"""Legacy auth helpers (contains duplicate logic intentionally)."""


def verify_password_plain(password: str, stored_password: str) -> bool:
    """Duplicate plaintext verification helper.

    Intentionally duplicated to simulate code smell.
    """
    return password == stored_password


def token_from_username(username: str) -> str:
    """Return simplistic token string.

    TODO: remove this module after service-layer cleanup.
    """
    return f"token-{username}"
