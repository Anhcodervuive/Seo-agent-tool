import csv
import io
import json
import os
from datetime import date

from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from markupsafe import Markup
import markdown

from app.models import (
    BacklinkHistory,
    Client,
    CrawlIssue,
    CrawlPage,
    CrawlPageImage,
    CrawlPageLink,
    Ga4Metric,
    GscMetric,
    Keyword,
    Ranking,
    Snapshot,
    db,
)
from services.ai_settings import get_effective_ai_settings
from services.health import compute_health_score
from services.make_pdf import markdown_file_to_pdf_bytes
from services.pipeline_runner import enqueue_snapshot_job

main_bp = Blueprint('main', __name__)


ISSUE_TYPE_PRIORITY = {
    "error": 0,
    "critical": 0,
    "warning": 1,
    "warn": 1,
    "info": 2,
    "notice": 2,
}

GA4_DIMENSION_LABELS = {
    "channel": "Channel",
    "page_path": "Page Path",
    "country": "Country",
    "device": "Device",
}

GA4_SORT_LABELS = {
    "totalUsers": "Total Users",
    "sessions": "Sessions",
    "averageSessionDuration": "Average Session Duration",
    "eventCount": "Event Count",
    "engagementRate": "Engagement Rate",
}

GSC_VIEW_LABELS = {
    "queries": "Queries",
    "urls": "URLs",
    "country": "Country",
    "device": "Device",
}

GSC_SORT_LABELS = {
    "clicks": "Clicks",
    "impressions": "Impressions",
    "ctr": "CTR",
    "position": "Average Position",
}

LINK_SORT_LABELS = {
    "unique_internal_links": "Unique Internal Links",
    "total_internal_links": "Total Internal Links",
}


def _ranking_lookup_key(keyword_text, location, device):
    return (
        (keyword_text or "").strip().lower(),
        (location or "").strip().lower(),
        (device or "").strip().lower(),
    )


def _build_keyword_rankings(keywords, current_snapshot, previous_snapshot):
    if not current_snapshot:
        return {}

    current_rows = Ranking.query.filter_by(snapshot_id=current_snapshot.id).all()
    previous_rows = Ranking.query.filter_by(snapshot_id=previous_snapshot.id).all() if previous_snapshot else []

    current_by_keyword = {
        _ranking_lookup_key(row.keyword, row.location, row.device): row for row in current_rows
    }
    previous_by_keyword = {
        _ranking_lookup_key(row.keyword, row.location, row.device): row for row in previous_rows
    }

    keyword_rankings = {}
    for keyword in keywords:
        ranking_key = _ranking_lookup_key(keyword.keyword, keyword.location, keyword.device)
        latest = current_by_keyword.get(ranking_key)
        previous = previous_by_keyword.get(ranking_key)

        current_position = latest.position if latest else None
        previous_position = previous.position if previous else None

        movement = None
        movement_label = "No data"
        movement_tone = "neutral"

        if current_position is not None and previous_position is not None:
            movement = previous_position - current_position
            if movement > 0:
                movement_label = f"Up {movement}"
                movement_tone = "up"
            elif movement < 0:
                movement_label = f"Down {abs(movement)}"
                movement_tone = "down"
            else:
                movement_label = "No change"
        elif current_position is not None:
            movement_label = "New"
            movement_tone = "new"
        elif previous_position is not None:
            movement_label = "Lost"
            movement_tone = "lost"

        keyword_rankings[keyword.id] = {
            "latest": latest,
            "previous": previous,
            "current_position": current_position,
            "previous_position": previous_position,
            "movement": movement,
            "movement_label": movement_label,
            "movement_tone": movement_tone,
        }

    return keyword_rankings


def _compute_keyword_page_score(ranking_row, crawl_pages_by_url):
    if not ranking_row or not ranking_row.url:
        return None

    page = crawl_pages_by_url.get((ranking_row.url or "").strip())
    if not page:
        return None

    score = 100

    if page.status_code and page.status_code >= 400:
        score -= 45
    elif page.status_code and page.status_code >= 300:
        score -= 15

    if not _clean_text(page.title):
        score -= 12
    elif len(_clean_text(page.title)) > 60:
        score -= 4

    if not _clean_text(page.meta_description):
        score -= 10
    elif len(_clean_text(page.meta_description)) > 160:
        score -= 4

    if not _clean_text(page.h1):
        score -= 8

    if not _clean_text(page.canonical_url):
        score -= 8
    elif _clean_text(page.canonical_url) != _clean_text(page.url):
        score -= 6

    if page.word_count is None:
        score -= 6
    elif page.word_count < 200:
        score -= 16
    elif page.word_count < 500:
        score -= 8

    if page.internal_links is not None and page.internal_links <= 1:
        score -= 5

    return max(0, min(100, int(round(score))))


def _group_crawl_issues(crawl_issues):
    grouped = {}
    for row in crawl_issues:
        issue_name = (row.issue or "Unknown issue").strip() or "Unknown issue"
        issue_type = (row.issue_type or "info").strip().lower() or "info"
        bucket = grouped.setdefault(
            issue_name,
            {
                "issue": issue_name,
                "issue_type": issue_type,
                "count": 0,
                "rows": [],
            },
        )
        bucket["count"] += 1
        bucket["rows"].append(row)

        current_priority = ISSUE_TYPE_PRIORITY.get(bucket["issue_type"], 99)
        row_priority = ISSUE_TYPE_PRIORITY.get(issue_type, 99)
        if row_priority < current_priority:
            bucket["issue_type"] = issue_type

    return sorted(
        grouped.values(),
        key=lambda item: (
            ISSUE_TYPE_PRIORITY.get(item["issue_type"], 99),
            -item["count"],
            item["issue"].lower(),
        ),
    )


def _serialize_issue_groups(issue_groups):
    serialized = []
    for group in issue_groups:
        serialized.append({
            "issue": group["issue"],
            "issue_type": group["issue_type"],
            "count": group["count"],
            "rows": [
                {
                    "url": row.url or "",
                    "issue_type": row.issue_type or "",
                    "details": row.details or "",
                }
                for row in group["rows"]
            ],
        })
    return serialized


def _clean_text(value):
    return (value or "").strip()


def _report_markdown_path(client, snapshot):
    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}.md"
    return os.path.join('reports', filename)


def _safe_date_text(value):
    try:
        return date.fromisoformat(value).isoformat() if value else ""
    except ValueError:
        return ""


def _parse_prefixed_value(value, fallback_type):
    text = (value or "").strip()
    if not text:
        return fallback_type, ""
    if "::" not in text:
        return fallback_type, text
    prefix, actual = text.split("::", 1)
    return prefix.strip().lower(), actual.strip()


def _ga4_dimension_parts(row):
    dimension_type, dimension_value = _parse_prefixed_value(row.dimension, "channel")
    return dimension_type, dimension_value or "N/A"


def _gsc_view_parts(row):
    if row.page:
        view_type, view_value = _parse_prefixed_value(row.page, "page")
    else:
        view_type, view_value = _parse_prefixed_value(row.query, "query")

    normalized = {
        "query": "queries",
        "page": "urls",
        "country": "country",
        "device": "device",
    }.get(view_type, "queries")
    return normalized, view_value or "N/A"


def _selected_date_range(default_rows, prefix):
    starts = sorted({_safe_date_text(row.period_start) for row in default_rows if _safe_date_text(row.period_start)})
    ends = sorted({_safe_date_text(row.period_end) for row in default_rows if _safe_date_text(row.period_end)})
    default_start = starts[0] if starts else ""
    default_end = ends[-1] if ends else ""
    selected_start = _safe_date_text(request.args.get(f"{prefix}_start")) or default_start
    selected_end = _safe_date_text(request.args.get(f"{prefix}_end")) or default_end
    return {
        "default_start": default_start,
        "default_end": default_end,
        "selected_start": selected_start,
        "selected_end": selected_end,
    }


def _matches_selected_range(row, selected_start, selected_end):
    row_start = _safe_date_text(row.period_start)
    row_end = _safe_date_text(row.period_end)
    if selected_start and row_start and row_start < selected_start:
        return False
    if selected_end and row_end and row_end > selected_end:
        return False
    return True


def _build_ga4_report(ga4_metrics):
    date_range = _selected_date_range(ga4_metrics, "ga4")
    selected_dimension = request.args.get("ga4_dimension", "channel").strip().lower()
    if selected_dimension not in GA4_DIMENSION_LABELS:
        selected_dimension = "channel"

    selected_sort = request.args.get("ga4_sort", "sessions").strip()
    if selected_sort not in GA4_SORT_LABELS:
        selected_sort = "sessions"

    filtered_rows = []
    for row in ga4_metrics:
        dimension_type, dimension_value = _ga4_dimension_parts(row)
        if dimension_type != selected_dimension:
            continue
        if not _matches_selected_range(row, date_range["selected_start"], date_range["selected_end"]):
            continue
        filtered_rows.append({
            "dimension_type": dimension_type,
            "dimension_value": dimension_value,
            "metric_name": row.metric_name or "N/A",
            "metric_value": row.metric_value,
            "period_start": row.period_start or "",
            "period_end": row.period_end or "",
        })

    filtered_rows.sort(
        key=lambda item: (
            item["metric_name"] != selected_sort,
            -(item["metric_value"] if item["metric_value"] is not None else float("-inf")),
            item["dimension_value"].lower(),
        )
    )

    return {
        "rows": filtered_rows,
        "selected_dimension": selected_dimension,
        "selected_sort": selected_sort,
        "dimension_label": GA4_DIMENSION_LABELS[selected_dimension],
        "date_range": date_range,
    }


def _build_gsc_report(gsc_metrics):
    date_range = _selected_date_range(gsc_metrics, "gsc")
    selected_view = request.args.get("gsc_view", "queries").strip().lower()
    if selected_view not in GSC_VIEW_LABELS:
        selected_view = "queries"

    selected_sort = request.args.get("gsc_sort", "impressions").strip()
    if selected_sort not in GSC_SORT_LABELS:
        selected_sort = "impressions"

    filtered_rows = []
    for row in gsc_metrics:
        view_type, view_value = _gsc_view_parts(row)
        if view_type != selected_view:
            continue
        if not _matches_selected_range(row, date_range["selected_start"], date_range["selected_end"]):
            continue
        filtered_rows.append({
            "label": view_value,
            "clicks": row.clicks or 0,
            "impressions": row.impressions or 0,
            "ctr": row.ctr or 0,
            "position": row.position,
            "period_start": row.period_start or "",
            "period_end": row.period_end or "",
        })

    reverse = selected_sort != "position"
    filtered_rows.sort(
        key=lambda item: (
            item[selected_sort] if item[selected_sort] is not None else (999999 if selected_sort == "position" else -1),
            item["label"].lower(),
        ),
        reverse=reverse,
    )

    if selected_sort == "position":
        filtered_rows.sort(
            key=lambda item: (
                item["position"] is None,
                item["position"] if item["position"] is not None else 999999,
                item["label"].lower(),
            )
        )

    return {
        "rows": filtered_rows,
        "selected_view": selected_view,
        "selected_sort": selected_sort,
        "view_label": GSC_VIEW_LABELS[selected_view],
        "date_range": date_range,
    }


def _meta_length(value):
    return len(_clean_text(value))


def _build_broken_link_report(crawl_links, limit=150):
    rows = []
    for row in crawl_links:
        if row.target_status is None or row.target_status < 400:
            continue
        rows.append({
            "broken_url": row.target_url or "",
            "anchor_text": row.anchor_text or "",
            "source_url": row.source_url or "",
            "status_code": row.target_status,
            "link_scope": "Internal" if row.is_internal else "External",
        })

    rows.sort(key=lambda item: (-int(item["status_code"] or 0), item["source_url"], item["broken_url"]))
    return {
        "total": len(rows),
        "rows": rows[:limit],
    }


def _build_internal_link_report(crawl_pages, crawl_links, limit=150, sort_key="unique_internal_links"):
    inbound_unique = {}
    inbound_total = {}

    for row in crawl_links:
        if not row.is_internal or not row.target_url:
            continue
        inbound_total[row.target_url] = inbound_total.get(row.target_url, 0) + 1
        inbound_unique.setdefault(row.target_url, set()).add(row.source_url or "")

    rows = []
    for page in crawl_pages:
        if page.is_internal is False:
            continue
        unique_sources = inbound_unique.get(page.url, set())
        rows.append({
            "url": page.url,
            "title": page.title or "",
            "status_code": page.status_code,
            "unique_internal_links": len([value for value in unique_sources if value]),
            "total_internal_links": inbound_total.get(page.url, 0),
            "word_count": page.word_count,
        })

    selected_sort = sort_key if sort_key in LINK_SORT_LABELS else "unique_internal_links"

    if selected_sort == "total_internal_links":
        rows.sort(
            key=lambda item: (
                -item["total_internal_links"],
                -item["unique_internal_links"],
                item["url"],
            )
        )
    else:
        rows.sort(
            key=lambda item: (
                -item["unique_internal_links"],
                -item["total_internal_links"],
                item["url"],
            )
        )

    return {
        "total": len(rows),
        "rows": rows[:limit],
        "selected_sort": selected_sort,
    }


def _build_image_report(crawl_images, limit=150):
    rows = []
    missing_alt = 0
    for row in crawl_images:
        alt_text = _clean_text(row.alt_text)
        missing = not alt_text
        if missing:
            missing_alt += 1
        rows.append({
            "image_url": row.image_url or "",
            "page_url": row.page_url or "",
            "alt_text": alt_text,
            "file_size_bytes": row.file_size_bytes,
            "dimensions": "×".join(str(value) for value in (row.width, row.height) if value) or "N/A",
            "alt_state": "Missing" if missing else "Present",
        })

    rows.sort(key=lambda item: (item["alt_state"] != "Missing", item["page_url"], item["image_url"]))
    return {
        "total": len(rows),
        "missing_alt": missing_alt,
        "rows": rows[:limit],
    }


def _build_meta_tag_report(crawl_pages, limit=150):
    title_counts = {}
    meta_counts = {}
    for page in crawl_pages:
        title = _clean_text(page.title)
        meta = _clean_text(page.meta_description)
        if title:
            title_counts[title] = title_counts.get(title, 0) + 1
        if meta:
            meta_counts[meta] = meta_counts.get(meta, 0) + 1

    rows = []
    flagged = 0
    for page in crawl_pages:
        title = _clean_text(page.title)
        meta = _clean_text(page.meta_description)
        title_length = len(title)
        meta_length = len(meta)
        flags = []

        if not title:
            flags.append("Missing title")
        elif title_counts.get(title, 0) > 1:
            flags.append("Duplicate title")
        elif title_length > 60:
            flags.append("Long title")

        if not meta:
            flags.append("Missing meta description")
        elif meta_counts.get(meta, 0) > 1:
            flags.append("Duplicate meta description")
        elif meta_length > 160:
            flags.append("Long meta description")

        if flags:
            flagged += 1

        rows.append({
            "url": page.url,
            "title": title,
            "meta_description": meta,
            "title_length": title_length or 0,
            "meta_length": meta_length or 0,
            "word_count": page.word_count,
            "flags": flags,
        })

    rows.sort(key=lambda item: (-len(item["flags"]), item["url"]))
    return {
        "total": len(rows),
        "flagged": flagged,
        "rows": rows[:limit],
    }


def _build_word_count_report(crawl_pages, limit=150):
    rows = []
    thin_count = 0
    for page in crawl_pages:
        if page.is_internal is False:
            continue
        word_count = page.word_count
        if word_count is None:
            bucket = "Unknown"
        elif word_count < 200:
            bucket = "Thin"
            thin_count += 1
        elif word_count < 500:
            bucket = "Medium"
        else:
            bucket = "Strong"

        rows.append({
            "url": page.url,
            "title": page.title or "",
            "word_count": word_count,
            "bucket": bucket,
        })

    rows.sort(key=lambda item: (item["word_count"] is None, item["word_count"] if item["word_count"] is not None else 10**9, item["url"]))
    return {
        "total": len(rows),
        "thin_count": thin_count,
        "rows": rows[:limit],
    }


def _build_canonical_report(crawl_pages, limit=150):
    rows = []
    for page in crawl_pages:
        canonical_url = _clean_text(page.canonical_url)
        flags = []
        if not canonical_url:
            flags.append("Missing canonical")
        elif canonical_url != page.url:
            flags.append("Canonical points elsewhere")

        if not flags:
            continue

        rows.append({
            "url": page.url,
            "canonical_url": canonical_url,
            "flags": flags,
        })

    rows.sort(key=lambda item: (-len(item["flags"]), item["url"]))
    return {
        "total": len(rows),
        "rows": rows[:limit],
    }


def _csv_response(filename, headers, rows):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@main_bp.route('/')
@login_required
def index():
    if current_user.role == 'admin':
        clients = Client.query.all()
    else:
        # User can only see clients assigned to them
        clients = current_user.clients
        
    return render_template('index.html', clients=clients)

@main_bp.route('/project/<int:client_id>')
@login_required
def project(client_id):
    client = Client.query.get_or_404(client_id)
    
    # Check authorization if not admin
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)
        
    snapshots = Snapshot.query.filter_by(client_id=client_id).order_by(Snapshot.created_at.desc()).all()
    keywords = Keyword.query.filter_by(client_id=client_id).order_by(Keyword.priority.asc(), Keyword.keyword.asc()).all()

    completed_snapshots = [snapshot for snapshot in snapshots if snapshot.status in ("complete", "partial")]
    latest_snapshot = completed_snapshots[0] if completed_snapshots else None
    previous_snapshot = completed_snapshots[1] if len(completed_snapshots) > 1 else None
    keyword_rankings = _build_keyword_rankings(keywords, latest_snapshot, previous_snapshot)
    health_score = compute_health_score(latest_snapshot, previous_snapshot)
    effective_ai_settings = get_effective_ai_settings(client.id)
    active_tab = request.args.get('tab', 'overview')
    if active_tab not in {"overview", "keywords", "history"}:
        active_tab = "overview"

    parsed_notes = {}
    for snapshot in snapshots:
        try:
            parsed_notes[snapshot.id] = json.loads(snapshot.notes) if snapshot.notes else {}
        except json.JSONDecodeError:
            parsed_notes[snapshot.id] = {"raw": snapshot.notes}

    return render_template(
        'project.html',
        client=client,
        snapshots=snapshots,
        keywords=keywords,
        latest_snapshot=latest_snapshot,
        previous_snapshot=previous_snapshot,
        keyword_rankings=keyword_rankings,
        health_score=health_score,
        effective_ai_settings=effective_ai_settings,
        parsed_notes=parsed_notes,
        active_tab=active_tab,
    )


@main_bp.route('/project/<int:client_id>/keywords/download')
@login_required
def download_keyword_rankings_csv(client_id):
    client = Client.query.get_or_404(client_id)
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    snapshots = Snapshot.query.filter_by(client_id=client_id).order_by(Snapshot.created_at.desc()).all()
    keywords = Keyword.query.filter_by(client_id=client_id).order_by(Keyword.priority.asc(), Keyword.keyword.asc()).all()
    latest_snapshot = next((snapshot for snapshot in snapshots if snapshot.status in ("complete", "partial")), None)

    if not latest_snapshot:
        flash("No completed snapshot is available yet for keyword export.", "error")
        return redirect(url_for('main.project', client_id=client.id))

    keyword_rankings = _build_keyword_rankings(keywords, latest_snapshot, None)
    crawl_pages = db.session.query(CrawlPage).filter_by(snapshot_id=latest_snapshot.id).all()
    crawl_pages_by_url = {_clean_text(page.url): page for page in crawl_pages if _clean_text(page.url)}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Sr. No.", "Keyword", "Search Volume", "Page Score", "Ranking URL"])

    for index, keyword in enumerate(keywords, start=1):
        ranking_state = keyword_rankings.get(keyword.id, {})
        latest = ranking_state.get("latest")
        page_score = _compute_keyword_page_score(latest, crawl_pages_by_url)

        writer.writerow([
            index,
            keyword.keyword,
            latest.search_volume if latest and latest.search_volume is not None else "",
            page_score if page_score is not None else "N/A",
            latest.url if latest and latest.url else "N/A",
        ])

    filename = f"{client.name.replace(' ', '_')}_keyword_rankings_snapshot{latest_snapshot.id}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@main_bp.route('/project/<int:client_id>/analyze', methods=['POST'])
@login_required
def analyze(client_id):
    client = Client.query.get_or_404(client_id)
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    snapshot = enqueue_snapshot_job(current_app._get_current_object(), client_id)
    flash(f"Analysis queued for snapshot #{snapshot.id}. Data collection has started in the background.", "success")
    return redirect(url_for('main.project', client_id=client_id))

@main_bp.route('/report/<int:snapshot_id>')
@login_required
def view_report(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get(snapshot.client_id)
    
    # Authorize
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)
        
    filepath = _report_markdown_path(client, snapshot)
    
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        report_html = markdown.markdown(
            content,
            extensions=[
                'extra',
                'sane_lists',
                'tables',
                'fenced_code',
                'toc',
            ],
        )
        return render_template(
            'report_view.html',
            client=client,
            snapshot=snapshot,
            report_title=f"{client.name} SEO Report",
            report_html=Markup(report_html),
        )
    else:
        flash("Report file not found. It might still be generating or was deleted.", "error")
        return redirect(url_for('main.project', client_id=client.id, tab='history'))


@main_bp.route('/report/<int:snapshot_id>/download')
@login_required
def download_report(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    pdf_filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}.pdf"
    filepath = _report_markdown_path(client, snapshot)
    if not os.path.exists(filepath):
        flash("Report file not found. It might still be generating or was deleted.", "error")
        return redirect(url_for('main.project', client_id=client.id, tab='history'))

    try:
        pdf_bytes = markdown_file_to_pdf_bytes(filepath)
    except Exception as exc:
        current_app.logger.exception("Failed to render PDF for snapshot %s", snapshot.id)
        flash(f"Could not generate PDF report: {exc}", "error")
        return redirect(url_for('main.project', client_id=client.id))

    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={"Content-Disposition": f'attachment; filename="{pdf_filename}"'},
    )


@main_bp.route('/snapshot/<int:snapshot_id>/delete', methods=['POST'])
@login_required
def delete_snapshot(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    filepath = _report_markdown_path(client, snapshot)

    try:
        db.session.delete(snapshot)
        db.session.commit()

        if os.path.exists(filepath):
            os.remove(filepath)

        flash(f"Snapshot #{snapshot_id} was deleted.", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to delete snapshot %s", snapshot_id)
        flash(f"Could not delete snapshot #{snapshot_id}.", "error")

    return redirect(url_for('main.project', client_id=client.id, tab='history'))


@main_bp.route('/snapshot/<int:snapshot_id>')
@login_required
def snapshot_detail(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    crawl_issues = db.session.query(CrawlIssue).filter_by(snapshot_id=snapshot_id).order_by(CrawlIssue.issue_type.asc(), CrawlIssue.issue.asc(), CrawlIssue.url.asc()).all()
    crawl_pages = db.session.query(CrawlPage).filter_by(snapshot_id=snapshot_id).order_by(CrawlPage.url.asc()).all()
    crawl_links = db.session.query(CrawlPageLink).filter_by(snapshot_id=snapshot_id).order_by(CrawlPageLink.source_url.asc(), CrawlPageLink.target_url.asc()).all()
    crawl_images = db.session.query(CrawlPageImage).filter_by(snapshot_id=snapshot_id).order_by(CrawlPageImage.page_url.asc(), CrawlPageImage.position.asc(), CrawlPageImage.image_url.asc()).all()
    ga4_metrics = db.session.query(Ga4Metric).filter_by(snapshot_id=snapshot_id).order_by(Ga4Metric.metric_name.asc(), Ga4Metric.metric_value.desc()).all()
    gsc_metrics = db.session.query(GscMetric).filter_by(snapshot_id=snapshot_id).order_by(GscMetric.impressions.desc()).all()
    rankings = db.session.query(Ranking).filter_by(snapshot_id=snapshot_id).order_by(Ranking.search_volume.desc().nullslast(), Ranking.keyword.asc()).all()
    backlinks = db.session.query(BacklinkHistory).filter_by(snapshot_id=snapshot_id).all()
    issue_groups = _group_crawl_issues(crawl_issues)
    issue_groups_data = _serialize_issue_groups(issue_groups)
    selected_group = issue_groups[0] if issue_groups else None
    selected_issue_rows = selected_group["rows"] if selected_group else []
    broken_link_report = _build_broken_link_report(crawl_links)
    link_sort = (request.args.get("link_sort") or "unique_internal_links").strip()
    internal_link_report = _build_internal_link_report(crawl_pages, crawl_links, sort_key=link_sort)
    image_report = _build_image_report(crawl_images)
    meta_tag_report = _build_meta_tag_report(crawl_pages)
    word_count_report = _build_word_count_report(crawl_pages)
    canonical_report = _build_canonical_report(crawl_pages)
    ga4_report = _build_ga4_report(ga4_metrics)
    gsc_report = _build_gsc_report(gsc_metrics)

    try:
        notes = json.loads(snapshot.notes) if snapshot.notes else {}
    except json.JSONDecodeError:
        notes = {"raw": snapshot.notes}

    return render_template(
        'snapshot_detail.html',
        client=client,
        snapshot=snapshot,
        notes=notes,
        crawl_issues=crawl_issues,
        crawl_pages=crawl_pages,
        crawl_links=crawl_links,
        crawl_images=crawl_images,
        issue_groups=issue_groups,
        issue_groups_data=issue_groups_data,
        selected_issue=selected_group["issue"] if selected_group else "",
        selected_issue_rows=selected_issue_rows,
        broken_link_report=broken_link_report,
        internal_link_report=internal_link_report,
        link_sort_labels=LINK_SORT_LABELS,
        image_report=image_report,
        meta_tag_report=meta_tag_report,
        word_count_report=word_count_report,
        canonical_report=canonical_report,
        ga4_metrics=ga4_metrics,
        ga4_report=ga4_report,
        ga4_dimension_labels=GA4_DIMENSION_LABELS,
        ga4_sort_labels=GA4_SORT_LABELS,
        gsc_metrics=gsc_metrics,
        gsc_report=gsc_report,
        gsc_view_labels=GSC_VIEW_LABELS,
        gsc_sort_labels=GSC_SORT_LABELS,
        rankings=rankings,
        backlinks=backlinks,
    )


@main_bp.route('/snapshot/<int:snapshot_id>/ga4/download')
@login_required
def download_ga4_csv(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    ga4_metrics = db.session.query(Ga4Metric).filter_by(snapshot_id=snapshot_id).order_by(Ga4Metric.metric_name.asc(), Ga4Metric.metric_value.desc()).all()
    ga4_report = _build_ga4_report(ga4_metrics)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Sr. No.", ga4_report["dimension_label"], "Metric", "Value", "Period Start", "Period End"])

    for index, row in enumerate(ga4_report["rows"], start=1):
        writer.writerow([
            index,
            row["dimension_value"],
            row["metric_name"],
            row["metric_value"] if row["metric_value"] is not None else "",
            row["period_start"],
            row["period_end"],
        ])

    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}_ga4_{ga4_report['selected_dimension']}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@main_bp.route('/snapshot/<int:snapshot_id>/gsc/download')
@login_required
def download_gsc_csv(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    gsc_metrics = db.session.query(GscMetric).filter_by(snapshot_id=snapshot_id).order_by(GscMetric.impressions.desc()).all()
    gsc_report = _build_gsc_report(gsc_metrics)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Sr. No.", gsc_report["view_label"], "Clicks", "Impressions", "CTR", "Average Position", "Period Start", "Period End"])

    for index, row in enumerate(gsc_report["rows"], start=1):
        writer.writerow([
            index,
            row["label"],
            row["clicks"],
            row["impressions"],
            row["ctr"],
            row["position"] if row["position"] is not None else "",
            row["period_start"],
            row["period_end"],
        ])

    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}_gsc_{gsc_report['selected_view']}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@main_bp.route('/snapshot/<int:snapshot_id>/issues/download')
@login_required
def download_issue_category_csv(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    selected_issue = (request.args.get("issue") or "").strip()
    if not selected_issue:
        flash("Select an issue category before downloading CSV.", "error")
        return redirect(url_for('main.snapshot_detail', snapshot_id=snapshot.id))

    rows = db.session.query(CrawlIssue).filter_by(snapshot_id=snapshot.id, issue=selected_issue).order_by(CrawlIssue.url.asc()).all()
    if not rows:
        flash("No crawl issue rows found for the selected category.", "error")
        return redirect(url_for('main.snapshot_detail', snapshot_id=snapshot.id))

    csv_rows = []
    for index, row in enumerate(rows, start=1):
        csv_rows.append([
            index,
            row.issue_type or "",
            row.issue or "",
            row.url or "",
            row.details or "",
        ])

    safe_issue = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in selected_issue).strip("_") or "issue"
    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}_{safe_issue}.csv"
    return _csv_response(
        filename,
        ["Sr. No.", "Issue Type", "Issue Category", "URL", "Details"],
        csv_rows,
    )


@main_bp.route('/snapshot/<int:snapshot_id>/links/download')
@login_required
def download_internal_links_csv(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    link_sort = (request.args.get("link_sort") or "unique_internal_links").strip()
    crawl_pages = db.session.query(CrawlPage).filter_by(snapshot_id=snapshot_id).order_by(CrawlPage.url.asc()).all()
    crawl_links = db.session.query(CrawlPageLink).filter_by(snapshot_id=snapshot_id).order_by(CrawlPageLink.source_url.asc(), CrawlPageLink.target_url.asc()).all()
    internal_link_report = _build_internal_link_report(crawl_pages, crawl_links, limit=100000, sort_key=link_sort)

    csv_rows = []
    for index, row in enumerate(internal_link_report["rows"], start=1):
        csv_rows.append([
            index,
            row["url"],
            row["unique_internal_links"],
            row["total_internal_links"],
            row["status_code"] or "",
            row["title"],
            row["word_count"] if row["word_count"] is not None else "",
        ])

    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}_internal_links_{internal_link_report['selected_sort']}.csv"
    return _csv_response(
        filename,
        ["Sr. No.", "Page", "Unique Internal Links", "Total Internal Links", "Status", "Title", "Word Count"],
        csv_rows,
    )


@main_bp.route('/snapshot/<int:snapshot_id>/images/download')
@login_required
def download_images_csv(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    crawl_images = db.session.query(CrawlPageImage).filter_by(snapshot_id=snapshot_id).order_by(CrawlPageImage.page_url.asc(), CrawlPageImage.position.asc(), CrawlPageImage.image_url.asc()).all()
    image_report = _build_image_report(crawl_images, limit=100000)

    csv_rows = []
    for index, row in enumerate(image_report["rows"], start=1):
        csv_rows.append([
            index,
            row["image_url"],
            row["alt_text"],
            row["alt_state"],
            row["page_url"],
            row["file_size_bytes"] if row["file_size_bytes"] is not None else "",
            row["dimensions"],
        ])

    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}_images.csv"
    return _csv_response(
        filename,
        ["Sr. No.", "Image URL", "Alt Text", "Alt State", "Page URL", "File Size Bytes", "Dimensions"],
        csv_rows,
    )


@main_bp.route('/snapshot/<int:snapshot_id>/meta-tags/download')
@login_required
def download_meta_tags_csv(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    crawl_pages = db.session.query(CrawlPage).filter_by(snapshot_id=snapshot_id).order_by(CrawlPage.url.asc()).all()
    meta_tag_report = _build_meta_tag_report(crawl_pages, limit=100000)

    csv_rows = []
    for index, row in enumerate(meta_tag_report["rows"], start=1):
        csv_rows.append([
            index,
            row["url"],
            row["title"],
            row["meta_description"],
            row["title_length"],
            row["meta_length"],
            row["word_count"] if row["word_count"] is not None else "",
            ", ".join(row["flags"]) if row["flags"] else "OK",
        ])

    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}_meta_tags.csv"
    return _csv_response(
        filename,
        ["Sr. No.", "Page", "Meta Title", "Meta Description", "Title Length", "Meta Description Length", "Word Count", "Flags"],
        csv_rows,
    )


@main_bp.route('/snapshot/<int:snapshot_id>/word-count/download')
@login_required
def download_word_count_csv(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    crawl_pages = db.session.query(CrawlPage).filter_by(snapshot_id=snapshot_id).order_by(CrawlPage.url.asc()).all()
    word_count_report = _build_word_count_report(crawl_pages, limit=100000)

    csv_rows = []
    for index, row in enumerate(word_count_report["rows"], start=1):
        csv_rows.append([
            index,
            row["url"],
            row["title"],
            row["word_count"] if row["word_count"] is not None else "",
            row["bucket"],
        ])

    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}_word_count.csv"
    return _csv_response(
        filename,
        ["Sr. No.", "Page", "Title", "Word Count", "Bucket"],
        csv_rows,
    )


@main_bp.route('/snapshot/<int:snapshot_id>/canonical/download')
@login_required
def download_canonical_csv(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    crawl_pages = db.session.query(CrawlPage).filter_by(snapshot_id=snapshot_id).order_by(CrawlPage.url.asc()).all()
    canonical_report = _build_canonical_report(crawl_pages, limit=100000)

    csv_rows = []
    for index, row in enumerate(canonical_report["rows"], start=1):
        csv_rows.append([
            index,
            row["url"],
            row["canonical_url"] or "",
            ", ".join(row["flags"]),
        ])

    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}_canonical.csv"
    return _csv_response(
        filename,
        ["Sr. No.", "Page", "Canonical URL", "Flags"],
        csv_rows,
    )
