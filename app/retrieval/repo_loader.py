"""Repository loader for Ragna.

Scans a local repository and returns structured file metadata and content
for supported code files.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)


SUPPORTED_EXTENSIONS: Dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".java": "java",
    ".cpp": "cpp",
    ".c": "c",
    ".go": "go",
}

DEFAULT_IGNORED_DIRS = {
    "node_modules",
    "venv",
    ".git",
    "__pycache__",
    "build",
    "dist",
}


def load_repository(repo_path: str) -> List[Dict[str, str]]:
    """Load and scan a local repository.

    Args:
        repo_path: Path to the local repository.

    Returns:
        A list of dictionaries with file metadata and full content.
    """
    root = Path(repo_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Repository path does not exist or is not a directory: {root}")

    logger.info("Scanning repository: %s", root)
    results: List[Dict[str, str]] = []

    for file_path in _iter_code_files(root):
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except (OSError, PermissionError) as exc:
            logger.warning("Skipping unreadable file %s: %s", file_path, exc)
            continue

        ext = file_path.suffix.lower()
        results.append(
            {
                "file_path": str(file_path),
                "file_name": file_path.name,
                "extension": ext,
                "language": SUPPORTED_EXTENSIONS.get(ext, "unknown"),
                "content": content,
            }
        )

    logger.info("Loaded %d files", len(results))
    return results


def _iter_code_files(root: Path):
    """Yield supported code files under root, skipping ignored directories."""
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        current_dir = Path(dirpath)

        if _is_hidden_or_system(current_dir) or current_dir.name in DEFAULT_IGNORED_DIRS:
            logger.debug("Skipping directory: %s", current_dir)
            dirnames[:] = []
            continue

        dirnames[:] = [
            d
            for d in dirnames
            if d not in DEFAULT_IGNORED_DIRS and not _is_hidden_or_system(Path(dirpath, d))
        ]

        for filename in filenames:
            path = Path(dirpath, filename)
            try:
                if _is_hidden_or_system(path) or _is_ignored(path):
                    logger.debug("Skipping path: %s", path)
                    continue

                if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                    yield path
            except (OSError, PermissionError) as exc:
                logger.warning("Skipping inaccessible path %s: %s", path, exc)
                continue


def _is_ignored(path: Path) -> bool:
    """Return True if a path is under an ignored directory."""
    return any(part in DEFAULT_IGNORED_DIRS for part in path.parts)


def _is_hidden_or_system(path: Path) -> bool:
    """Return True if path is hidden/system (best-effort, cross-platform)."""
    name = path.name
    if name.startswith("."):
        return True
    try:
        return path.is_symlink()
    except (OSError, PermissionError):
        return True
