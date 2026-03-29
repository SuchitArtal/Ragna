"""In-memory patch application utilities for sandbox execution."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

HUNK_HEADER_RE = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")


class PatchApplyError(ValueError):
    """Raised when a unified diff patch cannot be applied."""


@dataclass
class Hunk:
    """Parsed unified-diff hunk."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: List[str]


class PatchApplier:
    """Apply unified diff patches to file content in memory.

    This class is intentionally disk-free for safety. It is designed to be used
    by sandbox orchestration code after guardrail validation succeeds.
    """

    def __init__(self) -> None:
        """Initialize the in-memory patch applier."""
        logger.debug("PatchApplier initialized")

    def apply_patch(self, original_code: str, patch_text: str) -> str:
        """Apply a unified diff patch to a single file in memory.

        Args:
            original_code: Original file content.
            patch_text: Unified diff patch string.

        Returns:
            Patched file content.

        Raises:
            PatchApplyError: If patch format is invalid or cannot be applied.
        """
        logger.info("Applying unified diff patch in memory")

        original_lines = original_code.splitlines()
        trailing_newline = original_code.endswith("\n")
        hunks = self._parse_hunks(patch_text)
        if not hunks:
            raise PatchApplyError("No valid hunks found in patch")

        patched_lines: List[str] = []
        cursor = 0

        for hunk in hunks:
            start_index = max(hunk.old_start - 1, 0)

            if start_index < cursor:
                raise PatchApplyError("Overlapping or out-of-order hunks")

            patched_lines.extend(original_lines[cursor:start_index])
            cursor = start_index

            for line in hunk.lines:
                if not line:
                    symbol = " "
                    content = ""
                else:
                    symbol = line[0]
                    content = line[1:]

                if symbol == " ":
                    self._expect_line(original_lines, cursor, content, "context")
                    patched_lines.append(content)
                    cursor += 1
                elif symbol == "-":
                    self._expect_line(original_lines, cursor, content, "removal")
                    cursor += 1
                elif symbol == "+":
                    patched_lines.append(content)
                elif line.startswith("\\ No newline at end of file"):
                    # Informational marker from diff tools; no direct content change.
                    continue
                else:
                    raise PatchApplyError(f"Unsupported patch line in hunk: {line}")

        patched_lines.extend(original_lines[cursor:])
        result = "\n".join(patched_lines)
        if trailing_newline:
            result += "\n"

        logger.info("Patch applied successfully")
        return result

    def apply_patch_in_memory(self, original_content: str, unified_diff: str) -> Dict[str, object]:
        """Apply a unified diff patch to content in memory.

        Args:
            original_content: Original file content.
            unified_diff: Patch text in unified diff format.

        Returns:
            Structured result containing success state and patched content.
        """
        logger.info("Applying patch in memory")
        try:
            patched = self.apply_patch(original_content, unified_diff)
            return {
                "applied": True,
                "patched_content": patched,
                "errors": [],
                "warnings": [],
            }
        except PatchApplyError as exc:
            logger.warning("Patch apply failed: %s", exc)
            return {
                "applied": False,
                "patched_content": original_content,
                "errors": [str(exc)],
                "warnings": [],
            }

    def dry_run_patch(self, original_content: str, unified_diff: str) -> Dict[str, object]:
        """Validate whether a patch can be applied without mutating state.

        Args:
            original_content: Original file content.
            unified_diff: Patch text in unified diff format.

        Returns:
            Dry-run result with validation status.
        """
        logger.info("Running in-memory patch dry-run")
        try:
            self.apply_patch(original_content, unified_diff)
            return {
                "can_apply": True,
                "errors": [],
                "warnings": [],
            }
        except PatchApplyError as exc:
            return {
                "can_apply": False,
                "errors": [str(exc)],
                "warnings": [],
            }

    def _parse_hunks(self, patch_text: str) -> List[Hunk]:
        """Extract hunk definitions from unified diff text."""
        lines = (patch_text or "").splitlines()
        hunks: List[Hunk] = []
        i = 0

        while i < len(lines):
            line = lines[i]
            if not line.startswith("@@"):
                i += 1
                continue

            old_start, old_count, new_start, new_count = self._parse_hunk_header(line)
            i += 1
            hunk_lines: List[str] = []

            while i < len(lines) and not lines[i].startswith("@@"):
                current = lines[i]
                if current.startswith("--- ") or current.startswith("+++ "):
                    # Metadata lines should not appear inside hunks.
                    i += 1
                    continue
                hunk_lines.append(current)
                i += 1

            hunks.append(
                Hunk(
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    lines=hunk_lines,
                )
            )

        return hunks

    def _parse_hunk_header(self, header: str) -> Tuple[int, int, int, int]:
        """Parse unified diff hunk header values."""
        match = HUNK_HEADER_RE.match(header)
        if not match:
            raise PatchApplyError(f"Malformed hunk header: {header}")

        old_start = int(match.group(1))
        old_count = int(match.group(2) or 1)
        new_start = int(match.group(3))
        new_count = int(match.group(4) or 1)
        return old_start, old_count, new_start, new_count

    def _expect_line(self, original_lines: List[str], idx: int, expected: str, kind: str) -> None:
        """Validate that expected line matches source content during apply."""
        if idx >= len(original_lines):
            raise PatchApplyError(f"{kind} line out of range while applying patch")
        actual = original_lines[idx]
        if actual != expected:
            raise PatchApplyError(
                f"{kind} mismatch at source line {idx + 1}: expected {expected!r}, got {actual!r}"
            )
