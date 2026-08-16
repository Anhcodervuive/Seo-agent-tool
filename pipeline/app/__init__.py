from flask import Flask
from flask_login import LoginManager
from datetime import timedelta, timezone
import config
from app.models import db, User
from services.google_accounts import ensure_google_accounts_dir

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'info'

# IST is permanently UTC+05:30 and does not observe daylight saving time.
# A fixed offset avoids depending on an operating system timezone database,
# which is often unavailable in local Windows Python installations.
INDIA_STANDARD_TIME = timezone(timedelta(hours=5, minutes=30), name='IST')


def format_ist_datetime(value):
    """Render stored UTC timestamps consistently for the product UI."""
    if not value:
        return 'N/A'
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(INDIA_STANDARD_TIME).strftime('%d %b %Y, %I:%M %p IST')


def format_schedule_datetime(value, timezone_name):
    """Render a schedule timestamp in its own configured IANA timezone."""
    if not value:
        return 'N/A'
    try:
        from zoneinfo import ZoneInfo
        target_timezone = ZoneInfo(timezone_name)
    except Exception:
        target_timezone = INDIA_STANDARD_TIME
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(target_timezone).strftime('%d %b %Y, %I:%M %p %Z')

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = config.SECRET_KEY
    app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.add_template_filter(format_ist_datetime, 'ist_datetime')
    app.add_template_filter(format_schedule_datetime, 'schedule_datetime')

    db.init_app(app)
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Register Blueprints
    from app.routes.auth import auth_bp
    from app.routes.main import main_bp
    from app.routes.admin import admin_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)

    with app.app_context():
        ensure_google_accounts_dir()

    return app
