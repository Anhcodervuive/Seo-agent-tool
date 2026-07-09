from flask import Blueprint, render_template, redirect, url_for, abort
from flask_login import login_required, current_user
from app.models import Client, Snapshot, Keyword

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
@login_required
def index():
    if current_user.role == 'admin':
        clients = Client.query.all()
    else:
        # User can only see clients assigned to them
        clients = current_user.clients.all()
        
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
