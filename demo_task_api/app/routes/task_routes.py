"""Task API routes."""

from fastapi import APIRouter

from app.models import TaskCreate
from app.services.task_service import create_task, find_duplicate_titles_slow, list_tasks, mark_done

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("")
def add_task(payload: TaskCreate) -> dict:
    """Create task endpoint."""
    return create_task(payload.title, payload.description, payload.owner)


@router.get("")
def get_tasks(page: int = 1, limit: int = 10) -> list[dict]:
    """List tasks endpoint."""
    return list_tasks(page=page, limit=limit)


@router.patch("/{task_id}/done")
def set_done(task_id: int, done: bool) -> dict:
    """Mark done endpoint."""
    return mark_done(task_id, done)


@router.get("/duplicates")
def duplicates() -> dict:
    """Return duplicate task titles."""
    return {"duplicates": find_duplicate_titles_slow()}
