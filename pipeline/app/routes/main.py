import csv
import io
import json
import os

from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

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


def _build_keyword_rankings(keywords, current_snapshot, previous_snapshot):
    if not current_snapshot:
        return {}

    current_rows = Ranking.query.filter_by(snapshot_id=current_snapshot.id).all()
    previous_rows = Ranking.query.filter_by(snapshot_id=previous_snapshot.id).all() if previous_snapshot else []

    current_by_keyword = {row.keyword: row for row in current_rows}
    previous_by_keyword = {row.keyword: row for row in previous_rows}

    keyword_rankings = {}
    for keyword in keywords:
        latest = current_by_keyword.get(keyword.keyword)
        previous = previous_by_keyword.get(keyword.keyword)

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

        keyword_rankings[keyword.keyword] = {
            "latest": latest,
            "previous": previous,
            "current_position": current_position,
            "previous_position": previous_position,
            "movement": movement,
            "movement_label": movement_label,
            "movement_tone": movement_tone,
        }

    return keyword_rankings


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


def _build_internal_link_report(crawl_pages, crawl_links, limit=150):
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
        
    # The convention for report filenames was: {ClientName}_snapshot{ID}.md
    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}.md"
    filepath = os.path.join('reports', filename)
    
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        # For now, return as plain text. Later we can parse Markdown to HTML.
        from flask import Response
        return Response(content, mimetype='text/plain')
    else:
        flash("Report file not found. It might still be generating or was deleted.", "error")
        return redirect(url_for('main.project', client_id=client.id))


@main_bp.route('/report/<int:snapshot_id>/download')
@login_required
def download_report(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    markdown_filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}.md"
    pdf_filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}.pdf"
    filepath = os.path.join('reports', markdown_filename)
    if not os.path.exists(filepath):
        flash("Report file not found. It might still be generating or was deleted.", "error")
        return redirect(url_for('main.project', client_id=client.id))

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
    gsc_metrics = db.session.query(GscMetric).filter_by(snapshot_id=snapshot_id).order_by(GscMetric.impressions.desc()).limit(100).all()
    rankings = db.session.query(Ranking).filter_by(snapshot_id=snapshot_id).order_by(Ranking.search_volume.desc().nullslast(), Ranking.keyword.asc()).all()
    backlinks = db.session.query(BacklinkHistory).filter_by(snapshot_id=snapshot_id).all()
    issue_groups = _group_crawl_issues(crawl_issues)
    issue_groups_data = _serialize_issue_groups(issue_groups)
    selected_group = issue_groups[0] if issue_groups else None
    selected_issue_rows = selected_group["rows"] if selected_group else []
    broken_link_report = _build_broken_link_report(crawl_links)
    internal_link_report = _build_internal_link_report(crawl_pages, crawl_links)
    image_report = _build_image_report(crawl_images)
    meta_tag_report = _build_meta_tag_report(crawl_pages)
    word_count_report = _build_word_count_report(crawl_pages)
    canonical_report = _build_canonical_report(crawl_pages)

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
        image_report=image_report,
        meta_tag_report=meta_tag_report,
        word_count_report=word_count_report,
        canonical_report=canonical_report,
        ga4_metrics=ga4_metrics,
        gsc_metrics=gsc_metrics,
        rankings=rankings,
        backlinks=backlinks,
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

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Sr. No.", "Issue Type", "Issue Category", "URL", "Details"])
    for index, row in enumerate(rows, start=1):
        writer.writerow([
            index,
            row.issue_type or "",
            row.issue or "",
            row.url or "",
            row.details or "",
        ])

    safe_issue = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in selected_issue).strip("_") or "issue"
    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}_{safe_issue}.csv"

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
