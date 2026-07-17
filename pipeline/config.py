import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")

# Load variables from pipeline/.env deterministically.
load_dotenv(ENV_PATH)


def _env(name, default=""):
    value = os.environ.get(name)
    return value if value not in (None, "") else default


# OpenRouter - model is swappable; she can change OPENROUTER_MODEL anytime
OPENROUTER_API_KEY = _env("OPENROUTER_API_KEY")
OPENROUTER_MODEL = _env("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DFS_LOGIN = _env("DFS_LOGIN")
DFS_PASS = _env("DFS_PASS")
SECRET_KEY = _env("SECRET_KEY", "dev-secret-change-me")
APP_ENV = _env("APP_ENV", "development")
SQLALCHEMY_DATABASE_URI = _env("SQLALCHEMY_DATABASE_URI", "sqlite:///seo_agent.db")

if APP_ENV in {"production", "staging"}:
    if not os.environ.get("SQLALCHEMY_DATABASE_URI"):
        raise RuntimeError("SQLALCHEMY_DATABASE_URI must be set in production/staging.")
    if SECRET_KEY == "dev-secret-change-me":
        raise RuntimeError("SECRET_KEY must be set to a non-default value in production/staging.")
