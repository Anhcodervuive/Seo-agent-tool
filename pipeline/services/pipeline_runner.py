import datetime
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import select

from app.models import (
    Client,
    Competitor,
    CompetitorCountryTraffic,
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
    RankingReconciliationJob,
    Snapshot,
    db,
)
from services.ai_settings import get_effective_ai_settings
from services.dataforseo import (
    DataForSEOError,
    DataForSEOTaskPending,
    enrich_keyword_contexts,
    get_keyword_ranking_task_result,
    get_backlink_detail_report,
    get_backlink_metrics,
    get_competitor_country_traffic,
    get_competitor_insights,
    get_ready_keyword_ranking_task_ids,
    queue_keyword_ranking_tasks,
)
from services.ga4 import (
    GA4_DIMENSIONS,
    GA4_REPORT_METRICS,
    cache_ga4_daily_metrics,
    cache_ga4_metrics,
    fetch_ga4_daily_metrics,
    fetch_ga4_metrics,
)
from services.gsc import (
    GSC_VIEWS,
    cache_gsc_daily_metrics,
    cache_gsc_metrics,
    fetch_gsc_daily_metrics,
    fetch_gsc_metrics,
)
from services.crawl_scope import build_crawl_scope
from services.dataforseo_locations import normalize_competitor_traffic_locations
from services.pipeline_stages import StageSpec, build_stage_plan, execute_stage, normalize_selected_stages
from services.pipeline_status import final_snapshot_status, load_notes, stage_summary
from services.librecrawl_client import LibreCrawlClient, LibreCrawlError, CrawlPoll
from services.reporting import build_report_context, write_markdown_report
from services.crawl_data import normalize_crawl_export, normalize_url
from services.health import persist_health_score

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CRAWLER_URL = os.environ.get("LIBRECRAWL_URL", "http://127.0.0.1:5080")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
CRAWLER_REQUEST_TIMEOUT = int(os.environ.get("LIBRECRAWL_REQUEST_TIMEOUT", "120"))
CRAWLER_POLL_INTERVAL = int(os.environ.get("LIBRECRAWL_POLL_INTERVAL", "5"))
CRAWLER_MAX_POLLS = int(os.environ.get("LIBRECRAWL_MAX_POLLS", "60"))
TREND_SYNC_DAYS = max(30, min(int(os.environ.get("TREND_SYNC_DAYS", "90")), 365))
RANKING_TASK_POLL_SECONDS = max(5, min(int(os.environ.get("DATAFORSEO_RANKING_POLL_SECONDS", "5")), 60))
RANKING_TASK_MAX_WAIT_SECONDS = max(60, min(int(os.environ.get("DATAFORSEO_RANKING_MAX_WAIT_SECONDS", "900")), 3600))
RANKING_TASK_FOREGROUND_WAIT_SECONDS = max(
    30,
    min(
        int(os.environ.get("DATAFORSEO_RANKING_FOREGROUND_WAIT_SECONDS", "300")),
        RANKING_TASK_MAX_WAIT_SECONDS,
    ),
)
RANKING_RECONCILIATION_POLL_SECONDS = max(
    15,
    min(int(os.environ.get("DATAFORSEO_RANKING_RECONCILIATION_POLL_SECONDS", "60")), 300),
)
RANKING_RECONCILIATION_STALE_MINUTES = max(
    5,
    min(int(os.environ.get("DATAFORSEO_RANKING_RECONCILIATION_STALE_MINUTES", "15")), 120),
)
RANKING_RESULT_WORKERS = max(1, min(int(os.environ.get("DATAFORSEO_RANKING_RESULT_WORKERS", "12")), 24))

PROGRESS_STAGE_LABELS = {
    "crawl": "Crawling website",
    "ga4": "Collecting GA4 data",
    "gsc": "Collecting Search Console data",
    "backlinks": "Collecting backlink data",
    "competitor_insights": "Collecting competitor data",
    "rankings": "Checking keyword rankings",
    "report": "Generating report",
}


def _progress_stage_label(stage):
    return PROGRESS_STAGE_LABELS.get(stage, str(stage).replace("_", " ").title())


def _progress_stage_message(stage):
    messages = {
        "crawl": "Crawling the selected website scope...",
        "ga4": "Collecting Google Analytics data...",
        "gsc": "Collecting Google Search Console data...",
        "backlinks": "Collecting backlink metrics...",
        "competitor_insights": "Collecting competitor visibility data...",
        "rankings": "Collecting available keyword ranking results...",
        "report": "Preparing the SEO report...",
    }
    return messages.get(stage, f"Running {str(stage).replace('_', ' ')}...")


def _ranking_task_priority():
    """Map the human-readable deployment setting to DataForSEO's priority."""
    configured = (os.environ.get("DATAFORSEO_RANKING_PRIORITY") or "normal").strip().lower()
    return 2 if configured in {"2", "high"} else 1


def _log(message):
    # Docker captures stdout.  Flush every stage message so `docker logs -f`
    # and Docker Desktop show the live pipeline activity rather than waiting
    # for Python's buffered output to be written at process shutdown.
    print(f"[{datetime.datetime.now():%H:%M:%S}] {message}", flush=True)


def _log_event(event, **fields):
    """Emit one JSON line which can be filtered by snapshot/job context.

    Do not pass credentials, authorization headers, or full provider payloads
    here.  Ranking terms and domains are already project data and are useful
    operational correlation fields.
    """
    payload = {"event": event, **{key: value for key, value in fields.items() if value is not None}}
    _log(json.dumps(payload, sort_keys=True, default=str))


def _error_diagnostic(exc):
    if isinstance(exc, DataForSEOError):
        return exc.diagnostic()
    response = getattr(exc, "response", None)
    return {
        "error_type": type(exc).__name__,
        "message": str(exc)[:1000],
        "http_status": getattr(response, "status_code", None),
    }


def _update_snapshot_notes(snapshot, payload, status=None):
    # Progress and Standard-ranking task state are written independently while
    # a job is running. Preserve them when a completed pipeline stage replaces
    # the summary notes, so a worker restart can resume submitted provider
    # tasks without paying to submit them a second time.
    preserved_keys = ("progress", "run", "ranking_task_state", "stage_results")
    if any(key not in payload for key in preserved_keys):
        try:
            existing_notes = json.loads(snapshot.notes) if snapshot.notes else {}
        except json.JSONDecodeError:
            existing_notes = {}
        if isinstance(existing_notes, dict):
            payload = dict(payload)
            for key in preserved_keys:
                if key not in payload and existing_notes.get(key):
                    payload[key] = existing_notes[key]
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
    normalized = normalize_crawl_export(crawl_payload)
    urls = normalized["urls"]
    links = normalized["links"]
    issues = normalized["issues"]

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
        page_url = normalize_url(item.get("url"))
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
            canonical_url=normalize_url(item.get("canonical_url")),
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
            linked_from=[url for url in (normalize_url(value) for value in _coerce_list(item.get("linked_from"))) if url],
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
                source_url=normalize_url(link.get("source_url")) or "",
                target_url=normalize_url(link.get("target_url")) or "",
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
                url=normalize_url(item.get("url")),
                issue=item.get("issue"),
                issue_type=item.get("type") or item.get("issue_type"),
                category=item.get("category"),
                details=item.get("details"),
            )
        )

    notes = {}
    try:
        notes = json.loads(snapshot.notes) if snapshot.notes else {}
    except json.JSONDecodeError:
        pass
    if not isinstance(notes, dict):
        notes = {}
    notes["crawl_quality"] = normalized["quality"]
    snapshot.notes = json.dumps(notes)
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
    crawler = LibreCrawlClient(
        CRAWLER_URL,
        timeout=CRAWLER_REQUEST_TIMEOUT,
        poll_interval=CRAWLER_POLL_INTERVAL,
        max_polls=CRAWLER_MAX_POLLS,
    )
    crawler.guest_login()

    target_url = crawl_scope["site_origin"]
    _log(f"  crawl start requested for {target_url} ({crawl_mode})")
    data = crawler.start_crawl(
        target_url,
        seed_urls=crawl_scope.get("seed_urls", []),
        crawl_scope={
            key: value
            for key, value in crawl_scope.items()
            if key not in {"site_origin", "seed_urls"}
        },
    )

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
    def on_poll(observation: CrawlPoll):
        crawl_state = observation.crawl_state
        live_state = observation.live_state
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
        _log(f"  crawl status poll {observation.poll_number}/{CRAWLER_MAX_POLLS}: {observation.status}")

    try:
        crawl_state = crawler.wait_for_completion(crawl_id, on_poll=on_poll)
    except LibreCrawlError:
        raise

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
    try:
        trend_start = (datetime.date.today() - datetime.timedelta(days=TREND_SYNC_DAYS - 1)).isoformat()
        daily_rows = fetch_ga4_daily_metrics(client, trend_start, end)
        cache_ga4_daily_metrics(client.id, snapshot.id, daily_rows)
        count += len(daily_rows)
    except Exception as exc:
        # A trend-only refresh must not discard a successful snapshot report.
        _log(f"  GA4 daily trend sync unavailable: {exc}")
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
    try:
        trend_start = (end - datetime.timedelta(days=TREND_SYNC_DAYS - 1)).isoformat()
        daily_rows = fetch_gsc_daily_metrics(client, trend_start, end.isoformat())
        cache_gsc_daily_metrics(client.id, snapshot.id, daily_rows)
        total_rows += len(daily_rows)
    except Exception as exc:
        # GSC may delay recent rows; preserve the successful snapshot cache.
        _log(f"  GSC daily trend sync unavailable: {exc}")
    return total_rows


def _ranking_task_state(snapshot):
    state = load_notes(snapshot.notes).get("ranking_task_state")
    if not isinstance(state, dict) or state.get("version") != 1:
        return None
    if not isinstance(state.get("checks"), dict) or not isinstance(state.get("completed"), dict):
        return None
    return state


def _save_ranking_task_state(snapshot, state, *, commit=True):
    notes = load_notes(snapshot.notes)
    notes["ranking_task_state"] = state
    snapshot.notes = json.dumps(notes)
    if commit:
        db.session.commit()


def _clear_ranking_task_state(snapshot):
    notes = load_notes(snapshot.notes)
    notes.pop("ranking_task_state", None)
    snapshot.notes = json.dumps(notes)
    db.session.commit()


def _ranking_check_id(snapshot_id, competitor_id, keyword_id):
    return f"snapshot-{snapshot_id}:target-{competitor_id or 'project'}:keyword-{keyword_id}"


def _ranking_outcome_error_message(outcome):
    diagnostic = outcome.get("error") if isinstance(outcome, dict) else None
    if not isinstance(diagnostic, dict):
        return None
    provider_code = diagnostic.get("provider_status_code")
    prefix = f"DataForSEO {provider_code}: " if provider_code else "DataForSEO: "
    return (prefix + (diagnostic.get("message") or "Ranking check failed."))[:1000]


def _ranking_counts(state):
    completed = state.get("completed") or {}
    outcomes = list(completed.values())
    return {
        "rows": len(outcomes),
        "ranked_rows": sum(1 for item in outcomes if item.get("status") == "found"),
        "not_ranking_rows": sum(1 for item in outcomes if item.get("status") == "not_found"),
        "failed_rows": sum(1 for item in outcomes if item.get("status") == "failed"),
    }


def _ranking_error_samples(state, limit=50):
    samples = []
    for warning in state.get("warnings") or []:
        if isinstance(warning, dict):
            samples.append(warning.get("message") or "Ranking preparation warning")
        elif warning:
            samples.append(str(warning))
    for check_id, outcome in (state.get("completed") or {}).items():
        if outcome.get("status") != "failed":
            continue
        check = (state.get("checks") or {}).get(check_id) or {}
        message = _ranking_outcome_error_message(outcome) or "Ranking check failed."
        samples.append(f"{check.get('target') or 'unknown target'} / {check.get('keyword') or 'unknown keyword'}: {message}")
        if len(samples) >= limit:
            break
    return samples[:limit]


def _persist_ranking_outcomes(snapshot, state, check_ids):
    """Upsert stored checks and their durable task state in one transaction."""
    checks = state.get("checks") or {}
    completed = state.get("completed") or {}
    for check_id in check_ids:
        check = checks.get(check_id)
        outcome = completed.get(check_id)
        if not check or not outcome:
            continue
        row = (
            Ranking.query.filter_by(
                snapshot_id=snapshot.id,
                competitor_id=check.get("competitor_id"),
                keyword=check.get("keyword"),
                location=check.get("location"),
                device=check.get("device"),
                language=check.get("language"),
            )
            .order_by(Ranking.id.desc())
            .first()
        )
        if not row:
            row = Ranking(snapshot_id=snapshot.id)
            db.session.add(row)
        row.competitor_id = check.get("competitor_id")
        row.keyword = check.get("keyword")
        row.position = outcome.get("position")
        row.search_volume = check.get("search_volume")
        row.url = outcome.get("url")
        row.location = check.get("location")
        row.device = check.get("device")
        row.language = check.get("language")
        row.check_status = outcome.get("status") or "failed"
        row.error_message = _ranking_outcome_error_message(outcome)
    _save_ranking_task_state(snapshot, state, commit=False)
    db.session.commit()


def _update_ranking_progress(
    snapshot,
    state,
    total_checks,
    *,
    message,
    current_check=None,
    ranking_state="collecting",
    ranking_state_label=None,
):
    counts = _ranking_counts(state)
    submitted = sum(1 for task_id in (state.get("task_ids") or {}).values() if task_id)
    _update_snapshot_progress(
        snapshot,
        phase="rankings",
        phase_label="Checking keyword rankings",
        ranking_completed=counts["rows"],
        ranking_pending=max(total_checks - counts["rows"], 0),
        ranking_total=total_checks,
        ranked_rows=counts["ranked_rows"],
        not_ranking_rows=counts["not_ranking_rows"],
        ranking_failed_rows=counts["failed_rows"],
        ranking_submitted=submitted,
        ranking_state=ranking_state,
        ranking_state_label=ranking_state_label,
        current_keyword=(current_check or {}).get("keyword"),
        current_target=(current_check or {}).get("target"),
        message=message,
    )


def _prepare_ranking_task_state(snapshot, client, tracked_keywords, targets):
    warnings = []
    task_priority = _ranking_task_priority()
    try:
        enriched, enrichment_cost = enrich_keyword_contexts([
            {
                "keyword": keyword.keyword,
                "location": keyword.location or client.location or "United States",
                "language": keyword.language or "en",
            }
            for keyword in tracked_keywords
        ])
    except Exception as exc:
        enriched, enrichment_cost = {}, 0.0
        warning = _error_diagnostic(exc)
        warnings.append(warning)
        _log_event(
            "ranking.enrichment_failed",
            snapshot_id=snapshot.id,
            client_id=client.id,
            diagnostic=warning,
        )

    checks = {}
    for competitor_id, domain in targets:
        for keyword in tracked_keywords:
            location_name = keyword.location or client.location or "United States"
            language_code = keyword.language or "en"
            details = enriched.get(
                ((keyword.keyword or "").strip().casefold(), location_name.strip().casefold(), language_code.strip().casefold()),
                {},
            )
            check_id = _ranking_check_id(snapshot.id, competitor_id, keyword.id)
            checks[check_id] = {
                "id": check_id,
                "competitor_id": competitor_id,
                "target": domain,
                "keyword": keyword.keyword,
                "location": location_name,
                "language": language_code,
                "device": keyword.device or "desktop",
                "search_volume": details.get("search_volume"),
                "priority": task_priority,
            }
    return {
        "version": 1,
        "transport": "dataforseo_standard_tasks",
        "priority": task_priority,
        "created_at": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "checks": checks,
        "task_ids": {},
        "completed": {},
        "warnings": warnings,
        "enrichment_cost": enrichment_cost,
        "ranking_cost": 0.0,
    }


def _mark_ranking_failed(state, check_id, diagnostic):
    state.setdefault("completed", {})[check_id] = {
        "status": "failed",
        "position": None,
        "url": None,
        "error": diagnostic,
    }


def _log_ranking_failure(snapshot, client, state, check_id, diagnostic):
    check = (state.get("checks") or {}).get(check_id) or {}
    _log_event(
        "ranking.provider_failure",
        snapshot_id=snapshot.id,
        client_id=client.id,
        ranking_check_id=check_id,
        target=check.get("target"),
        keyword=check.get("keyword"),
        location=check.get("location"),
        language=check.get("language"),
        device=check.get("device"),
        task_id=(state.get("task_ids") or {}).get(check_id),
        diagnostic=diagnostic,
    )


def _submit_pending_ranking_tasks(snapshot, client, state):
    task_ids = state.setdefault("task_ids", {})
    completed = state.setdefault("completed", {})
    checks = state.get("checks") or {}
    pending_submission = [
        check for check_id, check in checks.items()
        if check_id not in task_ids and check_id not in completed
    ]
    if not pending_submission:
        return []

    _log_event(
        "ranking.submission_started",
        snapshot_id=snapshot.id,
        client_id=client.id,
        checks=len(pending_submission),
        batches=(len(pending_submission) + 99) // 100,
        transport=state.get("transport"),
    )
    changed = []
    try:
        submission = queue_keyword_ranking_tasks(pending_submission)
    except Exception as exc:
        diagnostic = _error_diagnostic(exc)
        for check in pending_submission:
            _mark_ranking_failed(state, check["id"], diagnostic)
            changed.append(check["id"])
            _log_ranking_failure(snapshot, client, state, check["id"], diagnostic)
    else:
        for check_id, item in (submission.get("queued") or {}).items():
            task_ids[check_id] = item.get("task_id")
        for check_id, diagnostic in (submission.get("failed") or {}).items():
            _mark_ranking_failed(state, check_id, diagnostic)
            changed.append(check_id)
            _log_ranking_failure(snapshot, client, state, check_id, diagnostic)
        _log_event(
            "ranking.submission_finished",
            snapshot_id=snapshot.id,
            client_id=client.id,
            queued=len(submission.get("queued") or {}),
            failed=len(submission.get("failed") or {}),
            transport=state.get("transport"),
        )
    if changed:
        _persist_ranking_outcomes(snapshot, state, changed)
    else:
        _save_ranking_task_state(snapshot, state)
    if pending_submission:
        submitted_at = datetime.datetime.utcnow()
        state["submitted_at"] = submitted_at.isoformat(timespec="seconds") + "Z"
        state["foreground_wait_until"] = (
            submitted_at + datetime.timedelta(seconds=RANKING_TASK_FOREGROUND_WAIT_SECONDS)
        ).isoformat(timespec="seconds") + "Z"
        state["provider_wait_until"] = (
            submitted_at + datetime.timedelta(seconds=RANKING_TASK_MAX_WAIT_SECONDS)
        ).isoformat(timespec="seconds") + "Z"
        _save_ranking_task_state(snapshot, state)
    return changed


def _ranking_scope(client):
    """Return the project keywords and domains covered by one ranking audit."""
    tracked_keywords = [row for row in Keyword.query.filter_by(client_id=client.id).all() if row.keyword]
    targets = [(None, client.domain)] + [
        (competitor.id, competitor.domain)
        for competitor in Competitor.query.filter_by(client_id=client.id).all()
    ]
    return tracked_keywords, targets


def _start_ranking_tasks(snapshot, client, *, background=False):
    """Submit Standard ranking tasks once, allowing independent audit work to overlap.

    Submission is durable in ``Snapshot.notes``.  A later ranking stage (or a
    recovered worker) only waits for the already-created DataForSEO tasks and
    never pays to submit the same checks twice.
    """
    tracked_keywords, targets = _ranking_scope(client)
    total_checks = len(targets) * len(tracked_keywords)
    if not tracked_keywords:
        return None, total_checks, False, len(targets)

    state = _ranking_task_state(snapshot)
    resumed = state is not None
    if state is None:
        state = _prepare_ranking_task_state(snapshot, client, tracked_keywords, targets)
        if background:
            state["started_in_background"] = True
        _save_ranking_task_state(snapshot, state)

    _log_event(
        "ranking.submission_resumed" if resumed else "ranking.submission_prepared",
        snapshot_id=snapshot.id,
        client_id=client.id,
        targets=len(targets),
        checks=total_checks,
        priority="high" if state.get("priority") == 2 else "normal",
        background=background,
        transport=state.get("transport"),
    )
    _submit_pending_ranking_tasks(snapshot, client, state)
    counts = _ranking_counts(state)
    submitted = sum(1 for task_id in (state.get("task_ids") or {}).values() if task_id)
    processing_in_background = background or bool(state.get("started_in_background"))
    if submitted:
        ranking_state = "processing" if processing_in_background else "submitted"
        ranking_state_label = (
            "Processing in DataForSEO (background)"
            if processing_in_background else "Submitted to DataForSEO"
        )
    elif counts["failed_rows"]:
        ranking_state = "submission_failed"
        ranking_state_label = "Unable to submit ranking checks"
    else:
        ranking_state = "preparing"
        ranking_state_label = "Preparing DataForSEO tasks"
    # Do not overwrite the primary workflow phase here. A full audit can be
    # crawling while DataForSEO processes these tasks in parallel.
    _update_snapshot_progress(
        snapshot,
        ranking_completed=counts["rows"],
        ranking_pending=max(total_checks - counts["rows"], 0),
        ranking_total=total_checks,
        ranking_submitted=submitted,
        ranking_failed_rows=counts["failed_rows"],
        ranking_state=ranking_state,
        ranking_state_label=ranking_state_label,
    )
    return state, total_checks, resumed, len(targets)


def _ranking_pending_tasks(state):
    completed = state.setdefault("completed", {})
    return {
        check_id: task_id
        for check_id, task_id in (state.setdefault("task_ids", {})).items()
        if check_id not in completed and task_id
    }


def _parse_utc_timestamp(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo:
        parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return parsed


def _ranking_deadline(state, key, fallback_seconds):
    deadline = _parse_utc_timestamp(state.get(key))
    if deadline:
        return deadline
    submitted_at = _parse_utc_timestamp(state.get("submitted_at")) or datetime.datetime.utcnow()
    deadline = submitted_at + datetime.timedelta(seconds=fallback_seconds)
    state[key] = deadline.isoformat(timespec="seconds") + "Z"
    return deadline


def _collect_available_ranking_results(snapshot, client, state):
    """Collect one ready batch without blocking for provider-side processing."""
    pending = _ranking_pending_tasks(state)
    if not pending:
        return {"pending": 0, "changed": 0, "poll_failed": False}

    try:
        ready_ids = get_ready_keyword_ranking_task_ids()
    except Exception as exc:
        _log_event(
            "ranking.ready_poll_failed",
            snapshot_id=snapshot.id,
            client_id=client.id,
            pending=len(pending),
            diagnostic=_error_diagnostic(exc),
        )
        return {"pending": len(pending), "changed": 0, "poll_failed": True}

    ready_checks = [
        (check_id, task_id)
        for check_id, task_id in pending.items()
        if task_id in ready_ids
    ]
    if not ready_checks:
        return {"pending": len(pending), "changed": 0, "poll_failed": False}

    # Task result retrieval is network-bound. The bounded fan-out keeps result
    # collection fast without turning a provider-ready batch into extra delay.
    max_workers = min(RANKING_RESULT_WORKERS, len(ready_checks))
    _log_event(
        "ranking.result_collection_started",
        snapshot_id=snapshot.id,
        client_id=client.id,
        ready=len(ready_checks),
        workers=max_workers,
    )
    changed = []
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="dfs-ranking") as executor:
        futures = {
            executor.submit(
                get_keyword_ranking_task_result,
                task_id,
                ((state.get("checks") or {}).get(check_id) or {}).get("target"),
            ): check_id
            for check_id, task_id in ready_checks
        }
        for future in as_completed(futures):
            check_id = futures[future]
            try:
                ranking_data, single_cost = future.result()
            except DataForSEOTaskPending:
                # The provider ready-list may race the result endpoint. Leave
                # the task pending for a later, safe reconciliation pass.
                continue
            except Exception as exc:
                diagnostic = _error_diagnostic(exc)
                _mark_ranking_failed(state, check_id, diagnostic)
                _log_ranking_failure(snapshot, client, state, check_id, diagnostic)
            else:
                state["ranking_cost"] = float(state.get("ranking_cost") or 0.0) + float(single_cost or 0.0)
                state.setdefault("completed", {})[check_id] = {
                    "status": ranking_data.get("status") or "not_found",
                    "position": ranking_data.get("position"),
                    "url": ranking_data.get("url"),
                }
            changed.append(check_id)
    _log_event(
        "ranking.result_collection_finished",
        snapshot_id=snapshot.id,
        client_id=client.id,
        collected=len(changed),
        still_pending=len(ready_checks) - len(changed),
    )
    if changed:
        _persist_ranking_outcomes(snapshot, state, changed)
    return {
        "pending": len(_ranking_pending_tasks(state)),
        "changed": len(changed),
        "poll_failed": False,
    }


def _wait_for_ranking_tasks(snapshot, client, state, total_checks):
    """Use a short, user-facing wait budget before deferring provider work."""
    deadline = _ranking_deadline(
        state,
        "foreground_wait_until",
        RANKING_TASK_FOREGROUND_WAIT_SECONDS,
    )

    while True:
        collected = _collect_available_ranking_results(snapshot, client, state)
        pending = collected["pending"]
        if not pending:
            return "complete"

        if datetime.datetime.utcnow() >= deadline:
            state["deferred_at"] = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
            _save_ranking_task_state(snapshot, state)
            _update_ranking_progress(
                snapshot,
                state,
                total_checks,
                message=f"{total_checks - pending}/{total_checks} ranking checks saved; {pending} still processing in DataForSEO.",
                ranking_state="background_processing",
                ranking_state_label="Results still processing in DataForSEO",
            )
            return "deferred"

        _update_ranking_progress(
            snapshot,
            state,
            total_checks,
            message=(
                f"Waiting for {pending} DataForSEO ranking task(s)..."
                if not collected["poll_failed"]
                else f"Retrying the DataForSEO status check for {pending} ranking task(s)..."
            ),
        )
        remaining_seconds = max(0.0, (deadline - datetime.datetime.utcnow()).total_seconds())
        time.sleep(min(RANKING_TASK_POLL_SECONDS, remaining_seconds))


def _mark_pending_rankings_timed_out(snapshot, client, state):
    """Make a real provider timeout explicit only after the full wait budget."""
    timed_out = []
    for check_id, task_id in _ranking_pending_tasks(state).items():
        diagnostic = DataForSEOError(
            "Timed out waiting for the DataForSEO Standard ranking task.",
            endpoint="/v3/serp/google/organic/tasks_ready",
            task_id=task_id,
            retryable=True,
        ).diagnostic()
        _mark_ranking_failed(state, check_id, diagnostic)
        timed_out.append(check_id)
        _log_ranking_failure(snapshot, client, state, check_id, diagnostic)
    if timed_out:
        _persist_ranking_outcomes(snapshot, state, timed_out)
    state["timed_out"] = True
    return timed_out


def _pull_rankings(snapshot, client):
    state, total_checks, resumed, target_count = _start_ranking_tasks(snapshot, client)
    if state is None:
        _update_snapshot_progress(
            snapshot,
            phase="rankings",
            phase_label="Checking keyword rankings",
            ranking_completed=0,
            ranking_pending=0,
            ranking_total=0,
            ranking_failed_rows=0,
            ranking_submitted=0,
            ranking_state="not_configured",
            ranking_state_label="No tracked keywords configured",
            message="No tracked keywords are configured.",
        )
        return {
            "rows": 0,
            "ranked_rows": 0,
            "not_ranking_rows": 0,
            "failed_rows": 0,
            "targets": 0,
            "cost": 0.0,
            "errors": [],
            "transport": "dataforseo_standard_tasks",
        }

    _log_event(
        "ranking.stage_started",
        snapshot_id=snapshot.id,
        client_id=client.id,
        targets=target_count,
        checks=total_checks,
        resumed=resumed,
        started_in_background=bool(state.get("started_in_background")),
        priority="high" if state.get("priority") == 2 else "normal",
        transport=state.get("transport"),
    )
    _update_ranking_progress(
        snapshot,
        state,
        total_checks,
        message=(
            "Collecting ranking results that were submitted while the other audit stages ran..."
            if state.get("started_in_background") else
            "Resuming submitted DataForSEO ranking tasks..."
            if resumed else f"Queueing {total_checks} DataForSEO ranking checks..."
        ),
    )
    wait_outcome = _wait_for_ranking_tasks(snapshot, client, state, total_checks)

    counts = _ranking_counts(state)
    deferred_rows = len(_ranking_pending_tasks(state))
    if wait_outcome == "deferred" and deferred_rows:
        _schedule_ranking_reconciliation(snapshot, client)
        final_ranking_state = "background_processing"
        final_ranking_label = "Results still processing in DataForSEO"
    elif state.get("timed_out"):
        final_ranking_state = "timed_out"
        final_ranking_label = "Ranking result wait timed out"
    elif counts["failed_rows"] or state.get("warnings"):
        final_ranking_state = "complete_with_issues"
        final_ranking_label = "Ranking results collected with issues"
    else:
        final_ranking_state = "complete"
        final_ranking_label = "Ranking results collected"
    _update_ranking_progress(
        snapshot,
        state,
        total_checks,
        ranking_state=final_ranking_state,
        ranking_state_label=final_ranking_label,
        message=(
            f"{counts['rows']}/{total_checks} ranking checks collected."
            if final_ranking_state == "complete"
            else f"{counts['rows']}/{total_checks} ranking checks saved; {deferred_rows} are still processing in DataForSEO."
            if final_ranking_state == "background_processing"
            else f"{counts['rows']}/{total_checks} ranking checks saved with issues."
        ),
    )
    errors = _ranking_error_samples(state)
    if deferred_rows:
        errors = [
            f"{deferred_rows} DataForSEO ranking task(s) are still processing and will be collected in the background."
        ] + errors
    total_cost = float(state.get("enrichment_cost") or 0.0) + float(state.get("ranking_cost") or 0.0)
    _log_event(
        "ranking.stage_finished",
        snapshot_id=snapshot.id,
        client_id=client.id,
        targets=target_count,
        transport=state.get("transport"),
        cost=round(total_cost, 6),
        deferred_rows=deferred_rows,
        error_count=counts["failed_rows"] + len(state.get("warnings") or []),
        **counts,
    )
    if not deferred_rows:
        _clear_ranking_task_state(snapshot)
    return {
        **counts,
        "targets": target_count,
        "cost": total_cost,
        "errors": errors,
        "error_count": counts["failed_rows"] + len(state.get("warnings") or []),
        "deferred": bool(deferred_rows),
        "deferred_rows": deferred_rows,
        "transport": state.get("transport"),
    }


def _ranking_target_count(state):
    targets = {
        check.get("competitor_id")
        for check in (state.get("checks") or {}).values()
        if isinstance(check, dict)
    }
    return len(targets)


def _ranking_result_payload(state, total_checks, *, deferred=False):
    counts = _ranking_counts(state)
    deferred_rows = len(_ranking_pending_tasks(state)) if deferred else 0
    errors = _ranking_error_samples(state)
    if deferred_rows:
        errors = [
            f"{deferred_rows} DataForSEO ranking task(s) are still processing and will be collected in the background."
        ] + errors
    return {
        **counts,
        "targets": _ranking_target_count(state),
        "cost": float(state.get("enrichment_cost") or 0.0) + float(state.get("ranking_cost") or 0.0),
        "errors": errors,
        "error_count": counts["failed_rows"] + len(state.get("warnings") or []),
        "deferred": bool(deferred_rows),
        "deferred_rows": deferred_rows,
        "transport": state.get("transport"),
    }


def _schedule_ranking_reconciliation(snapshot, client):
    """Upsert low-priority follow-up work for still-processing provider tasks."""
    job = RankingReconciliationJob.query.filter_by(snapshot_id=snapshot.id).first()
    if job and job.status == "running":
        return job
    if not job:
        job = RankingReconciliationJob(snapshot_id=snapshot.id, client_id=client.id)
        db.session.add(job)
    job.status = "pending"
    job.next_poll_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=RANKING_RECONCILIATION_POLL_SECONDS)
    job.completed_at = None
    job.last_error = None
    db.session.commit()
    _log_event(
        "ranking.reconciliation_scheduled",
        snapshot_id=snapshot.id,
        client_id=client.id,
        next_poll_at=job.next_poll_at.isoformat(timespec="seconds") + "Z",
    )
    return job


def recover_stale_ranking_reconciliation_jobs():
    """Make abandoned reconciliation work eligible after a worker restart."""
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(minutes=RANKING_RECONCILIATION_STALE_MINUTES)
    jobs = RankingReconciliationJob.query.filter(
        RankingReconciliationJob.status == "running",
        RankingReconciliationJob.updated_at <= cutoff,
    ).all()
    for job in jobs:
        job.status = "pending"
        job.next_poll_at = datetime.datetime.utcnow()
        job.last_error = "Recovered after the ranking reconciliation worker stopped unexpectedly."
    if jobs:
        db.session.commit()
    return len(jobs)


def _claim_due_ranking_reconciliation_job():
    now = datetime.datetime.utcnow()
    try:
        job = db.session.execute(
            select(RankingReconciliationJob)
            .where(
                RankingReconciliationJob.status == "pending",
                (RankingReconciliationJob.next_poll_at.is_(None)) | (RankingReconciliationJob.next_poll_at <= now),
            )
            .order_by(RankingReconciliationJob.next_poll_at, RankingReconciliationJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).scalar_one_or_none()
        if not job:
            db.session.rollback()
            return None
        job.status = "running"
        job.attempt_count += 1
        job.last_error = None
        db.session.commit()
        return job.id
    except Exception:
        db.session.rollback()
        raise


def _reschedule_ranking_reconciliation(job, *, error=None):
    job.status = "pending"
    job.next_poll_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=RANKING_RECONCILIATION_POLL_SECONDS)
    job.last_error = str(error)[:1000] if error else None
    db.session.commit()


def _finish_ranking_reconciliation_job(job, status, *, error=None):
    job.status = status
    job.next_poll_at = None
    job.last_error = str(error)[:1000] if error else None
    job.completed_at = datetime.datetime.utcnow()
    db.session.commit()


def _update_ranking_stage_summary(snapshot, result, *, status):
    """Refresh just the ranking stage while retaining all other audit stages."""
    notes = load_notes(snapshot.notes)
    stage_results = notes.get("stage_results") if isinstance(notes.get("stage_results"), list) else []
    matching_stage = next(
        (item for item in stage_results if isinstance(item, dict) and item.get("name") == "rankings"),
        None,
    )
    error = (result.get("errors") or [None])[0] if status == "partial" else None
    if matching_stage is None:
        matching_stage = {"name": "rankings", "optional": True, "duration_seconds": 0}
        stage_results.append(matching_stage)
    matching_stage["status"] = status
    matching_stage["error"] = error
    matching_stage.setdefault("optional", True)
    matching_stage.setdefault("duration_seconds", 0)
    notes["stage_results"] = stage_results
    notes["rankings"] = result
    snapshot.notes = json.dumps(notes)
    db.session.commit()
    return stage_results


def _finalize_reconciled_rankings(snapshot, state):
    """Publish the terminal ranking result without re-running the audit."""
    total_checks = len(state.get("checks") or {})
    result = _ranking_result_payload(state, total_checks)
    ranking_status = "partial" if result["failed_rows"] or state.get("warnings") else "complete"
    stage_results = _update_ranking_stage_summary(snapshot, result, status=ranking_status)
    final_status = final_snapshot_status(stage_results) if stage_results else snapshot.status
    snapshot.status = final_status
    db.session.commit()
    _clear_ranking_task_state(snapshot)
    counts = _ranking_counts(state)
    final_ranking_state = (
        "timed_out" if state.get("timed_out")
        else "complete_with_issues" if ranking_status == "partial"
        else "complete"
    )
    final_ranking_label = (
        "Ranking result wait timed out" if final_ranking_state == "timed_out"
        else "Ranking results collected with issues" if ranking_status == "partial"
        else "Ranking results collected"
    )
    _update_snapshot_progress(
        snapshot,
        phase=final_status,
        phase_label=(
            "Analysis complete" if final_status == "complete"
            else "Analysis completed with issues" if final_status == "partial"
            else "Analysis failed"
        ),
        ranking_completed=counts["rows"],
        ranking_pending=0,
        ranking_total=total_checks,
        ranked_rows=counts["ranked_rows"],
        not_ranking_rows=counts["not_ranking_rows"],
        ranking_failed_rows=counts["failed_rows"],
        ranking_submitted=sum(1 for task_id in (state.get("task_ids") or {}).values() if task_id),
        ranking_state=final_ranking_state,
        ranking_state_label=final_ranking_label,
        workflow_current_stage="complete",
        workflow_current_stage_label="All audit stages finished",
        message=(
            "All analysis stages completed."
            if final_status == "complete"
            else "Analysis completed, but one or more stages reported an issue."
        ),
    )
    run = load_notes(snapshot.notes).get("run") or {}
    if run.get("type") == "full_audit" and final_status in {"complete", "partial"}:
        try:
            persist_health_score(snapshot)
        except Exception as exc:
            db.session.rollback()
            _log_event(
                "ranking.reconciliation_health_refresh_failed",
                snapshot_id=snapshot.id,
                client_id=snapshot.client_id,
                diagnostic=_error_diagnostic(exc),
            )
    return result, final_status


def reconcile_due_ranking_tasks():
    """Collect one due ranking batch when no primary audit is waiting.

    The worker intentionally handles at most one snapshot per idle cycle. This
    keeps new audits and Copilot requests ahead of low-priority provider polling.
    """
    reconciliation_job_id = _claim_due_ranking_reconciliation_job()
    if not reconciliation_job_id:
        return 0
    job = db.session.get(RankingReconciliationJob, reconciliation_job_id)
    if not job:
        return 0

    snapshot = db.session.get(Snapshot, job.snapshot_id)
    client = db.session.get(Client, job.client_id)
    if not snapshot or not client:
        _finish_ranking_reconciliation_job(job, "cancelled", error="The project or snapshot no longer exists.")
        return 1

    state = _ranking_task_state(snapshot)
    if state is None:
        _finish_ranking_reconciliation_job(job, "cancelled", error="No pending ranking task state remains on this snapshot.")
        return 1

    total_checks = len(state.get("checks") or {})
    pending_before = len(_ranking_pending_tasks(state))
    _log_event(
        "ranking.reconciliation_started",
        snapshot_id=snapshot.id,
        client_id=client.id,
        attempt=job.attempt_count,
        pending=pending_before,
        total=total_checks,
    )
    try:
        collected = _collect_available_ranking_results(snapshot, client, state)
        pending = collected["pending"]
        if not pending:
            result, final_status = _finalize_reconciled_rankings(snapshot, state)
            _finish_ranking_reconciliation_job(job, "completed")
            _log_event(
                "ranking.reconciliation_finished",
                snapshot_id=snapshot.id,
                client_id=client.id,
                resolution="complete",
                snapshot_status=final_status,
                **_ranking_counts(state),
            )
            return 1

        provider_deadline = _ranking_deadline(
            state,
            "provider_wait_until",
            RANKING_TASK_MAX_WAIT_SECONDS,
        )
        if datetime.datetime.utcnow() >= provider_deadline:
            _mark_pending_rankings_timed_out(snapshot, client, state)
            result, final_status = _finalize_reconciled_rankings(snapshot, state)
            _finish_ranking_reconciliation_job(job, "expired", error="DataForSEO did not finish before the configured provider wait limit.")
            _log_event(
                "ranking.reconciliation_finished",
                snapshot_id=snapshot.id,
                client_id=client.id,
                resolution="timed_out",
                snapshot_status=final_status,
                **_ranking_counts(state),
            )
            return 1

        result = _ranking_result_payload(state, total_checks, deferred=True)
        _update_ranking_stage_summary(snapshot, result, status="partial")
        _update_ranking_progress(
            snapshot,
            state,
            total_checks,
            message=f"{total_checks - pending}/{total_checks} ranking checks saved; {pending} still processing in DataForSEO.",
            ranking_state="background_processing",
            ranking_state_label="Results still processing in DataForSEO",
        )
        _reschedule_ranking_reconciliation(
            job,
            error="DataForSEO ready-task poll was unavailable." if collected["poll_failed"] else None,
        )
        _log_event(
            "ranking.reconciliation_deferred",
            snapshot_id=snapshot.id,
            client_id=client.id,
            pending=pending,
            total=total_checks,
            changed=collected["changed"],
            poll_failed=collected["poll_failed"],
        )
    except Exception as exc:
        db.session.rollback()
        _reschedule_ranking_reconciliation(job, error=exc)
        _log_event(
            "ranking.reconciliation_failed",
            snapshot_id=job.snapshot_id,
            client_id=job.client_id,
            diagnostic=_error_diagnostic(exc),
        )
    return 1


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
    traffic_markets = normalize_competitor_traffic_locations(
        client.competitor_traffic_locations,
        client.location,
    )
    for competitor in competitors:
        try:
            insight_data, cost = get_competitor_insights(competitor.domain, location_name=client.location or "United States")
            competitor_errors = [
                f"{dataset}: {message}"
                for dataset, message in (insight_data.get("dataset_errors") or {}).items()
            ]
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
            db.session.add(CompetitorCountryTraffic(
                snapshot_id=snapshot.id,
                competitor_id=competitor.id,
                location=traffic_markets[0],
                estimated_organic_traffic=summary.get("estimated_organic_traffic"),
                organic_keyword_count=summary.get("organic_keyword_count"),
                top_10_keyword_count=sum(summary.get(key, 0) or 0 for key in ("position_1", "position_2_3", "position_4_10")),
                estimated_traffic_cost=summary.get("estimated_paid_traffic_cost"),
            ))
            for market in traffic_markets[1:]:
                try:
                    country_traffic, country_cost = get_competitor_country_traffic(
                        competitor.domain,
                        location_name=market,
                    )
                    db.session.add(CompetitorCountryTraffic(
                        snapshot_id=snapshot.id,
                        competitor_id=competitor.id,
                        location=market,
                        estimated_organic_traffic=country_traffic.get("estimated_organic_traffic"),
                        organic_keyword_count=country_traffic.get("organic_keyword_count"),
                        top_10_keyword_count=country_traffic.get("top_10_keyword_count"),
                        estimated_traffic_cost=country_traffic.get("estimated_traffic_cost"),
                    ))
                    total_cost += country_cost
                except Exception as exc:
                    message = f"country traffic ({market}): {exc}"
                    competitor_errors.append(message)
                    db.session.add(CompetitorCountryTraffic(
                        snapshot_id=snapshot.id,
                        competitor_id=competitor.id,
                        location=market,
                        status="failed",
                        error_message=str(exc)[:1000],
                    ))
            db.session.add(CompetitorInsight(
                client_id=client.id,
                competitor_id=competitor.id,
                snapshot_id=snapshot.id,
                target_domain=insight_data.get("target") or competitor.domain,
                status="partial" if competitor_errors else "complete",
                summary=summary,
                ranked_keywords=insight_data.get("ranked_keywords") or [],
                top_pages=insight_data.get("top_pages") or [],
                error_message="; ".join(competitor_errors)[:1000] or None,
            ))
            count += 1
            total_cost += cost
            if competitor_errors:
                errors.extend(f"{competitor.domain} / {message}" for message in competitor_errors)
                _log(f"  competitor insights partial for {competitor.domain}: {'; '.join(competitor_errors)}")
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
    return {
        "rows": count,
        "targets": len(competitors),
        "traffic_markets": len(traffic_markets),
        "cost": total_cost,
        "errors": errors,
    }


def _generate_report(snapshot, client):
    from services import analyze

    brief = analyze.build_brief_from_models(client.id, snapshot.id)
    ai_settings = get_effective_ai_settings(client.id)
    report = analyze.generate(
        brief,
        model_name=ai_settings["model_name"],
        system_prompt=ai_settings["system_prompt"],
    )
    context = build_report_context(client, snapshot, brief, ai_settings)
    artifact = write_markdown_report(REPORTS_DIR, context, report)
    return artifact.markdown_path, ai_settings


def _run_snapshot_job(app, snapshot_id, client_id):
    with app.app_context():
        snapshot = db.session.get(Snapshot, snapshot_id)
        client = db.session.get(Client, client_id)
        if not snapshot or not client:
            return

        snapshot.status = "running"
        db.session.commit()
        snapshot_notes = load_notes(snapshot.notes)
        run_details = snapshot_notes.get("run") or {}
        crawl_scope = run_details.get("crawl_scope")
        run_type = run_details.get("type", "full_audit")
        selected_stages = normalize_selected_stages(run_details.get("selected_stages"))
        ranking_requested = run_type == "rank_check" or "rankings" in selected_stages
        keyword_count = Keyword.query.filter(
            Keyword.client_id == client_id,
            Keyword.keyword.isnot(None),
        ).count()
        competitor_count = Competitor.query.filter_by(client_id=client_id).count()
        initial_ranking_total = keyword_count * (competitor_count + 1) if ranking_requested else 0
        stages = build_stage_plan(
            run_type,
            crawl=lambda: _pull_crawl(snapshot, client, crawl_scope),
            ga4=lambda: _pull_ga4(snapshot, client),
            gsc=lambda: _pull_gsc(snapshot, client),
            rankings=lambda: _pull_rankings(snapshot, client),
            backlinks=lambda: _pull_backlinks(snapshot, client),
            competitor_insights=lambda: _pull_competitor_insights(snapshot, client),
            selected_stages=selected_stages,
        )
        workflow_total = len(stages) + (0 if run_type == "rank_check" else 1)
        _update_snapshot_progress(
            snapshot,
            phase="rankings" if run_type == "rank_check" else "starting",
            phase_label="Starting ranking check" if run_type == "rank_check" else "Starting analysis",
            crawled_urls=0,
            pending_urls=0,
            ranking_completed=0,
            ranking_pending=initial_ranking_total,
            ranking_total=initial_ranking_total,
            ranking_submitted=0,
            ranking_state=(
                "preparing" if ranking_requested and initial_ranking_total
                else "not_configured" if ranking_requested
                else "not_selected"
            ),
            ranking_state_label=(
                "Preparing DataForSEO tasks" if ranking_requested and initial_ranking_total
                else "No tracked keywords configured" if ranking_requested
                else "Not selected for this audit"
            ),
            workflow_total_stages=workflow_total,
            workflow_finished_stages=0,
            workflow_current_stage="preparing",
            workflow_current_stage_label="Preparing audit",
            workflow_current_stage_position=0,
            message=(
                "Ranking checks are starting..."
                if run_type == "rank_check"
                else "Analysis is starting; ranking checks will be submitted in parallel with the audit."
                if initial_ranking_total
                else "Analysis is starting..."
            ),
        )
        results = {}
        try:
            # Crawl and provider-side SERP processing are independent.  Submit
            # the ranking tasks first, then let DataForSEO work on them while
            # LibreCrawl/Google/backlink stages run.  The ranking stage later
            # only collects the durable task results.
            if run_type != "rank_check" and "rankings" in selected_stages:
                _start_ranking_tasks(snapshot, client, background=True)
            stage_results = []
            for stage_index, spec in enumerate(stages, start=1):
                label = spec.name
                _update_snapshot_progress(
                    snapshot,
                    phase=label,
                    phase_label=_progress_stage_label(label),
                    workflow_current_stage=label,
                    workflow_current_stage_label=_progress_stage_label(label),
                    workflow_current_stage_position=stage_index,
                    workflow_finished_stages=stage_index - 1,
                    workflow_total_stages=workflow_total,
                    message=_progress_stage_message(label),
                )
                execution = execute_stage(spec)
                stage_results.append(execution)
                try:
                    if execution["status"] == "failed":
                        raise RuntimeError(execution["error"])
                    job_result = execution["value"]
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
                    execution["status"] = "failed"
                    execution["error"] = str(exc)
                    results[label] = f"FAILED: {exc}"
                    _log(f"  {label} FAILED: {exc}")
                    _update_snapshot_notes(snapshot, results, status="partial")
                finally:
                    _update_snapshot_progress(
                        snapshot,
                        workflow_current_stage=label,
                        workflow_current_stage_label=_progress_stage_label(label),
                        workflow_current_stage_position=stage_index,
                        workflow_finished_stages=stage_index,
                        workflow_total_stages=workflow_total,
                    )

            snapshot_notes = load_notes(snapshot.notes)
            snapshot_notes["stage_results"] = stage_summary(stage_results)
            snapshot.notes = json.dumps(snapshot_notes)
            db.session.commit()

            if run_type == "rank_check":
                results["report"] = "Skipped for ranking-only check"
            else:
                _update_snapshot_progress(
                    snapshot,
                    phase="report",
                    phase_label="Generating report",
                    workflow_current_stage="report",
                    workflow_current_stage_label=_progress_stage_label("report"),
                    workflow_current_stage_position=workflow_total,
                    workflow_finished_stages=len(stages),
                    workflow_total_stages=workflow_total,
                    message="Preparing the SEO report...",
                )
                report_spec = StageSpec(
                    "report",
                    lambda: _generate_report(snapshot, client),
                    # The stored snapshot is still valuable when a generative
                    # provider is misconfigured or temporarily unavailable.
                    # Treat report generation as a recoverable enhancement so
                    # its failure cannot re-run crawl/DFS/backlink collection.
                    optional=True,
                )
                report_execution = execute_stage(report_spec)
                stage_results.append(report_execution)
                if report_execution["status"] == "failed":
                    results["report"] = f"FAILED: {report_execution['error']}"
                    _log_event(
                        "report.generation_failed",
                        snapshot_id=snapshot.id,
                        client_id=client.id,
                        diagnostic=_error_diagnostic(
                            report_execution.get("exception") or RuntimeError(report_execution["error"])
                        ),
                    )
                else:
                    report_path, ai_settings = report_execution["value"]
                    results["report"] = os.path.basename(report_path)
                    results["ai_model"] = ai_settings["model_name"]
                    results["ai_settings_source"] = ai_settings["source"]
                _update_snapshot_progress(
                    snapshot,
                    workflow_current_stage="report",
                    workflow_current_stage_label=_progress_stage_label("report"),
                    workflow_current_stage_position=workflow_total,
                    workflow_finished_stages=workflow_total,
                    workflow_total_stages=workflow_total,
                )

            final_status = final_snapshot_status(stage_results)
            ranking_result = results.get("rankings") if isinstance(results.get("rankings"), dict) else {}
            deferred_ranking_rows = max(0, int(ranking_result.get("deferred_rows") or 0))
            _update_snapshot_progress(
                snapshot,
                phase=final_status,
                phase_label=(
                    "Analysis complete" if final_status == "complete"
                    else "Analysis failed" if final_status == "failed"
                    else "Analysis completed with issues"
                ),
                pending_urls=0,
                ranking_pending=deferred_ranking_rows,
                workflow_current_stage="complete",
                workflow_current_stage_label="All audit stages finished",
                workflow_current_stage_position=workflow_total,
                workflow_finished_stages=workflow_total,
                workflow_total_stages=workflow_total,
                message=(
                    "All analysis stages completed."
                    if final_status == "complete"
                    else "Analysis failed and will be retried when eligible."
                    if final_status == "failed"
                    else f"Analysis completed; {deferred_ranking_rows} ranking result(s) are still being collected in the background."
                    if deferred_ranking_rows
                    else "Analysis completed, but one or more stages reported an issue."
                ),
            )
            snapshot_notes = load_notes(snapshot.notes)
            snapshot_notes["stage_results"] = stage_summary(stage_results)
            snapshot.notes = json.dumps(snapshot_notes)
            db.session.commit()
            _update_snapshot_notes(snapshot, results, status=final_status)
            # Health is a stored interpretation of a completed crawl, never a
            # requirement for the audit itself. Keep it isolated so a scoring
            # regression cannot turn an otherwise usable audit into a failure.
            if run_type == "full_audit" and final_status in {"complete", "partial"}:
                try:
                    health_record = persist_health_score(snapshot)
                    if health_record:
                        _log(f"  health score v2: {health_record.score} (confidence {health_record.confidence}%)")
                except Exception as exc:
                    db.session.rollback()
                    _log(f"  health score skipped: {exc}")
        except Exception as exc:
            db.session.rollback()
            results["job"] = f"FAILED: {exc}"
            _log(f"  snapshot job FAILED: {exc}")
            _update_snapshot_progress(
                snapshot,
                phase="failed",
                phase_label="Analysis failed",
                workflow_current_stage="failed",
                workflow_current_stage_label="Audit stopped",
                message=str(exc),
            )
            _update_snapshot_notes(snapshot, results, status="failed")


def enqueue_snapshot_job(app, client_id, crawl_scope=None, run_type="full_audit", selected_stages=None):
    """Queue a durable job. ``app`` remains for backwards-compatible callers."""
    from services.audit_queue import queue_snapshot_job

    client = db.session.get(Client, client_id)
    if not client:
        raise ValueError("Project not found.")
    crawl_scope = crawl_scope or build_crawl_scope(client)
    snapshot, _job = queue_snapshot_job(
        client,
        crawl_scope=crawl_scope,
        run_type=run_type,
        selected_stages=selected_stages,
    )
    return snapshot
