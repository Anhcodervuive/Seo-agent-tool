import datetime
import json
import os
import threading
import time

import requests
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
from google.oauth2 import service_account
from googleapiclient.discovery import build

from app.models import (
    Client,
    Competitor,
    CompetitorInsight,
    BacklinkHistory,
    CrawlIssue,
    CrawlPage,
    CrawlPageImage,
    CrawlPageLink,
    CrawlPageStructuredData,
    Ga4Metric,
    GscMetric,
    Keyword,
    Ranking,
    Snapshot,
    db,
)
from services.ai_settings import get_effective_ai_settings
from services.dataforseo import enrich_keywords, get_backlink_metrics, get_competitor_insights, get_keyword_ranking
from services.google_accounts import get_credentials_path_for_client
from services.site_urls import normalize_site_url

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CRAWLER_URL = os.environ.get("LIBRECRAWL_URL", "http://127.0.0.1:5080")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
CRAWLER_REQUEST_TIMEOUT = int(os.environ.get("LIBRECRAWL_REQUEST_TIMEOUT", "120"))
CRAWLER_POLL_INTERVAL = int(os.environ.get("LIBRECRAWL_POLL_INTERVAL", "5"))
CRAWLER_MAX_POLLS = int(os.environ.get("LIBRECRAWL_MAX_POLLS", "60"))


def _log(message):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {message}")


def _update_snapshot_notes(snapshot, payload, status=None):
    if status:
        snapshot.status = status
    snapshot.notes = json.dumps(payload)
    db.session.commit()


def _coerce_list(value):
    if isinstance(value, list):
        return value
    if value in (None, "", {}):
        return []
    return [value]


def _coerce_dict(value):
    return value if isinstance(value, dict) else None


def _coerce_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None


def _extract_schema_type(payload):
    if isinstance(payload, dict):
        schema_type = payload.get("@type") or payload.get("type")
        if isinstance(schema_type, list):
            return ", ".join(str(item) for item in schema_type if item)
        if schema_type:
            return str(schema_type)
    return None


def _persist_crawl_export(snapshot, crawl_id, crawl_payload):
    urls = crawl_payload.get("urls", []) or []
    links = crawl_payload.get("links", []) or []
    issues = crawl_payload.get("issues", []) or []

    snapshot.librecrawl_crawl_id = crawl_id
    db.session.flush()

    db.session.query(CrawlPageStructuredData).filter_by(snapshot_id=snapshot.id).delete()
    db.session.query(CrawlPageImage).filter_by(snapshot_id=snapshot.id).delete()
    db.session.query(CrawlPageLink).filter_by(snapshot_id=snapshot.id).delete()
    db.session.query(CrawlPage).filter_by(snapshot_id=snapshot.id).delete()
    db.session.query(CrawlIssue).filter_by(snapshot_id=snapshot.id).delete()
    db.session.flush()

    image_count = 0
    structured_count = 0
    persisted_page_urls = set()

    for item in urls:
        page_url = (item.get("url") or "").strip()
        if not page_url or page_url in persisted_page_urls:
            continue
        persisted_page_urls.add(page_url)
        page = CrawlPage(
            snapshot_id=snapshot.id,
            url=page_url,
            status_code=_coerce_int(item.get("status_code")),
            content_type=item.get("content_type"),
            size=_coerce_int(item.get("size")),
            is_internal=_coerce_bool(item.get("is_internal")),
            depth=_coerce_int(item.get("depth")),
            title=item.get("title"),
            meta_description=item.get("meta_description"),
            h1=item.get("h1"),
            h2=_coerce_list(item.get("h2")),
            h3=_coerce_list(item.get("h3")),
            word_count=_coerce_int(item.get("word_count")),
            canonical_url=item.get("canonical_url"),
            lang=item.get("lang"),
            charset=item.get("charset"),
            viewport=item.get("viewport"),
            robots=item.get("robots"),
            meta_tags=_coerce_dict(item.get("meta_tags")) or {},
            og_tags=_coerce_dict(item.get("og_tags")) or {},
            twitter_tags=_coerce_dict(item.get("twitter_tags")) or {},
            json_ld=_coerce_list(item.get("json_ld")),
            analytics=_coerce_dict(item.get("analytics")) or {},
            hreflang=_coerce_list(item.get("hreflang")),
            schema_org=_coerce_list(item.get("schema_org")),
            redirects=_coerce_list(item.get("redirects")),
            linked_from=_coerce_list(item.get("linked_from")),
            external_links=_coerce_int(item.get("external_links")),
            internal_links=_coerce_int(item.get("internal_links")),
            response_time=_coerce_float(item.get("response_time")),
            javascript_rendered=_coerce_bool(item.get("javascript_rendered")) or False,
            error_type=item.get("error_type"),
            crawled_at=item.get("crawled_at"),
        )
        db.session.add(page)
        db.session.flush()

        for index, image in enumerate(_coerce_list(item.get("images")), start=1):
            if isinstance(image, dict):
                image_url = image.get("src") or image.get("url")
                alt_text = image.get("alt")
                width = _coerce_int(image.get("width"))
                height = _coerce_int(image.get("height"))
                file_size_bytes = _coerce_int(
                    image.get("file_size_bytes")
                    or image.get("size_bytes")
                    or image.get("file_size")
                )
            else:
                image_url = str(image)
                alt_text = None
                width = None
                height = None
                file_size_bytes = None
            if not image_url:
                continue
            db.session.add(
                CrawlPageImage(
                    snapshot_id=snapshot.id,
                    page_id=page.id,
                    page_url=page.url,
                    image_url=image_url,
                    alt_text=alt_text,
                    width=width,
                    height=height,
                    file_size_bytes=file_size_bytes,
                    position=index,
                )
            )
            image_count += 1

        for source_name, payloads in (
            ("json_ld", _coerce_list(item.get("json_ld"))),
            ("schema_org", _coerce_list(item.get("schema_org"))),
        ):
            for index, payload in enumerate(payloads, start=1):
                db.session.add(
                    CrawlPageStructuredData(
                        snapshot_id=snapshot.id,
                        page_id=page.id,
                        page_url=page.url,
                        source=source_name,
                        schema_type=_extract_schema_type(payload),
                        payload=payload,
                        position=index,
                    )
                )
                structured_count += 1

    for link in links:
        db.session.add(
            CrawlPageLink(
                snapshot_id=snapshot.id,
                source_url=link.get("source_url") or "",
                target_url=link.get("target_url") or "",
                anchor_text=link.get("anchor_text"),
                is_internal=_coerce_bool(link.get("is_internal")),
                target_domain=link.get("target_domain"),
                target_status=_coerce_int(link.get("target_status")),
                placement=link.get("placement"),
                discovered_at=link.get("discovered_at"),
            )
        )

    for item in issues:
        db.session.add(
            CrawlIssue(
                snapshot_id=snapshot.id,
                url=item.get("url"),
                issue=item.get("issue"),
                issue_type=item.get("type") or item.get("issue_type"),
                category=item.get("category"),
                details=item.get("details"),
            )
        )

    db.session.commit()
    return {
        "crawl_issues": len(issues),
        "crawl": len(issues),
        "crawl_pages": len(persisted_page_urls),
        "crawl_links": len(links),
        "crawl_images": image_count,
        "crawl_structured_data": structured_count,
    }


def _pull_crawl(snapshot, client):
    session = requests.Session()
    login_response = session.post(
        f"{CRAWLER_URL}/api/guest-login",
        json={},
        timeout=CRAWLER_REQUEST_TIMEOUT,
    )
    login_response.raise_for_status()

    target_url = normalize_site_url(client.domain)
    _log(f"  crawl start requested for {target_url}")
    response = session.post(
        f"{CRAWLER_URL}/api/start_crawl",
        json={"url": target_url},
        timeout=CRAWLER_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("success"):
        raise RuntimeError(f"crawl start failed: {data}")

    crawl_id = data["crawl_id"]
    snapshot.librecrawl_crawl_id = crawl_id
    db.session.commit()
    _log(f"  crawl started with crawl_id={crawl_id}")
    crawl_state = None
    for index in range(CRAWLER_MAX_POLLS):
        time.sleep(CRAWLER_POLL_INTERVAL)
        status_response = session.get(
            f"{CRAWLER_URL}/api/crawls/{crawl_id}",
            timeout=CRAWLER_REQUEST_TIMEOUT,
        )
        status_response.raise_for_status()
        crawl_state = status_response.json()
        status = crawl_state.get("crawl", {}).get("status")
        _log(f"  crawl status poll {index + 1}/{CRAWLER_MAX_POLLS}: {status}")
        if status == "completed":
            break
    else:
        raise RuntimeError(
            f"crawl did not complete within {CRAWLER_MAX_POLLS * CRAWLER_POLL_INTERVAL} seconds"
        )

    return _persist_crawl_export(snapshot, crawl_id, crawl_state or {})


def _pull_ga4(snapshot, client):
    if not client.ga4_property_id:
        return 0

    creds = service_account.Credentials.from_service_account_file(get_credentials_path_for_client(client))
    analytics = BetaAnalyticsDataClient(credentials=creds)
    start = (datetime.date.today() - datetime.timedelta(days=28)).isoformat()
    end = datetime.date.today().isoformat()
    metric_names = [
        "totalUsers",
        "sessions",
        "averageSessionDuration",
        "eventCount",
        "engagementRate",
    ]
    dimension_map = {
        "channel": "sessionDefaultChannelGroup",
        "page_path": "pagePath",
        "country": "country",
        "device": "deviceCategory",
    }
    count = 0

    for dimension_prefix, dimension_name in dimension_map.items():
        request = RunReportRequest(
            property=f"properties/{client.ga4_property_id}",
            date_ranges=[DateRange(start_date=start, end_date=end)],
            metrics=[Metric(name=name) for name in metric_names],
            dimensions=[Dimension(name=dimension_name)],
        )
        response = analytics.run_report(request)

        for row in response.rows:
            dimension_value = row.dimension_values[0].value
            prefixed_dimension = f"{dimension_prefix}::{dimension_value}"
            for idx, metric_name in enumerate(metric_names):
                db.session.add(
                    Ga4Metric(
                        snapshot_id=snapshot.id,
                        metric_name=metric_name,
                        metric_value=float(row.metric_values[idx].value),
                        dimension=prefixed_dimension,
                        period_start=start,
                        period_end=end,
                    )
                )
                count += 1
    db.session.commit()
    return count


def _pull_gsc(snapshot, client):
    if not client.gsc_site_url:
        return 0

    creds = service_account.Credentials.from_service_account_file(
        get_credentials_path_for_client(client),
        scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
    )
    service = build("searchconsole", "v1", credentials=creds)
    end = datetime.date.today() - datetime.timedelta(days=3)
    start = end - datetime.timedelta(days=28)
    dimension_sets = [
        ("queries", ["query"]),
        ("urls", ["page"]),
        ("country", ["country"]),
        ("device", ["device"]),
    ]

    total_rows = 0
    for view_name, dimensions in dimension_sets:
        response = service.searchanalytics().query(
            siteUrl=client.gsc_site_url,
            body={
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "dimensions": dimensions,
                "rowLimit": 100,
            },
        ).execute()

        rows = response.get("rows", [])
        for row in rows:
            key_value = row["keys"][0] if row.get("keys") else ""
            query_value = None
            page_value = None

            if view_name == "queries":
                query_value = f"query::{key_value}"
            elif view_name == "urls":
                page_value = f"page::{key_value}"
            elif view_name == "country":
                query_value = f"country::{key_value}"
            elif view_name == "device":
                query_value = f"device::{key_value}"

            db.session.add(
                GscMetric(
                    snapshot_id=snapshot.id,
                    query=query_value,
                    page=page_value,
                    clicks=row.get("clicks"),
                    impressions=row.get("impressions"),
                    ctr=row.get("ctr"),
                    position=row.get("position"),
                    period_start=start.isoformat(),
                    period_end=end.isoformat(),
                )
            )
        total_rows += len(rows)

    db.session.commit()
    return total_rows


def _pull_rankings(snapshot, client):
    tracked_keywords = Keyword.query.filter_by(client_id=client.id).all()
    keywords = [row.keyword for row in tracked_keywords if row.keyword]
    if not keywords:
        return 0

    enriched, cost = enrich_keywords(keywords, location_name=client.location or "United States")
    ranking_cost = 0.0
    count = 0
    targets = [(None, client.domain)] + [(competitor.id, competitor.domain) for competitor in Competitor.query.filter_by(client_id=client.id).all()]
    for competitor_id, domain in targets:
        target = f"*{domain}*"
        for keyword in tracked_keywords:
            details = enriched.get(keyword.keyword, {})
            ranking_data = {"position": None, "url": None}
            try:
                ranking_data, single_cost = get_keyword_ranking(
                    keyword=keyword.keyword,
                    target=target,
                    location_name=keyword.location or client.location or "United States",
                    language_code=keyword.language or "en",
                    device=keyword.device or "desktop",
                )
                ranking_cost += single_cost
            except RuntimeError as exc:
                if "No Search Results" not in str(exc):
                    raise
                _log(f"  rankings: no live ranking found for '{keyword.keyword}' on target {target}")
            db.session.add(
                Ranking(
                    snapshot_id=snapshot.id,
                    competitor_id=competitor_id,
                    keyword=keyword.keyword,
                    position=ranking_data.get("position"),
                    search_volume=details.get("search_volume"),
                    url=ranking_data.get("url"),
                    location=keyword.location or client.location,
                    device=keyword.device or "desktop",
                )
            )
            count += 1
    db.session.commit()
    _log(f"  rankings cost: ${cost + ranking_cost}; rows={count}; targets={len(targets)}")
    return count


def _pull_backlinks(snapshot, client):
    targets = [(None, client.domain)] + [(competitor.id, competitor.domain) for competitor in Competitor.query.filter_by(client_id=client.id).all()]
    count = 0
    total_cost = 0.0
    errors = []
    for competitor_id, domain in targets:
        try:
            metrics, cost = get_backlink_metrics(domain)
            db.session.add(
                BacklinkHistory(
                    snapshot_id=snapshot.id,
                    competitor_id=competitor_id,
                    total_backlinks=metrics.get("total_backlinks", 0),
                    referring_domains=metrics.get("referring_domains", 0),
                    new_backlinks=metrics.get("new_backlinks", 0),
                    lost_backlinks=metrics.get("lost_backlinks", 0),
                )
            )
            total_cost += cost
            count += 1
        except Exception as exc:
            errors.append(f"{domain}: {exc}")
            _log(f"  backlinks failed for {domain}: {exc}")
    if count:
        db.session.commit()
    if errors and not count:
        raise RuntimeError("; ".join(errors))
    _log(f"  backlinks cost: ${total_cost}; targets={len(targets)}; stored={count}")
    return {"rows": count, "targets": len(targets), "cost": total_cost, "errors": errors}


def _pull_competitor_insights(snapshot, client):
    competitors = Competitor.query.filter_by(client_id=client.id).all()
    if not competitors:
        return {"rows": 0, "targets": 0, "cost": 0.0, "errors": []}

    count = 0
    total_cost = 0.0
    errors = []
    for competitor in competitors:
        try:
            insight_data, cost = get_competitor_insights(competitor.domain, location_name=client.location or "United States")
            backlink = BacklinkHistory.query.filter_by(
                snapshot_id=snapshot.id,
                competitor_id=competitor.id,
            ).first()
            summary = insight_data.get("summary") or {}
            if backlink:
                summary.update({
                    "backlinks": backlink.total_backlinks,
                    "referring_domains": backlink.referring_domains,
                    "new_backlinks": backlink.new_backlinks,
                    "lost_backlinks": backlink.lost_backlinks,
                })
            db.session.add(CompetitorInsight(
                client_id=client.id,
                competitor_id=competitor.id,
                snapshot_id=snapshot.id,
                target_domain=insight_data.get("target") or competitor.domain,
                status="complete",
                summary=summary,
                ranked_keywords=insight_data.get("ranked_keywords") or [],
                top_pages=insight_data.get("top_pages") or [],
            ))
            count += 1
            total_cost += cost
        except Exception as exc:
            errors.append(f"{competitor.domain}: {exc}")
            db.session.add(CompetitorInsight(
                client_id=client.id,
                competitor_id=competitor.id,
                snapshot_id=snapshot.id,
                target_domain=competitor.domain,
                status="failed",
                error_message=str(exc),
            ))
            _log(f"  competitor insights failed for {competitor.domain}: {exc}")
    db.session.commit()
    _log(f"  competitor insights cost: ${total_cost}; targets={len(competitors)}; stored={count}")
    return {"rows": count, "targets": len(competitors), "cost": total_cost, "errors": errors}


def _generate_report(snapshot, client):
    from services import analyze

    brief = analyze.build_brief_from_models(client.id, snapshot.id)
    ai_settings = get_effective_ai_settings(client.id)
    report = analyze.generate(
        brief,
        model_name=ai_settings["model_name"],
        system_prompt=ai_settings["system_prompt"],
    )
    os.makedirs(REPORTS_DIR, exist_ok=True)
    filename = os.path.join(REPORTS_DIR, f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}.md")
    with open(filename, "w", encoding="utf-8") as handle:
        handle.write(
            f"# SEO Report - {client.name}\n"
            f"_Snapshot {snapshot.id} · {datetime.datetime.now():%Y-%m-%d}_\n\n{report}\n"
        )
    return filename, ai_settings


def _run_snapshot_job(app, snapshot_id, client_id):
    with app.app_context():
        snapshot = db.session.get(Snapshot, snapshot_id)
        client = db.session.get(Client, client_id)
        if not snapshot or not client:
            return

        snapshot.status = "running"
        db.session.commit()
        results = {}
        try:
            for label, job in [
                ("crawl", lambda: _pull_crawl(snapshot, client)),
                ("ga4", lambda: _pull_ga4(snapshot, client)),
                ("gsc", lambda: _pull_gsc(snapshot, client)),
                ("rankings", lambda: _pull_rankings(snapshot, client)),
                ("backlinks", lambda: _pull_backlinks(snapshot, client)),
                ("competitor_insights", lambda: _pull_competitor_insights(snapshot, client)),
            ]:
                try:
                    job_result = job()
                    if label == "crawl" and isinstance(job_result, dict):
                        results.update(job_result)
                        _log(
                            "  crawl: "
                            f"{job_result.get('crawl', 0)} issues, "
                            f"{job_result.get('crawl_pages', 0)} pages, "
                            f"{job_result.get('crawl_links', 0)} links, "
                            f"{job_result.get('crawl_images', 0)} images, "
                            f"{job_result.get('crawl_structured_data', 0)} structured data rows"
                        )
                    else:
                        results[label] = job_result
                        _log(f"  {label}: {results[label]} rows")
                    _update_snapshot_notes(snapshot, results, status=snapshot.status)
                except Exception as exc:
                    db.session.rollback()
                    results[label] = f"FAILED: {exc}"
                    _log(f"  {label} FAILED: {exc}")
                    _update_snapshot_notes(snapshot, results, status="partial")

            try:
                report_path, ai_settings = _generate_report(snapshot, client)
                results["report"] = os.path.basename(report_path)
                results["ai_model"] = ai_settings["model_name"]
                results["ai_settings_source"] = ai_settings["source"]
            except Exception as exc:
                results["report"] = f"FAILED: {exc}"
                _log(f"  report FAILED: {exc}")

            failures = [
                value for value in results.values()
                if str(value).startswith("FAILED")
                or (isinstance(value, dict) and value.get("errors"))
            ]
            final_status = "complete" if not failures else "partial"
            _update_snapshot_notes(snapshot, results, status=final_status)
        except Exception as exc:
            db.session.rollback()
            results["job"] = f"FAILED: {exc}"
            _log(f"  snapshot job FAILED: {exc}")
            _update_snapshot_notes(snapshot, results, status="failed")


def enqueue_snapshot_job(app, client_id):
    snapshot = Snapshot(client_id=client_id, status="pending", notes=json.dumps({"queued": True}))
    db.session.add(snapshot)
    db.session.commit()

    worker = threading.Thread(
        target=_run_snapshot_job,
        args=(app, snapshot.id, client_id),
        daemon=True,
    )
    worker.start()
    return snapshot
