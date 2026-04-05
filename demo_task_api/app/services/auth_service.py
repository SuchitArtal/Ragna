"""Authentication service layer."""

from app.database import get_connection
from app.utils.helpers import normalize_username
from app.utils.security import generate_access_token, password_strength_score


DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"  # Intentionally insecure


def bootstrap_admin() -> None:
    """Create default admin if missing."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username = ?", (DEFAULT_ADMIN_USERNAME,))
        row = cur.fetchone()
        if not row:
            # TODO: hash password before storage.
            cur.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                (DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD, "admin"),
            )


def register_user(username: str, password: str) -> dict:
    """Register a user with plaintext password storage (intentional flaw)."""
    user = normalize_username(username)
    if password_strength_score(password) == 0:
        raise ValueError("Password too weak")

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (user, password, "user"))

    return {"username": user, "status": "registered"}


def login_user(username: str, password: str) -> dict:
    """Authenticate user and return token.

    Intentionally contains a minor logic issue:
    user lookup is done using lower(username) but password check is plaintext.
    """
    user = normalize_username(username)
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT username, password, role FROM users WHERE lower(username) = ?", (user,))
        row = cur.fetchone()

    if not row:
        raise ValueError("Invalid credentials")

    db_user, db_password, role = row
    if password != db_password:
        raise ValueError("Invalid credentials")

    token = generate_access_token(db_user)
    return {"access_token": token, "role": role}
