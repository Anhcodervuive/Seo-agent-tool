import json
import os

from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.models import (
    BacklinkHistory,
    Client,
    CrawlIssue,
    Ga4Metric,
    GscMetric,
    Keyword,
    Ranking,
    Snapshot,
    db,
)
from services.pipeline_runner import enqueue_snapshot_job

main_bp = Blueprint('main', __name__)

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

    latest_snapshot = snapshots[0] if snapshots else None
    latest_rankings = {}
    if latest_snapshot:
        ranking_rows = Ranking.query.filter_by(snapshot_id=latest_snapshot.id).all()
        latest_rankings = {row.keyword: row for row in ranking_rows}

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
        latest_rankings=latest_rankings,
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

    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}.md"
    filepath = os.path.join('reports', filename)
    if not os.path.exists(filepath):
        flash("Report file not found. It might still be generating or was deleted.", "error")
        return redirect(url_for('main.project', client_id=client.id))

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    return Response(
        content,
        mimetype='text/markdown',
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@main_bp.route('/snapshot/<int:snapshot_id>')
@login_required
def snapshot_detail(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    crawl_issues = db.session.query(CrawlIssue).filter_by(snapshot_id=snapshot_id).order_by(CrawlIssue.issue_type.asc(), CrawlIssue.url.asc()).limit(100).all()
    ga4_metrics = db.session.query(Ga4Metric).filter_by(snapshot_id=snapshot_id).order_by(Ga4Metric.metric_name.asc(), Ga4Metric.metric_value.desc()).all()
    gsc_metrics = db.session.query(GscMetric).filter_by(snapshot_id=snapshot_id).order_by(GscMetric.impressions.desc()).limit(100).all()
    rankings = db.session.query(Ranking).filter_by(snapshot_id=snapshot_id).order_by(Ranking.search_volume.desc().nullslast(), Ranking.keyword.asc()).all()
    backlinks = db.session.query(BacklinkHistory).filter_by(snapshot_id=snapshot_id).all()

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
        ga4_metrics=ga4_metrics,
        gsc_metrics=gsc_metrics,
        rankings=rankings,
        backlinks=backlinks,
    )
