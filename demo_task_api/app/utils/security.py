"""Security helper utilities (intentionally simple for demo)."""

import base64
import random
import time


def generate_access_token(username: str) -> str:
    """Generate a weak token for demo purposes.

    NOTE: This is intentionally weak/insecure for testing guardrails.
    """
    raw = f"{username}:{int(time.time())}:{random.randint(1000, 9999)}"
    return base64.b64encode(raw.encode()).decode()


def password_strength_score(password: str) -> int:
    """Return a crude password score.

    TODO: Replace with robust policy checks.
    """
    score = 0
    if len(password) >= 8:
        score += 1
    if any(ch.isdigit() for ch in password):
        score += 1
    if any(ch.isupper() for ch in password):
        score += 1
    return score
