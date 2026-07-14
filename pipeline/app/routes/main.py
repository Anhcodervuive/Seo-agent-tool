from flask import Blueprint, render_template, redirect, url_for, abort, flash
from flask_login import login_required, current_user
from app.models import db, Client, Snapshot, Keyword

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
    keywords = Keyword.query.filter_by(client_id=client_id).all()
    
    return render_template('project.html', client=client, snapshots=snapshots, keywords=keywords)

@main_bp.route('/project/<int:client_id>/analyze', methods=['POST'])
@login_required
def analyze(client_id):
    client = Client.query.get_or_404(client_id)
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)
        
    # Create a pending snapshot to indicate an audit is queued
    new_snapshot = Snapshot(client_id=client_id, status='pending', notes='Audit queued via Dashboard') # type: ignore
    db.session.add(new_snapshot)
    db.session.commit()
    
    flash("Analysis queued! The AI Agent will start gathering fresh data shortly.", "success")
    return redirect(url_for('main.project', client_id=client_id))

import os

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
