import json
import os
import uuid

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import db, Client, Keyword, Competitor, Snapshot, AISetting, ProjectAISetting, GoogleAccountConfig
from functools import wraps
from services.ai_settings import get_global_ai_setting
from services.google_accounts import GOOGLE_ACCOUNTS_DIR, ensure_google_accounts_dir, get_available_google_accounts, get_default_google_account

admin_bp = Blueprint('admin', __name__)

MODEL_OPTIONS = [
    ("z-ai/glm-5.2", "Z-AI GLM-5.2 (Recommended)"),
    ("openai/gpt-4o", "OpenAI GPT-4o"),
    ("anthropic/claude-3-5-sonnet", "Claude 3.5 Sonnet"),
]


def parse_keywords_input(raw_value, default_location):
    keywords = []
    for line in raw_value.splitlines():
        entry = line.strip()
        if not entry:
            continue
        parts = [part.strip() for part in entry.split('|')]
        keyword = parts[0]
        if not keyword:
            continue
        keywords.append({
            "keyword": keyword,
            "priority": parts[1] if len(parts) > 1 and parts[1] else "medium",
            "device": parts[2] if len(parts) > 2 and parts[2] else "desktop",
            "location": parts[3] if len(parts) > 3 and parts[3] else (default_location or "United States"),
            "language": parts[4] if len(parts) > 4 and parts[4] else "en",
        })
    return keywords


def serialize_keywords(keywords):
    return "\n".join(
        f"{keyword['keyword']}|{keyword['priority']}|{keyword['device']}|{keyword['location']}|{keyword['language']}"
        for keyword in keywords
    )


def normalize_credentials_path(raw_path):
    if not raw_path:
        return ""
    cleaned = raw_path.strip()
    return cleaned.replace("/", "\\")


def resolve_service_email(credentials_path, provided_email=""):
    if provided_email.strip():
        return provided_email.strip()
    try:
        with open(credentials_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    return payload.get("client_email")


def parse_uploaded_google_credentials(uploaded_file):
    if not uploaded_file or not uploaded_file.filename:
        return None, None, "A Google service-account JSON file is required."

    try:
        payload = json.load(uploaded_file.stream)
    except ValueError:
        return None, None, "Uploaded file is not valid JSON."

    required_keys = {"type", "project_id", "private_key", "client_email"}
    if not required_keys.issubset(payload.keys()):
        return None, None, "Uploaded JSON does not look like a valid Google service-account key."

    return payload, payload.get("client_email"), None


def store_google_credentials_payload(payload):
    ensure_google_accounts_dir()
    filename = f"{uuid.uuid4().hex}.json"
    stored_path = os.path.join(GOOGLE_ACCOUNTS_DIR, filename)
    with open(stored_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return filename


def set_default_google_account(target_account):
    if not target_account:
        return
    GoogleAccountConfig.query.update({"is_default": False})
    target_account.is_default = True

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
        google_account_id = request.form.get('google_account_id') or None
        keywords_input = request.form.get('keywords', '')
        competitors_input = request.form.get('competitors', '')
        crawl_mode = request.form.get('crawl_mode', 'full')
        crawl_paths = request.form.get('crawl_paths', '')
        ai_model_override = request.form.get('ai_model_override', '').strip()
        ai_prompt_override = request.form.get('ai_prompt_override', '').strip()

        if not name or not domain:
            flash("Name and Domain are required.", "error")
            return redirect(url_for('admin.add_project'))

        new_client = Client( # type: ignore
            name=name,
            domain=domain,
            location=location,
            business_context=business_context,
            google_account_id=int(google_account_id) if google_account_id else None,
            ga4_property_id=ga4_property_id,
            gsc_site_url=gsc_site_url,
            crawl_mode=crawl_mode,
            crawl_paths=crawl_paths
        )
        
        db.session.add(new_client)
        db.session.flush() # Get the new client ID

        # Process keywords (one per line; metadata optional)
        if keywords_input.strip():
            kws = parse_keywords_input(keywords_input, location)
            for kw in kws:
                new_kw = Keyword( # type: ignore
                    client_id=new_client.id,
                    keyword=kw["keyword"],
                    priority=kw["priority"],
                    device=kw["device"],
                    location=kw["location"],
                    language=kw["language"],
                )
                db.session.add(new_kw)

        # Process competitors (comma separated)
        if competitors_input.strip():
            comps = [c.strip() for c in competitors_input.split(',') if c.strip()]
            for comp in comps:
                new_comp = Competitor(client_id=new_client.id, domain=comp) # type: ignore
                db.session.add(new_comp)

        if ai_model_override or ai_prompt_override:
            db.session.add(ProjectAISetting(
                client_id=new_client.id,
                model_name=ai_model_override or None,
                system_prompt=ai_prompt_override or None,
            ))

        db.session.commit()
        flash("Project added successfully!", "success")
        return redirect(url_for('main.index'))

    global_setting = get_global_ai_setting()
    return render_template(
        'add_project.html',
        model_options=MODEL_OPTIONS,
        global_setting=global_setting,
        google_accounts=get_available_google_accounts(),
        default_google_account=get_default_google_account(),
        keyword_rows=[],
        competitor_rows=[],
    )

@admin_bp.route('/project/<int:client_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_project(client_id):
    client = Client.query.get_or_404(client_id)
    project_ai_setting = ProjectAISetting.query.filter_by(client_id=client.id).first()
    
    if request.method == 'POST':
        client.name = request.form.get('name')
        client.domain = request.form.get('domain')
        client.location = request.form.get('location')
        client.business_context = request.form.get('business_context')
        google_account_id = request.form.get('google_account_id') or None
        client.google_account_id = int(google_account_id) if google_account_id else None
        client.ga4_property_id = request.form.get('ga4_property_id')
        client.gsc_site_url = request.form.get('gsc_site_url')
        client.crawl_mode = request.form.get('crawl_mode', 'full')
        client.crawl_paths = request.form.get('crawl_paths', '')
        ai_model_override = request.form.get('ai_model_override', '').strip()
        ai_prompt_override = request.form.get('ai_prompt_override', '').strip()
        
        keywords_input = request.form.get('keywords', '')
        competitors_input = request.form.get('competitors', '')
        
        # Update Keywords (delete old, add new)
        Keyword.query.filter_by(client_id=client.id).delete()
        if keywords_input.strip():
            kws = parse_keywords_input(keywords_input, client.location)
            for kw in kws:
                new_kw = Keyword( # type: ignore
                    client_id=client.id,
                    keyword=kw["keyword"],
                    priority=kw["priority"],
                    device=kw["device"],
                    location=kw["location"],
                    language=kw["language"],
                )
                db.session.add(new_kw)
                
        # Update Competitors (delete old, add new)
        Competitor.query.filter_by(client_id=client.id).delete()
        if competitors_input.strip():
            comps = [c.strip() for c in competitors_input.split(',') if c.strip()]
            for comp in comps:
                new_comp = Competitor(client_id=client.id, domain=comp) # type: ignore
                db.session.add(new_comp)

        if ai_model_override or ai_prompt_override:
            if not project_ai_setting:
                project_ai_setting = ProjectAISetting(client_id=client.id)
                db.session.add(project_ai_setting)
            project_ai_setting.model_name = ai_model_override or None
            project_ai_setting.system_prompt = ai_prompt_override or None
        elif project_ai_setting:
            db.session.delete(project_ai_setting)
                
        db.session.commit()
        flash("Project updated successfully!", "success")
        return redirect(url_for('main.project', client_id=client.id))
        
    # GET: Prepare keywords and competitors strings for textareas
    keyword_rows = [
        {
            "keyword": k.keyword,
            "priority": k.priority,
            "device": k.device,
            "location": k.location,
            "language": k.language,
        }
        for k in client.keywords
    ]
    competitor_rows = [{"domain": c.domain} for c in client.competitors]
    keywords_str = serialize_keywords(keyword_rows)
    competitors_str = ", ".join([c["domain"] for c in competitor_rows])
    
    global_setting = get_global_ai_setting()
    return render_template(
        'edit_project.html',
        client=client,
        keywords_str=keywords_str,
        competitors_str=competitors_str,
        keyword_rows=keyword_rows,
        competitor_rows=competitor_rows,
        model_options=MODEL_OPTIONS,
        global_setting=global_setting,
        project_ai_setting=project_ai_setting,
        google_accounts=get_available_google_accounts(),
        default_google_account=get_default_google_account(),
    )

@admin_bp.route('/project/<int:client_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_project(client_id):
    client = Client.query.get_or_404(client_id)
    
    # We must manually delete snapshots or let cascade handle it.
    # Since we didn't explicitly define cascade on Snapshots in Client, let's delete them manually to be safe.
    snapshots = Snapshot.query.filter_by(client_id=client.id).all()
    for s in snapshots:
        db.session.delete(s)
        
    db.session.delete(client)
    db.session.commit()
    
    flash(f"Project '{client.name}' deleted successfully.", "success")
    return redirect(url_for('main.index'))

@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def settings():
    setting = get_global_ai_setting()

    if request.method == 'POST':
        setting.model_name = request.form.get('model_name')
        setting.system_prompt = request.form.get('system_prompt')
        db.session.commit()
        flash("AI Settings updated successfully!", "success")
        return redirect(url_for('admin.settings'))

    return render_template(
        'settings.html',
        setting=setting,
        model_options=MODEL_OPTIONS,
    )


@admin_bp.route('/google-accounts', methods=['GET', 'POST'])
@login_required
@admin_required
def google_accounts():
    if request.method == 'POST':
        action = request.form.get('action', '')

        if action == 'add_google_account':
            payload, detected_email, error = parse_uploaded_google_credentials(request.files.get('credentials_file'))
            if error:
                flash(error, "error")
                return redirect(url_for('admin.google_accounts'))
            stored_filename = store_google_credentials_payload(payload)
            account = GoogleAccountConfig(
                name=request.form.get('account_name', '').strip() or 'Google Account',
                service_email=request.form.get('service_email', '').strip() or detected_email,
                credentials_path='[managed-upload]',
                stored_filename=stored_filename,
                active=bool(request.form.get('is_active')),
            )
            db.session.add(account)
            db.session.flush()
            if request.form.get('is_default'):
                set_default_google_account(account)
            db.session.commit()
            flash("Google account added successfully.", "success")
            return redirect(url_for('admin.google_accounts'))

        if action == 'update_google_account':
            account_id = request.form.get('account_id')
            account = GoogleAccountConfig.query.get_or_404(account_id)
            account.name = request.form.get('account_name', '').strip() or account.name
            account.active = bool(request.form.get('is_active'))
            uploaded_file = request.files.get('credentials_file')
            if uploaded_file and uploaded_file.filename:
                payload, detected_email, error = parse_uploaded_google_credentials(uploaded_file)
                if error:
                    flash(error, "error")
                    return redirect(url_for('admin.google_accounts'))
                account.stored_filename = store_google_credentials_payload(payload)
                account.credentials_path = '[managed-upload]'
                account.service_email = request.form.get('service_email', '').strip() or detected_email
            else:
                account.service_email = request.form.get('service_email', '').strip() or account.service_email
            if request.form.get('is_default'):
                set_default_google_account(account)
            elif account.is_default and not request.form.get('is_active'):
                account.is_default = False
            db.session.commit()
            flash("Google account updated successfully.", "success")
            return redirect(url_for('admin.google_accounts'))

        if action == 'delete_google_account':
            account_id = request.form.get('account_id')
            account = GoogleAccountConfig.query.get_or_404(account_id)
            replacement = get_default_google_account() if account.is_default else None
            for client in account.clients:
                if replacement and replacement.id != account.id:
                    client.google_account_id = replacement.id
                else:
                    client.google_account_id = None
            db.session.delete(account)
            db.session.commit()
            flash("Google account deleted successfully.", "success")
            return redirect(url_for('admin.google_accounts'))

    return render_template(
        'google_accounts.html',
        google_accounts=GoogleAccountConfig.query.order_by(
            GoogleAccountConfig.is_default.desc(),
            GoogleAccountConfig.name.asc(),
        ).all(),
    )

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

@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    
    if user.id == current_user.id:
        flash("You cannot delete your own account.", "error")
        return redirect(url_for('admin.users'))
        
    # Clear associations just to be perfectly safe before deleting
    user.clients = []
    
    db.session.delete(user)
    db.session.commit()
    
    flash(f"User '{user.username}' has been deleted.", "success")
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
