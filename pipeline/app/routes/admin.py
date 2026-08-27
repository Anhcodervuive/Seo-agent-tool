import json
import os
import re
import uuid
from zoneinfo import available_timezones

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import db, AuditSchedule, Client, Keyword, Competitor, Snapshot, AISetting, ProjectAISetting, GoogleAccountConfig, User
from functools import wraps
from services.audit_queue import upsert_schedule
from services.ai_settings import get_global_ai_setting
from services.google_accounts import GOOGLE_ACCOUNTS_DIR, ensure_google_accounts_dir, get_available_google_accounts, get_default_google_account
from services.ai_models import AIModelValidationError, model_options_for_selection, validate_model_for_copilot
from services.dataforseo_locations import (
    GOOGLE_LOCATIONS,
    normalize_competitor_traffic_locations,
    normalize_google_location,
)
from services.site_urls import normalize_site_url
from services.keyword_languages import keyword_language_options, normalize_keyword_language

admin_bp = Blueprint('admin', __name__)

ALLOWED_KEYWORD_PRIORITIES = {"high", "medium", "low"}
ALLOWED_KEYWORD_DEVICES = {"desktop", "mobile"}
SCHEDULE_TIMEZONES = sorted(
    timezone for timezone in available_timezones()
    if not timezone.startswith(("Etc/", "posix/", "right/"))
)


def parse_keywords_input(raw_value, default_location):
    default_location = normalize_google_location(default_location)
    keywords = []
    for line_number, line in enumerate(raw_value.splitlines(), start=1):
        entry = line.strip()
        if not entry:
            continue
        parts = split_keyword_entry(entry)
        keyword = parts[0]
        if not keyword:
            continue
        priority = parts[1].lower() if len(parts) > 1 and parts[1] else "medium"
        device = parts[2].lower() if len(parts) > 2 and parts[2] else "desktop"
        requested_location = parts[3] if len(parts) > 3 and parts[3] else default_location
        try:
            location = normalize_google_location(requested_location)
            language = normalize_keyword_language(parts[4] if len(parts) > 4 else "en")
        except ValueError as exc:
            raise ValueError(f"Keyword line {line_number}: {exc}") from exc
        keywords.append({
            "keyword": keyword,
            "priority": priority if priority in ALLOWED_KEYWORD_PRIORITIES else "medium",
            "device": device if device in ALLOWED_KEYWORD_DEVICES else "desktop",
            "location": location,
            "language": language,
        })
    return keywords


def split_keyword_entry(entry):
    if "|" in entry:
        return [part.strip() for part in entry.split("|")]

    if "," in entry:
        comma_parts = [part.strip() for part in re.split(r"\s*,\s*", entry)]
        if len(comma_parts) >= 2:
            possible_priority = comma_parts[1].lower()
            possible_device = comma_parts[2].lower() if len(comma_parts) > 2 else ""
            if possible_priority in ALLOWED_KEYWORD_PRIORITIES or possible_device in ALLOWED_KEYWORD_DEVICES:
                return comma_parts

    return [entry.strip()]


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


def _validate_changed_model(requested_model, current_model):
    """Protect an existing client selection while validating any new model choice."""
    if requested_model and requested_model != current_model:
        validate_model_for_copilot(requested_model)


def _model_selection_context(*selected_models):
    model_options, model_catalog_warning = model_options_for_selection(*selected_models)
    return {
        "model_options": model_options,
        "model_catalog_warning": model_catalog_warning,
    }


def _admin_nav_counts():
    return {
        "admin_google_accounts_count": GoogleAccountConfig.query.count(),
        "admin_users_count": User.query.count(),
    }


@admin_bp.route('/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_project():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        domain = request.form.get('domain', '').strip()
        location = request.form.get('location', '').strip()
        competitor_traffic_locations = request.form.getlist('competitor_traffic_locations')
        business_context = request.form.get('business_context', '').strip()
        ga4_property_id = request.form.get('ga4_property_id', '').strip()
        gsc_site_url = request.form.get('gsc_site_url', '').strip()
        google_account_id = request.form.get('google_account_id') or None
        keywords_input = request.form.get('keywords', '')
        competitors_input = request.form.get('competitors', '')
        crawl_mode = request.form.get('crawl_mode', 'full')
        crawl_paths = request.form.get('crawl_paths', '')
        ai_model_override = request.form.get('ai_model_override', '').strip()
        ai_prompt_override = request.form.get('ai_prompt_override', '').strip()

        if not name or not domain:
            flash("Project name and domain are required.", "error")
            return redirect(url_for('admin.add_project'))

        try:
            domain = normalize_site_url(domain)
            location = normalize_google_location(location)
            competitor_traffic_locations = normalize_competitor_traffic_locations(
                competitor_traffic_locations,
                location,
            )
            competitor_traffic_locations = [market for market in competitor_traffic_locations if market != location]
            competitors = [
                normalize_site_url(item)
                for item in competitors_input.split(',')
                if item.strip()
            ]
            kws = parse_keywords_input(keywords_input, location) if keywords_input.strip() else []
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for('admin.add_project'))

        try:
            _validate_changed_model(ai_model_override, None)
        except AIModelValidationError as exc:
            flash(f"AI model override was not saved: {exc}", "error")
            return redirect(url_for('admin.add_project'))

        new_client = Client( # type: ignore
            name=name,
            domain=domain,
            location=location,
            competitor_traffic_locations=competitor_traffic_locations,
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
        if kws:
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
        if competitors:
            for comp in competitors:
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
        global_setting=global_setting,
        google_accounts=get_available_google_accounts(),
        default_google_account=get_default_google_account(),
        keyword_rows=[],
        competitor_rows=[],
        dataforseo_locations=GOOGLE_LOCATIONS,
        keyword_language_options=keyword_language_options(),
        **_model_selection_context(global_setting.model_name),
    )

@admin_bp.route('/project/<int:client_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_project(client_id):
    client = Client.query.get_or_404(client_id)
    project_ai_setting = ProjectAISetting.query.filter_by(client_id=client.id).first()
    
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        raw_domain = request.form.get('domain', '').strip()
        location = request.form.get('location', '').strip()
        competitor_traffic_locations = request.form.getlist('competitor_traffic_locations')
        business_context = request.form.get('business_context', '').strip()
        google_account_id = request.form.get('google_account_id') or None
        ga4_property_id = request.form.get('ga4_property_id', '').strip()
        gsc_site_url = request.form.get('gsc_site_url', '').strip()
        crawl_mode = request.form.get('crawl_mode', 'full')
        crawl_paths = request.form.get('crawl_paths', '')
        ai_model_override = request.form.get('ai_model_override', '').strip()
        ai_prompt_override = request.form.get('ai_prompt_override', '').strip()
        
        keywords_input = request.form.get('keywords', '')
        competitors_input = request.form.get('competitors', '')

        if not name or not raw_domain:
            flash("Project name and domain are required.", "error")
            return redirect(url_for('admin.edit_project', client_id=client.id))

        try:
            domain = normalize_site_url(raw_domain)
            location = normalize_google_location(location)
            competitor_traffic_locations = normalize_competitor_traffic_locations(
                competitor_traffic_locations,
                location,
            )
            competitor_traffic_locations = [market for market in competitor_traffic_locations if market != location]
            competitors = [
                normalize_site_url(item)
                for item in competitors_input.split(',')
                if item.strip()
            ]
            kws = parse_keywords_input(keywords_input, location) if keywords_input.strip() else []
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for('admin.edit_project', client_id=client.id))
        
        try:
            _validate_changed_model(ai_model_override, project_ai_setting.model_name if project_ai_setting else None)
        except AIModelValidationError as exc:
            flash(f"AI model override was not saved: {exc}", "error")
            return redirect(url_for('admin.edit_project', client_id=client.id))

        client.name = name
        client.domain = domain
        client.location = location
        client.competitor_traffic_locations = competitor_traffic_locations
        client.business_context = business_context
        client.google_account_id = int(google_account_id) if google_account_id else None
        client.ga4_property_id = ga4_property_id
        client.gsc_site_url = gsc_site_url
        client.crawl_mode = crawl_mode
        client.crawl_paths = crawl_paths

        # Update Keywords (delete old, add new)
        Keyword.query.filter_by(client_id=client.id).delete()
        if kws:
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
        if competitors:
            for comp in competitors:
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
        try:
            full_audit_schedule_enabled = request.form.get('full_audit_schedule_enabled') == 'on'
            rank_check_schedule_enabled = request.form.get('rank_check_schedule_enabled') == 'on'
            existing_schedules = {
                schedule.run_type: schedule
                for schedule in AuditSchedule.query.filter_by(client_id=client.id).all()
            }
            for run_type, enabled, frequency, timezone_name, run_at_local in (
                (
                    'full_audit',
                    full_audit_schedule_enabled,
                    request.form.get('full_audit_schedule_frequency', 'weekly'),
                    request.form.get('full_audit_schedule_timezone') or 'Asia/Kolkata',
                    request.form.get('full_audit_schedule_time') or '02:00',
                ),
                (
                    'rank_check',
                    rank_check_schedule_enabled,
                    request.form.get('rank_check_schedule_frequency', 'weekly'),
                    request.form.get('rank_check_schedule_timezone') or 'Asia/Kolkata',
                    request.form.get('rank_check_schedule_time') or '02:00',
                ),
            ):
                if enabled:
                    upsert_schedule(
                        client,
                        enabled=True,
                        frequency=frequency,
                        run_type=run_type,
                        timezone_name=timezone_name,
                        run_at_local=run_at_local,
                    )
                elif existing_schedule := existing_schedules.get(run_type):
                    existing_schedule.enabled = False
                    existing_schedule.next_run_at = None
                    db.session.commit()
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return redirect(url_for('admin.edit_project', client_id=client.id))
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
    audit_schedules = {
        schedule.run_type: schedule
        for schedule in AuditSchedule.query.filter_by(client_id=client.id).all()
    }
    return render_template(
        'edit_project.html',
        client=client,
        keywords_str=keywords_str,
        competitors_str=competitors_str,
        keyword_rows=keyword_rows,
        competitor_rows=competitor_rows,
        global_setting=global_setting,
        project_ai_setting=project_ai_setting,
        audit_schedules=audit_schedules,
        schedule_timezones=SCHEDULE_TIMEZONES,
        google_accounts=get_available_google_accounts(),
        default_google_account=get_default_google_account(),
        dataforseo_locations=GOOGLE_LOCATIONS,
        keyword_language_options=keyword_language_options(),
        **_model_selection_context(global_setting.model_name, project_ai_setting.model_name if project_ai_setting else None),
    )

@admin_bp.route('/project/<int:client_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_project(client_id):
    client = Client.query.get_or_404(client_id)

    # Clear many-to-many user assignments before removing the project.
    client.users = []

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
        requested_model = request.form.get('model_name', '').strip()
        if not requested_model:
            flash("Choose a verified OpenRouter model before saving the global AI settings.", "error")
            return redirect(url_for('admin.settings'))
        try:
            _validate_changed_model(requested_model, setting.model_name)
        except AIModelValidationError as exc:
            flash(f"AI model was not changed: {exc}", "error")
            return redirect(url_for('admin.settings'))
        setting.model_name = requested_model
        setting.system_prompt = request.form.get('system_prompt')
        db.session.commit()
        flash("AI Settings updated successfully!", "success")
        return redirect(url_for('admin.settings'))

    return render_template(
        'settings.html',
        setting=setting,
        **_model_selection_context(setting.model_name),
        **_admin_nav_counts(),
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
        **_admin_nav_counts(),
    )


@admin_bp.route('/users')
@login_required
@admin_required
def users():
    all_users = User.query.order_by(User.id.asc()).all()
    all_clients = Client.query.order_by(Client.name.asc()).all()
    return render_template('users.html', users=all_users, all_clients=all_clients, **_admin_nav_counts())

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
    all_clients = Client.query.order_by(Client.name.asc()).all()
    
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
        
    return render_template('assign_project.html', target_user=user, all_clients=all_clients, **_admin_nav_counts())
