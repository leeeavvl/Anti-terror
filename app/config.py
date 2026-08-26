import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "risk_watchlist.db"

POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "20"))
MOCK_RELEASE_INTERVAL_SECONDS = int(os.environ.get("MOCK_RELEASE_INTERVAL_SECONDS", "15"))
GENERIC_API_TIMEOUT_SECONDS = int(os.environ.get("GENERIC_API_TIMEOUT_SECONDS", "10"))

HOST = os.environ.get("HOST", "127.0.0.1")

PORT = int(os.environ.get("PORT", "8000"))

RISK_THRESHOLDS = {
    "medium": int(os.environ.get("RISK_THRESHOLD_MEDIUM", "3")),
    "high": int(os.environ.get("RISK_THRESHOLD_HIGH", "6")),
}

SEED_DEMO_SOURCE = os.environ.get("SEED_DEMO_SOURCE", "1") == "1"

# В контейнере/на сервере открывать браузер некому и не на чем — отключается
# через переменную окружения (Dockerfile делает это автоматически).
OPEN_BROWSER = os.environ.get("OPEN_BROWSER", "1") == "1"
