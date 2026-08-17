import datetime
import json
import os
import time

import requests

from app.models import (
    Client,
    Competitor,
    CompetitorInsight,
    BacklinkAnchor,
    BacklinkHistory,
    BacklinkItem,
    BacklinkReferringDomain,
    CrawlIssue,
    CrawlPage,
    CrawlPageImage,
    CrawlPageLink,
    CrawlPageStructuredData,
    Keyword,
    Ranking,
    Snapshot,
    db,
)
from services.ai_settings import get_effective_ai_settings
from services.dataforseo import (
    enrich_keyword_contexts,
    get_backlink_detail_report,
    get_backlink_metrics,
    get_competitor_insights,
    get_keyword_ranking,
)
from services.ga4 import GA4_DIMENSIONS, GA4_REPORT_METRICS, cache_ga4_metrics, fetch_ga4_metrics
from services.gsc import GSC_VIEWS, cache_gsc_metrics, fetch_gsc_metrics
from services.crawl_scope import build_crawl_scope

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CRAWLER_URL = os.environ.get("LIBRECRAWL_URL", "http://127.0.0.1:5080")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
CRAWLER_REQUEST_TIMEOUT = int(os.environ.get("LIBRECRAWL_REQUEST_TIMEOUT", "120"))
CRAWLER_POLL_INTERVAL = int(os.environ.get("LIBRECRAWL_POLL_INTERVAL", "5"))
CRAWLER_MAX_POLLS = int(os.environ.get("LIBRECRAWL_MAX_POLLS", "60"))


def _log(message):
    # Docker captures stdout.  Flush every stage message so `docker logs -f`
    # and Docker Desktop show the live pipeline activity rather than waiting
    # for Python's buffered output to be written at process shutdown.
    print(f"[{datetime.datetime.now():%H:%M:%S}] {message}", flush=True)


def _update_snapshot_notes(snapshot, payload, status=None):
    # Progress is written independently while a job is running. Preserve it
    # when a completed pipeline stage replaces the summary notes.
    if "progress" not in payload or "run" not in payload:
        try:
            existing_notes = json.loads(snapshot.notes) if snapshot.notes else {}
        except json.JSONDecodeError:
            existing_notes = {}
        if isinstance(existing_notes, dict):
            payload = dict(payload)
            if "progress" not in payload and existing_notes.get("progress"):
                payload["progress"] = existing_notes["progress"]
            if "run" not in payload and existing_notes.get("run"):
                payload["run"] = existing_notes["run"]
    if status:
        snapshot.status = status
    snapshot.notes = json.dumps(payload)
    db.session.commit()


def _update_snapshot_progress(snapshot, **updates):
    """Persist live crawl/ranking progress without changing stage results."""
    try:
        notes = json.loads(snapshot.notes) if snapshot.notes else {}
    except json.JSONDecodeError:
        notes = {}
    if not isinstance(notes, dict):
        notes = {}

    progress = notes.get("progress") if isinstance(notes.get("progress"), dict) else {}
    progress.update({key: value for key, value in updates.items() if value is not None})
    progress["updated_at"] = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    notes["progress"] = progress
    snapshot.notes = json.dumps(notes)
    db.session.commit()


def _crawl_progress_values(crawl_state, live_state=None):
    """Normalize LibreCrawl's live stats into dashboard-friendly counters."""
    crawl_meta = crawl_state.get("crawl", {}) if isinstance(crawl_state, dict) else {}
    live_stats = live_state.get("stats", {}) if isinstance(live_state, dict) else {}
    if not isinstance(crawl_meta, dict):
        crawl_meta = {}
    if not isinstance(live_stats, dict):
        live_stats = {}

    def first_number(*values):
        for value in values:
            if value is None or value == "":
                continue
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                continue
        return 0

    crawled = first_number(
        live_stats.get("crawled"),
        live_stats.get("urls_crawled"),
        crawl_meta.get("urls_crawled"),
    )
    discovered = first_number(
        live_stats.get("discovered"),
        live_stats.get("urls_discovered"),
        crawl_meta.get("urls_discovered"),
    )
    return {
        "crawled_urls": crawled,
        "discovered_urls": discovered,
        "pending_urls": max(discovered - crawled, 0),
    }


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


def _copy_row_values(row, model, excluded=None):
    excluded = set(excluded or ())
    return {
        column.name: getattr(row, column.name)
        for column in model.__table__.columns
        if column.name not in {"id", *excluded}
    }


def _reuse_previous_crawl(snapshot, client):
    """Copy the most recent persisted crawl into a new snapshot.

    The copy is intentionally snapshot-local. Later analysis stages can still
    fetch fresh GA4, GSC, rankings, and backlink data without calling the
    crawler again.
    """
    source_id = (
        db.session.query(CrawlPage.snapshot_id)
        .join(Snapshot, Snapshot.id == CrawlPage.snapshot_id)
        .filter(Snapshot.client_id == client.id, Snapshot.id != snapshot.id)
        .order_by(Snapshot.created_at.desc(), Snapshot.id.desc())
        .first()
    )
    if not source_id:
        raise RuntimeError("No previous crawl is available. Run a full crawl before using Reuse previous crawl.")

    source = db.session.get(Snapshot, source_id[0])
    _update_snapshot_progress(
        snapshot,
        phase="crawl",
        phase_label="Reusing previous crawl",
        message=f"Copying crawl data from snapshot #{source.id}...",
        crawled_urls=0,
        pending_urls=0,
    )

    page_ids = {}
    page_urls = {}
    source_pages = CrawlPage.query.filter_by(snapshot_id=source.id).order_by(CrawlPage.id).all()
    for source_page in source_pages:
        page = CrawlPage(
            snapshot_id=snapshot.id,
            **_copy_row_values(source_page, CrawlPage, {"snapshot_id"}),
        )
        db.session.add(page)
        db.session.flush()
        page_ids[source_page.id] = page.id
        page_urls[source_page.url] = page.id

    for source_issue in CrawlIssue.query.filter_by(snapshot_id=source.id).all():
        db.session.add(CrawlIssue(
            snapshot_id=snapshot.id,
            **_copy_row_values(source_issue, CrawlIssue, {"snapshot_id"}),
        ))
    for source_link in CrawlPageLink.query.filter_by(snapshot_id=source.id).all():
        db.session.add(CrawlPageLink(
            snapshot_id=snapshot.id,
            **_copy_row_values(source_link, CrawlPageLink, {"snapshot_id"}),
        ))
    for source_image in CrawlPageImage.query.filter_by(snapshot_id=source.id).all():
        page_id = page_ids.get(source_image.page_id) or page_urls.get(source_image.page_url)
        db.session.add(CrawlPageImage(
            snapshot_id=snapshot.id,
            page_id=page_id,
            **_copy_row_values(source_image, CrawlPageImage, {"snapshot_id", "page_id"}),
        ))
    for source_schema in CrawlPageStructuredData.query.filter_by(snapshot_id=source.id).all():
        page_id = page_ids.get(source_schema.page_id) or page_urls.get(source_schema.page_url)
        db.session.add(CrawlPageStructuredData(
            snapshot_id=snapshot.id,
            page_id=page_id,
            **_copy_row_values(source_schema, CrawlPageStructuredData, {"snapshot_id", "page_id"}),
        ))

    try:
        notes = json.loads(snapshot.notes) if snapshot.notes else {}
    except json.JSONDecodeError:
        notes = {}
    notes.setdefault("run", {})["reused_from_snapshot_id"] = source.id
    snapshot.notes = json.dumps(notes)
    db.session.commit()

    result = {
        "crawl": CrawlIssue.query.filter_by(snapshot_id=snapshot.id).count(),
        "crawl_issues": CrawlIssue.query.filter_by(snapshot_id=snapshot.id).count(),
        "crawl_pages": len(source_pages),
        "crawl_links": CrawlPageLink.query.filter_by(snapshot_id=snapshot.id).count(),
        "crawl_images": CrawlPageImage.query.filter_by(snapshot_id=snapshot.id).count(),
        "crawl_structured_data": CrawlPageStructuredData.query.filter_by(snapshot_id=snapshot.id).count(),
    }
    _update_snapshot_progress(
        snapshot,
        phase="crawl",
        phase_label="Previous crawl reused",
        crawled_urls=result["crawl_pages"],
        discovered_urls=result["crawl_pages"],
        pending_urls=0,
        message=f"Reused {result['crawl_pages']} crawled URLs from snapshot #{source.id}.",
    )
    return result


def _pull_crawl(snapshot, client, crawl_scope=None):
    crawl_scope = crawl_scope or build_crawl_scope(client)
    crawl_mode = crawl_scope["mode"]
    if crawl_mode == "reuse":
        return _reuse_previous_crawl(snapshot, client)

    _update_snapshot_progress(
        snapshot,
        phase="crawl",
        phase_label="Starting website crawl",
        crawled_urls=0,
        discovered_urls=0,
        pending_urls=0,
        message=(
            "Connecting to the crawler for the selected URLs..."
            if crawl_mode == "selected_urls"
            else "Connecting to the crawler..."
        ),
    )
    session = requests.Session()
    login_response = session.post(
        f"{CRAWLER_URL}/api/guest-login",
        json={},
        timeout=CRAWLER_REQUEST_TIMEOUT,
    )
    login_response.raise_for_status()

    target_url = crawl_scope["site_origin"]
    _log(f"  crawl start requested for {target_url} ({crawl_mode})")
    response = session.post(
        f"{CRAWLER_URL}/api/start_crawl",
        json={
            "url": target_url,
            "seed_urls": crawl_scope.get("seed_urls", []),
            "crawl_scope": {
                key: value
                for key, value in crawl_scope.items()
                if key not in {"site_origin", "seed_urls"}
            },
        },
        timeout=CRAWLER_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("success"):
        raise RuntimeError(f"crawl start failed: {data}")

    crawl_id = data["crawl_id"]
    snapshot.librecrawl_crawl_id = crawl_id
    db.session.commit()
    _update_snapshot_progress(
        snapshot,
        phase="crawl",
        phase_label="Crawling website",
        crawl_id=crawl_id,
        message="Discovering and crawling URLs...",
    )
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
        live_state = None
        try:
            live_response = session.get(
                f"{CRAWLER_URL}/api/crawl_status",
                timeout=CRAWLER_REQUEST_TIMEOUT,
            )
            live_response.raise_for_status()
            live_state = live_response.json()
        except (requests.RequestException, ValueError):
            # The persisted crawl metadata is still enough to complete the
            # import if the optional live-status endpoint is unavailable.
            live_state = None
        live_counts = _crawl_progress_values(crawl_state, live_state)
        _update_snapshot_progress(
            snapshot,
            phase="crawl",
            phase_label="Crawling website",
            **live_counts,
            message=(
                f"{live_counts['crawled_urls']} URLs crawled; "
                f"{live_counts['pending_urls']} URLs pending."
            ),
        )
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

    start = (datetime.date.today() - datetime.timedelta(days=28)).isoformat()
    end = datetime.date.today().isoformat()
    fetched = fetch_ga4_metrics(client, start, end, GA4_DIMENSIONS.keys())
    count = 0
    for dimension_key, rows in fetched.items():
        cache_ga4_metrics(snapshot, start, end, dimension_key, rows)
        count += len(rows) * len(GA4_REPORT_METRICS)
    return count


def _pull_gsc(snapshot, client):
    if not client.gsc_site_url:
        return 0

    end = datetime.date.today() - datetime.timedelta(days=3)
    start = end - datetime.timedelta(days=28)
    fetched = fetch_gsc_metrics(client, start.isoformat(), end.isoformat(), GSC_VIEWS.keys())
    total_rows = 0
    for view_name, rows in fetched.items():
        cache_gsc_metrics(snapshot, start.isoformat(), end.isoformat(), view_name, rows)
        total_rows += len(rows)
    return total_rows


def _pull_rankings(snapshot, client):
    tracked_keywords = [row for row in Keyword.query.filter_by(client_id=client.id).all() if row.keyword]
    keywords = [row.keyword for row in tracked_keywords]
    targets = [(None, client.domain)] + [(competitor.id, competitor.domain) for competitor in Competitor.query.filter_by(client_id=client.id).all()]
    total_checks = len(targets) * len(tracked_keywords)
    if not keywords:
        _update_snapshot_progress(
            snapshot,
            phase="rankings",
            phase_label="Checking keyword rankings",
            ranking_completed=0,
            ranking_pending=0,
            ranking_total=0,
            message="No tracked keywords are configured.",
        )
        return {"rows": 0, "ranked_rows": 0, "not_ranking_rows": 0, "targets": 0, "cost": 0.0, "errors": []}

    _update_snapshot_progress(
        snapshot,
        phase="rankings",
        phase_label="Checking keyword rankings",
        ranking_completed=0,
        ranking_pending=total_checks,
        ranking_total=total_checks,
        message=f"Preparing {total_checks} ranking checks...",
    )
    errors = []
    try:
        enriched, cost = enrich_keyword_contexts([
            {
                "keyword": keyword.keyword,
                "location": keyword.location or client.location or "United States",
                "language": keyword.language or "en",
            }
            for keyword in tracked_keywords
        ])
    except Exception as exc:
        enriched, cost = {}, 0.0
        errors.append(f"keyword enrichment: {exc}")
        _log(f"  rankings keyword enrichment failed: {exc}")
    ranking_cost = 0.0
    count = 0
    ranked_count = 0
    not_ranking_count = 0
    completed_checks = 0
    for competitor_id, domain in targets:
        # Pass the raw domain. get_keyword_ranking normalizes it and adds
        # exactly one wildcard pair for DataForSEO's target field.
        target = domain
        for keyword in tracked_keywords:
            location_name = keyword.location or client.location or "United States"
            language_code = keyword.language or "en"
            details = enriched.get(
                ((keyword.keyword or "").strip().casefold(), location_name.strip().casefold(), language_code.strip().casefold()),
                {},
            )
            ranking_data = {"status": "not_found", "position": None, "url": None}
            error_message = None
            try:
                ranking_data, single_cost = get_keyword_ranking(
                    keyword=keyword.keyword,
                    target=target,
                    location_name=location_name,
                    language_code=language_code,
                    device=keyword.device or "desktop",
                )
                ranking_cost += single_cost
                if ranking_data.get("position") is None:
                    _log(
                        f"  rankings: '{keyword.keyword}' is not ranking in the checked top 100 "
                        f"for {target}"
                    )
            except Exception as exc:
                error_message = str(exc)[:1000]
                ranking_data = {"status": "failed", "position": None, "url": None}
                errors.append(f"{target} / {keyword.keyword}: {error_message}")
                _log(f"  rankings failed for '{keyword.keyword}' on target {target}: {error_message}")
            if ranking_data.get("position") is not None:
                ranked_count += 1
            else:
                not_ranking_count += 1
            completed_checks += 1
            _update_snapshot_progress(
                snapshot,
                phase="rankings",
                phase_label="Checking keyword rankings",
                ranking_completed=completed_checks,
                ranking_pending=max(total_checks - completed_checks, 0),
                ranking_total=total_checks,
                ranked_rows=ranked_count,
                not_ranking_rows=not_ranking_count,
                current_keyword=keyword.keyword,
                current_target=target,
                message=(
                    f"{completed_checks}/{total_checks} ranking checks complete; "
                    f"{max(total_checks - completed_checks, 0)} pending."
                ),
            )
            db.session.add(
                Ranking(
                    snapshot_id=snapshot.id,
                    competitor_id=competitor_id,
                    keyword=keyword.keyword,
                    position=ranking_data.get("position"),
                    search_volume=details.get("search_volume"),
                    url=ranking_data.get("url"),
                    location=location_name,
                    device=keyword.device or "desktop",
                    language=language_code,
                    check_status=ranking_data.get("status") or "not_found",
                    error_message=error_message,
                )
            )
            count += 1
    db.session.commit()
    _log(f"  rankings cost: ${cost + ranking_cost}; rows={count}; targets={len(targets)}")
    return {
        "rows": count,
        "ranked_rows": ranked_count,
        "not_ranking_rows": not_ranking_count,
        "targets": len(targets),
        "cost": cost + ranking_cost,
        "errors": errors,
    }


def _pull_backlinks(snapshot, client):
    _update_snapshot_progress(
        snapshot,
        phase="backlinks",
        phase_label="Collecting backlink metrics",
        message="Collecting backlink totals for the project and competitors...",
    )
    targets = [(None, client.domain)] + [(competitor.id, competitor.domain) for competitor in Competitor.query.filter_by(client_id=client.id).all()]
    count = 0
    total_cost = 0.0
    errors = []
    warnings = []
    client_metrics = {}
    detail_counts = {"backlinks": 0, "referring_domains": 0, "anchors": 0}
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
            if competitor_id is None:
                client_metrics = metrics
                _update_snapshot_progress(
                    snapshot,
                    phase="backlinks",
                    phase_label="Collecting backlink metrics",
                    message="Saving the project backlink details for this snapshot...",
                )
                try:
                    detail_report, detail_cost = get_backlink_detail_report(domain)
                    total_cost += detail_cost
                    db.session.add_all([
                        BacklinkItem(snapshot_id=snapshot.id, **row)
                        for row in detail_report.get("backlinks", [])
                    ])
                    db.session.add_all([
                        BacklinkReferringDomain(snapshot_id=snapshot.id, **row)
                        for row in detail_report.get("referring_domains", [])
                    ])
                    db.session.add_all([
                        BacklinkAnchor(snapshot_id=snapshot.id, **row)
                        for row in detail_report.get("anchors", [])
                    ])
                    detail_counts = {
                        "backlinks": len(detail_report.get("backlinks", [])),
                        "referring_domains": len(detail_report.get("referring_domains", [])),
                        "anchors": len(detail_report.get("anchors", [])),
                    }
                    warnings.extend(detail_report.get("warnings", []))
                except Exception as exc:
                    # Keep the summary usable if the optional detail endpoints
                    # are unavailable for the current DataForSEO account.
                    warning = f"Project backlink detail report was unavailable: {exc}"
                    warnings.append(warning)
                    _log(f"  backlinks detail failed for {domain}: {exc}")
            total_cost += cost
            count += 1
        except Exception as exc:
            errors.append(f"{domain}: {exc}")
            _log(f"  backlinks failed for {domain}: {exc}")
    if count:
        db.session.commit()
    if errors and not count:
        raise RuntimeError("; ".join(errors))
    _log(
        f"  backlinks cost: ${total_cost}; targets={len(targets)}; stored={count}; "
        f"detail={detail_counts['backlinks']} backlinks, "
        f"{detail_counts['referring_domains']} referring domains, "
        f"{detail_counts['anchors']} anchors"
    )
    return {
        "rows": count,
        "targets": len(targets),
        "cost": total_cost,
        "errors": errors,
        "warnings": warnings,
        "detail_rows": detail_counts,
        "client_total_backlinks": client_metrics.get("total_backlinks"),
        "client_referring_domains": client_metrics.get("referring_domains"),
        "client_new_backlinks": client_metrics.get("new_backlinks"),
        "client_lost_backlinks": client_metrics.get("lost_backlinks"),
    }


def _pull_competitor_insights(snapshot, client):
    _update_snapshot_progress(
        snapshot,
        phase="competitor_insights",
        phase_label="Collecting competitor insights",
        message="Collecting competitor visibility and top-page data...",
    )
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
        try:
            snapshot_notes = json.loads(snapshot.notes) if snapshot.notes else {}
        except json.JSONDecodeError:
            snapshot_notes = {}
        run_details = snapshot_notes.get("run") or {}
        crawl_scope = run_details.get("crawl_scope")
        run_type = run_details.get("type", "full_audit")
        keyword_count = Keyword.query.filter(
            Keyword.client_id == client_id,
            Keyword.keyword.isnot(None),
        ).count()
        competitor_count = Competitor.query.filter_by(client_id=client_id).count()
        initial_ranking_total = keyword_count * (competitor_count + 1)
        _update_snapshot_progress(
            snapshot,
            phase="rankings" if run_type == "rank_check" else "starting",
            phase_label="Starting ranking check" if run_type == "rank_check" else "Starting analysis",
            crawled_urls=0,
            pending_urls=0,
            ranking_completed=0,
            ranking_pending=initial_ranking_total,
            ranking_total=initial_ranking_total,
            message=(
                "Ranking checks are starting..."
                if run_type == "rank_check"
                else "Analysis is starting; ranking checks will begin after the crawl."
                if initial_ranking_total
                else "Analysis is starting..."
            ),
        )
        results = {}
        try:
            stages = (
                [("rankings", lambda: _pull_rankings(snapshot, client))]
                if run_type == "rank_check"
                else [
                    ("crawl", lambda: _pull_crawl(snapshot, client, crawl_scope)),
                    ("ga4", lambda: _pull_ga4(snapshot, client)),
                    ("gsc", lambda: _pull_gsc(snapshot, client)),
                    ("rankings", lambda: _pull_rankings(snapshot, client)),
                    ("backlinks", lambda: _pull_backlinks(snapshot, client)),
                    ("competitor_insights", lambda: _pull_competitor_insights(snapshot, client)),
                ]
            )
            for label, job in stages:
                try:
                    if label not in {"crawl", "rankings", "backlinks", "competitor_insights"}:
                        _update_snapshot_progress(
                            snapshot,
                            phase=label,
                            phase_label=label.replace("_", " ").title(),
                            message=f"Collecting {label.replace('_', ' ')} data...",
                        )
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

            if run_type == "rank_check":
                results["report"] = "Skipped for ranking-only check"
            else:
                try:
                    _update_snapshot_progress(
                        snapshot,
                        phase="report",
                        phase_label="Generating report",
                        message="Preparing the SEO report...",
                    )
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
            _update_snapshot_progress(
                snapshot,
                phase="complete" if final_status == "complete" else "partial",
                phase_label="Analysis complete" if final_status == "complete" else "Analysis completed with issues",
                pending_urls=0,
                ranking_pending=0,
                message=(
                    "All analysis stages completed."
                    if final_status == "complete"
                    else "Analysis completed, but one or more stages reported an issue."
                ),
            )
            _update_snapshot_notes(snapshot, results, status=final_status)
        except Exception as exc:
            db.session.rollback()
            results["job"] = f"FAILED: {exc}"
            _log(f"  snapshot job FAILED: {exc}")
            _update_snapshot_progress(
                snapshot,
                phase="failed",
                phase_label="Analysis failed",
                message=str(exc),
            )
            _update_snapshot_notes(snapshot, results, status="failed")


def enqueue_snapshot_job(app, client_id, crawl_scope=None, run_type="full_audit"):
    """Queue a durable job. ``app`` remains for backwards-compatible callers."""
    from services.audit_queue import queue_snapshot_job

    client = db.session.get(Client, client_id)
    if not client:
        raise ValueError("Project not found.")
    crawl_scope = crawl_scope or build_crawl_scope(client)
    snapshot, _job = queue_snapshot_job(client, crawl_scope=crawl_scope, run_type=run_type)
    return snapshot
