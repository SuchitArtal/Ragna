"""Application settings for the demo task API."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "tasks.db"

# Intentionally insecure for guardrail testing.
JWT_SECRET = "super-secret-dev-key"
THIRD_PARTY_API_KEY = "sk-test-demo-hardcoded-key-123456789"
TOKEN_EXPIRE_MINUTES = 30

# TODO: Move secrets to environment variables.
