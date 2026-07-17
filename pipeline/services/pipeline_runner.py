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

from app.models import Client, CrawlIssue, Ga4Metric, GscMetric, Keyword, Ranking, Snapshot, db
from services.dataforseo import enrich_keywords

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY_PATH = os.path.join(os.path.dirname(BASE_DIR), "credentials", "google-service-account.json")
CRAWLER_URL = os.environ.get("LIBRECRAWL_URL", "http://127.0.0.1:5080")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
CRAWLER_REQUEST_TIMEOUT = int(os.environ.get("LIBRECRAWL_REQUEST_TIMEOUT", "120"))
CRAWLER_POLL_INTERVAL = int(os.environ.get("LIBRECRAWL_POLL_INTERVAL", "5"))
CRAWLER_MAX_POLLS = int(os.environ.get("LIBRECRAWL_MAX_POLLS", "60"))


def _log(message):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {message}")


def _update_snapshot_notes(snapshot, payload):
    snapshot.notes = json.dumps(payload)
    db.session.commit()


def _pull_crawl(snapshot, client):
    session = requests.Session()
    login_response = session.post(
        f"{CRAWLER_URL}/api/guest-login",
        json={},
        timeout=CRAWLER_REQUEST_TIMEOUT,
    )
    login_response.raise_for_status()

    target_url = f"https://{client.domain}"
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
        raise RuntimeError(f"crawl did not complete within {CRAWLER_MAX_POLLS * CRAWLER_POLL_INTERVAL} seconds")

    issues = (crawl_state or {}).get("issues", [])
    for item in issues:
        db.session.add(
            CrawlIssue(
                snapshot_id=snapshot.id,
                url=item.get("url"),
                issue=item.get("issue"),
                issue_type=item.get("type"),
                category=item.get("category"),
                details=item.get("details"),
            )
        )
    db.session.commit()
    return len(issues)


def _pull_ga4(snapshot, client):
    if not client.ga4_property_id:
        return 0

    creds = service_account.Credentials.from_service_account_file(KEY_PATH)
    analytics = BetaAnalyticsDataClient(credentials=creds)
    start = (datetime.date.today() - datetime.timedelta(days=28)).isoformat()
    end = datetime.date.today().isoformat()
    request = RunReportRequest(
        property=f"properties/{client.ga4_property_id}",
        date_ranges=[DateRange(start_date=start, end_date=end)],
        metrics=[Metric(name="sessions"), Metric(name="totalUsers"), Metric(name="screenPageViews")],
        dimensions=[Dimension(name="sessionDefaultChannelGroup")],
    )
    response = analytics.run_report(request)

    count = 0
    for row in response.rows:
        channel = row.dimension_values[0].value
        for idx, metric_name in enumerate(["sessions", "totalUsers", "screenPageViews"]):
            db.session.add(
                Ga4Metric(
                    snapshot_id=snapshot.id,
                    metric_name=metric_name,
                    metric_value=float(row.metric_values[idx].value),
                    dimension=channel,
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
        KEY_PATH,
        scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
    )
    service = build("searchconsole", "v1", credentials=creds)
    end = datetime.date.today() - datetime.timedelta(days=3)
    start = end - datetime.timedelta(days=28)
    response = service.searchanalytics().query(
        siteUrl=client.gsc_site_url,
        body={
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": ["query"],
            "rowLimit": 100,
        },
    ).execute()

    rows = response.get("rows", [])
    for row in rows:
        db.session.add(
            GscMetric(
                snapshot_id=snapshot.id,
                query=row["keys"][0],
                page=None,
                clicks=row.get("clicks"),
                impressions=row.get("impressions"),
                ctr=row.get("ctr"),
                position=row.get("position"),
                period_start=start.isoformat(),
                period_end=end.isoformat(),
            )
        )
    db.session.commit()
    return len(rows)


def _pull_rankings(snapshot, client):
    tracked_keywords = Keyword.query.filter_by(client_id=client.id).all()
    keywords = [row.keyword for row in tracked_keywords if row.keyword]
    if not keywords:
        keywords = [
            row.query
            for row in db.session.query(GscMetric).filter_by(snapshot_id=snapshot.id).all()
            if row.query
        ]
    if not keywords:
        return 0

    enriched, cost = enrich_keywords(keywords, location_name=client.location or "United States")
    count = 0
    for keyword in tracked_keywords:
        details = enriched.get(keyword.keyword, {})
        db.session.add(
            Ranking(
                snapshot_id=snapshot.id,
                keyword=keyword.keyword,
                position=None,
                search_volume=details.get("search_volume"),
                url=None,
                location=keyword.location or client.location,
                device=keyword.device or "desktop",
            )
        )
        count += 1
    db.session.commit()
    _log(f"  rankings cost: ${cost}")
    return count


def _generate_report(snapshot, client):
    from services import analyze

    brief = analyze.build_brief_from_models(client.id, snapshot.id)
    report = analyze.generate(brief)
    os.makedirs(REPORTS_DIR, exist_ok=True)
    filename = os.path.join(REPORTS_DIR, f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}.md")
    with open(filename, "w", encoding="utf-8") as handle:
        handle.write(
            f"# SEO Report - {client.name}\n"
            f"_Snapshot {snapshot.id} · {datetime.datetime.now():%Y-%m-%d}_\n\n{report}\n"
        )
    return filename


def _run_snapshot_job(app, snapshot_id, client_id):
    with app.app_context():
        snapshot = Snapshot.query.get(snapshot_id)
        client = Client.query.get(client_id)
        if not snapshot or not client:
            return

        snapshot.status = "running"
        db.session.commit()
        results = {}

        for label, job in [
            ("crawl", lambda: _pull_crawl(snapshot, client)),
            ("ga4", lambda: _pull_ga4(snapshot, client)),
            ("gsc", lambda: _pull_gsc(snapshot, client)),
            ("rankings", lambda: _pull_rankings(snapshot, client)),
        ]:
            try:
                results[label] = job()
                _log(f"  {label}: {results[label]} rows")
                _update_snapshot_notes(snapshot, results)
            except Exception as exc:
                db.session.rollback()
                results[label] = f"FAILED: {exc}"
                _log(f"  {label} FAILED: {exc}")
                _update_snapshot_notes(snapshot, results)

        try:
            report_path = _generate_report(snapshot, client)
            results["report"] = os.path.basename(report_path)
        except Exception as exc:
            results["report"] = f"FAILED: {exc}"
            _log(f"  report FAILED: {exc}")

        failures = [value for value in results.values() if str(value).startswith("FAILED")]
        snapshot.status = "complete" if not failures else "partial"
        _update_snapshot_notes(snapshot, results)


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
