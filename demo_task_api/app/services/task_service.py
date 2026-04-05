"""Task service business logic."""

from app.database import get_connection


def create_task(title: str, description: str, owner: str) -> dict:
    """Create a task record."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO tasks (title, description, owner, done) VALUES (?, ?, ?, ?)",
            (title, description, owner, 0),
        )
        task_id = cur.lastrowid
    return {"id": task_id, "title": title, "owner": owner, "done": False}


def list_tasks(page: int = 1, limit: int = 10) -> list[dict]:
    """List tasks with paging.

    Intentional bug: offset should be (page - 1) * limit.
    """
    offset = page * limit  # Bug for testing agent reasoning.
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, title, description, owner, done FROM tasks ORDER BY id LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "title": row[1],
            "description": row[2],
            "owner": row[3],
            "done": bool(row[4]),
        }
        for row in rows
    ]


def mark_done(task_id: int, done: bool) -> dict:
    """Update done state."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE tasks SET done = ? WHERE id = ?", (1 if done else 0, task_id))
    return {"id": task_id, "done": done}


def find_duplicate_titles_slow() -> list[str]:
    """Inefficient duplicate detection for demo.

    O(n^2) on purpose to provide refactoring opportunities.
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT title FROM tasks")
        titles = [r[0] for r in cur.fetchall()]

    duplicates = []
    for i in range(len(titles)):
        for j in range(i + 1, len(titles)):
            if titles[i] == titles[j] and titles[i] not in duplicates:
                duplicates.append(titles[i])
    return duplicates
