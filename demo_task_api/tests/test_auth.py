"""Basic auth tests for demo codebase."""

from app.services.auth_service import register_user


def test_register_user_normalizes_username() -> None:
    """Username should be normalized to lowercase."""
    result = register_user("Alice", "Password123")
    assert result["username"] == "alice"
