from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import db, Client, Keyword
from functools import wraps

admin_bp = Blueprint('admin', __name__)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.role != 'admin':
            flash("You do not have permission to access this page.", "error")
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_project():
    if request.method == 'POST':
        name = request.form.get('name')
        domain = request.form.get('domain')
        location = request.form.get('location')
        business_context = request.form.get('business_context')
        ga4_property_id = request.form.get('ga4_property_id')
        gsc_site_url = request.form.get('gsc_site_url')
        keywords_input = request.form.get('keywords', '')

        if not name or not domain:
            flash("Name and Domain are required.", "error")
            return redirect(url_for('admin.add_project'))

        new_client = Client( # type: ignore
            name=name,
            domain=domain,
            location=location,
            business_context=business_context,
            ga4_property_id=ga4_property_id,
            gsc_site_url=gsc_site_url
        )
        
        db.session.add(new_client)
        db.session.flush() # Get the new client ID

        # Process keywords (comma separated)
        if keywords_input.strip():
            kws = [k.strip() for k in keywords_input.split(',') if k.strip()]
            for kw in kws:
                new_kw = Keyword(client_id=new_client.id, keyword=kw, priority='high') # type: ignore
                db.session.add(new_kw)

        db.session.commit()
        flash("Project added successfully!", "success")
        return redirect(url_for('main.index'))

    return render_template('add_project.html')

from app.models import AISetting

@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def settings():
    setting = AISetting.query.first()
    if not setting:
        setting = AISetting(model_name='z-ai/glm-5.2', system_prompt='You are an expert SEO Copilot.')
        db.session.add(setting)
        db.session.commit()

    if request.method == 'POST':
        setting.model_name = request.form.get('model_name')
        setting.system_prompt = request.form.get('system_prompt')
        db.session.commit()
        flash("AI Settings updated successfully!", "success")
        return redirect(url_for('admin.settings'))

    return render_template('settings.html', setting=setting)

from app.models import User

@admin_bp.route('/users')
@login_required
@admin_required
def users():
    all_users = User.query.all()
    return render_template('users.html', users=all_users)

@admin_bp.route('/users/add', methods=['POST'])
@login_required
@admin_required
def add_user():
    username = request.form.get('username')
    password = request.form.get('password')
    role = request.form.get('role', 'member')
    
    if User.query.filter_by(username=username).first():
        flash("Username already exists.", "error")
    else:
        new_user = User(username=username, role=role) # type: ignore
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        flash("User created successfully.", "success")
        
    return redirect(url_for('admin.users'))

@admin_bp.route('/users/<int:user_id>/assign', methods=['GET', 'POST'])
@login_required
@admin_required
def assign_projects(user_id):
    user = User.query.get_or_404(user_id)
    all_clients = Client.query.all()
    
    if request.method == 'POST':
        # Get list of checked client IDs
        assigned_ids = request.form.getlist('client_ids')
        assigned_ids = [int(i) for i in assigned_ids]
        
        # Clear current assignments and re-add
        user.clients = []
        for client in all_clients:
            if client.id in assigned_ids:
                user.clients.append(client)
                
        db.session.commit()
        flash(f"Projects assigned to {user.username} successfully.", "success")
        return redirect(url_for('admin.users'))
        
    return render_template('assign_project.html', target_user=user, all_clients=all_clients)
