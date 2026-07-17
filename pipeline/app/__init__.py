from flask import Flask
from flask_login import LoginManager
from sqlalchemy import inspect
from sqlalchemy import text
import config
from app.models import Client, GoogleAccountConfig, ProjectAISetting, db, User
from services.google_accounts import ensure_google_accounts_dir

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message_category = 'info'

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = config.SECRET_KEY
    app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

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
        inspector = inspect(db.engine)
        if not inspector.has_table(ProjectAISetting.__tablename__):
            ProjectAISetting.__table__.create(db.engine)
        if not inspector.has_table(GoogleAccountConfig.__tablename__):
            GoogleAccountConfig.__table__.create(db.engine)
            inspector = inspect(db.engine)

        client_columns = {column["name"] for column in inspector.get_columns(Client.__tablename__)}
        if "google_account_id" not in client_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE clients ADD COLUMN google_account_id INTEGER"))

        account_columns = {column["name"] for column in inspector.get_columns(GoogleAccountConfig.__tablename__)}
        if "stored_filename" not in account_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE google_account_configs ADD COLUMN stored_filename VARCHAR(255)"))

        ensure_google_accounts_dir()

    return app
