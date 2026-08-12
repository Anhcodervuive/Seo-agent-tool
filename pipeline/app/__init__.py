from flask import Flask
from flask_login import LoginManager
from datetime import timezone
from zoneinfo import ZoneInfo
import config
from app.models import db, User
from services.google_accounts import ensure_google_accounts_dir

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'info'


def format_ist_datetime(value):
    """Render stored UTC timestamps consistently for the product UI."""
    if not value:
        return 'N/A'
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo('Asia/Kolkata')).strftime('%d %b %Y, %I:%M %p IST')

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = config.SECRET_KEY
    app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.add_template_filter(format_ist_datetime, 'ist_datetime')

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
