"""Path validation for guardrail file operations."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)


class FileValidator:
    """Validate file paths for safety and repository boundaries."""

    PROTECTED_PATTERNS = {
        ".env",
        "requirements.txt",
        "pyproject.toml",
        "config/settings.py",
    }

    def validate_file_path(self, repo_root: str, file_path: str, *, allow_protected: bool = False) -> Dict[str, object]:
        """Validate an agent-proposed file path.

        Args:
            repo_root: Absolute path to the repository root.
            file_path: Proposed relative file path.

        Returns:
            Dictionary describing path safety and existence.
        """
        error = None

        try:
            root = Path(repo_root).expanduser().resolve()
            candidate = Path(file_path)

            if candidate.is_absolute():
                error = "absolute paths are not allowed"
                logger.warning("Rejected absolute path: %s", file_path)
                return self._result(False, False, False, "", error)

            if any(part in ("..", "~") for part in candidate.parts):
                error = "path traversal is not allowed"
                logger.warning("Rejected traversal path: %s", file_path)
                return self._result(False, False, False, "", error)

            full_path = (root / candidate).resolve()

            within_repo = self._is_within_repo(root, full_path)
            is_safe_path = within_repo and not self._is_hidden_or_system(full_path)
            exists = full_path.exists()
            rel_path = self._relative_path(root, full_path)
            is_protected = self._is_protected_path(rel_path)

            if not within_repo:
                error = "path escapes repository root"
                logger.warning("Rejected path outside repo: %s", full_path)
            elif not is_safe_path:
                error = "hidden or system path is not allowed"
                logger.warning("Rejected hidden/system path: %s", full_path)
            elif is_protected and not allow_protected:
                error = "protected file requires explicit permission"
                logger.warning("Rejected protected path edit: %s", full_path)
            elif not exists:
                error = "file does not exist"
                logger.warning("Target file does not exist: %s", full_path)

            result = self._result(exists, within_repo, is_safe_path, str(full_path), error)
            result["is_protected"] = is_protected
            result["relative_path"] = rel_path
            return result
        except OSError as exc:
            logger.warning("Failed to validate path %s: %s", file_path, exc)
            return self._result(False, False, False, "", str(exc))

    def _is_within_repo(self, root: Path, full_path: Path) -> bool:
        try:
            full_path.relative_to(root)
            return True
        except ValueError:
            return False

    def _is_hidden_or_system(self, path: Path) -> bool:
        name = path.name
        if name.startswith("."):
            return True
        try:
            return path.is_symlink()
        except OSError:
            return True

    def _relative_path(self, root: Path, full_path: Path) -> str:
        try:
            return str(full_path.relative_to(root)).replace("\\", "/")
        except ValueError:
            return str(full_path).replace("\\", "/")

    def _is_protected_path(self, rel_path: str) -> bool:
        cleaned = (rel_path or "").lstrip("./").lower()
        if cleaned in self.PROTECTED_PATTERNS:
            return True
        return cleaned.startswith(".git/") or cleaned.startswith(".github/")

    def _result(
        self,
        exists: bool,
        within_repo: bool,
        is_safe_path: bool,
        full_path: str,
        error: str | None,
    ) -> Dict[str, object]:
        return {
            "exists": exists,
            "within_repo": within_repo,
            "is_safe_path": is_safe_path,
            "full_path": full_path,
            "error": error,
        }
