import os

from app.models import Client, GoogleAccountConfig

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CREDENTIALS_PATH = os.path.join(os.path.dirname(BASE_DIR), "credentials", "google-service-account.json")
GOOGLE_ACCOUNTS_DIR = os.path.join(BASE_DIR, "secure", "google_accounts")


def get_default_google_account():
    return GoogleAccountConfig.query.filter_by(is_default=True).order_by(GoogleAccountConfig.id.asc()).first()


def get_available_google_accounts():
    return GoogleAccountConfig.query.filter_by(active=True).order_by(
        GoogleAccountConfig.is_default.desc(),
        GoogleAccountConfig.name.asc(),
    ).all()


def get_google_account_for_client(client: Client):
    if client.google_account_id:
        account = GoogleAccountConfig.query.get(client.google_account_id)
        if account and account.active:
            return account
    return get_default_google_account()


def get_credentials_path_for_client(client: Client):
    account = get_google_account_for_client(client)
    if account:
        if account.stored_filename:
            return os.path.join(GOOGLE_ACCOUNTS_DIR, account.stored_filename)
        if account.credentials_path:
            return account.credentials_path
    return DEFAULT_CREDENTIALS_PATH


def ensure_google_accounts_dir():
    os.makedirs(GOOGLE_ACCOUNTS_DIR, exist_ok=True)
