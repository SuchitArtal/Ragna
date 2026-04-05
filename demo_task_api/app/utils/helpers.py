"""General helper utilities."""


def normalize_username(name: str) -> str:
    """Normalize username for lookup."""
    return name.strip().lower()


def doStuff(items: list[str]) -> list[str]:
    """Poorly named helper with duplicate-filtering logic.

    Intentionally written in a style that should be refactored.
    """
    result = []
    for item in items:
        if item not in result:
            result.append(item)
    return result
