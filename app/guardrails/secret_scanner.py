"""Secret detection for patch validation."""

from __future__ import annotations

import logging
import re
from typing import Dict, List

logger = logging.getLogger(__name__)


class SecretScanner:
    """Scan code patches for potential secrets."""

    # Regex patterns for common secrets
    PATTERNS = {
        "aws_access_key": re.compile(r"AKIA[0-9A-Z]{16}", re.IGNORECASE),
        "aws_secret_key": re.compile(r"['\"]([A-Za-z0-9/+=]{40})['\"]"),
        "generic_api_key": re.compile(
            r"(?i)(api[_-]?key|apikey|api_key)\s*[=:]\s*['\"]?([a-zA-Z0-9_\-]{6,})['\"]?"
        ),
        "bearer_token": re.compile(
            r"(?i)bearer\s+[A-Za-z0-9\-\._~\+\/]+=*"
        ),
        "password_assignment": re.compile(
            r"(?i)(password|passwd|pwd)\s*[=:]\s*['\"]?([^'\";\s]{4,})['\"]?"
        ),
        "generic_token": re.compile(
            r"(?i)(token|auth[_-]?token)\s*[=:]\s*['\"]?([a-zA-Z0-9_\-\.]{20,})['\"]?"
        ),
        "secret_key": re.compile(
            r"(?i)(secret[_-]?key|secret)\s*[=:]\s*['\"]?([a-zA-Z0-9_\-]{16,})['\"]?"
        ),
        "private_key": re.compile(r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----", re.IGNORECASE),
        "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,}", re.IGNORECASE),
        "slack_token": re.compile(r"xox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24,}", re.IGNORECASE),
        "jwt_token": re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    }

    def scan_patch_for_secrets(self, added_lines: List[str]) -> Dict[str, object]:
        """Scan added patch lines for potential secrets.

        Args:
            added_lines: List of lines being added (starting with +).

        Returns:
            Detection result with secret matches.
        """
        matches: List[Dict[str, str]] = []

        for line in added_lines:
            clean_line = line.lstrip("+").strip()
            
            if not clean_line or self._is_comment_or_test(clean_line):
                continue

            for secret_type, pattern in self.PATTERNS.items():
                if pattern.search(clean_line):
                    matches.append({"type": secret_type, "line": clean_line})
                    logger.warning("Detected potential %s in line: %s", secret_type, clean_line[:50])

        has_secrets = len(matches) > 0

        if has_secrets:
            logger.warning("Found %d potential secret(s) in patch", len(matches))

        return {
            "has_secrets": has_secrets,
            "matches": matches,
        }

    def _is_comment_or_test(self, line: str) -> bool:
        """Check if line is a comment or test fixture (heuristic)."""
        if line.startswith("#") or line.startswith("//"):
            return True
        # Only filter if it's clearly a placeholder or comment context
        lower_line = line.lower()
        if any(phrase in lower_line for phrase in ["your_api_key", "your_token", "placeholder", "xxx", "fake_"]):
            return True
        return False
