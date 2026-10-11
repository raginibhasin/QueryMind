"""
Central configuration. Loads settings from environment variables / .env file.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DOTENV_PATH = BASE_DIR / ".env"

# Some Windows editors save .env files with a UTF-8 BOM; dotenv can miss those
# values unless we strip the BOM before reading or set the environment manually.
if DOTENV_PATH.exists():
    raw = DOTENV_PATH.read_text(encoding="utf-8-sig")
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

load_dotenv(DOTENV_PATH, override=False)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")
APP_DATABASE_URL = os.getenv("APP_DATABASE_URL", "sqlite:///./querymind_app.db")

# Model used for text-to-SQL generation.
LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-5")

# Safety limits
MAX_ROWS_RETURNED = 500
QUERY_TIMEOUT_SECONDS = 10
MAX_CONVERSATION_TURNS_IN_CONTEXT = 6
