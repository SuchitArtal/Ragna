"""Basic task service tests."""

from app.services.task_service import list_tasks


def test_list_tasks_returns_list() -> None:
    """Task listing should return list."""
    result = list_tasks(page=1, limit=5)
    assert isinstance(result, list)
