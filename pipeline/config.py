import os
from dotenv import load_dotenv

# Load variables from .env if it exists
load_dotenv()

# OpenRouter — model is swappable; she can change OPENROUTER_MODEL anytime
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
SQLALCHEMY_DATABASE_URI = os.environ.get("SQLALCHEMY_DATABASE_URI", "sqlite:///seo_agent.db")
