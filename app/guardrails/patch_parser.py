"""Unified diff patch parser for guardrail validation."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List

logger = logging.getLogger(__name__)


@dataclass
class Hunk:
	"""Represents a parsed unified diff hunk."""

	header: str
	added_lines: List[str] = field(default_factory=list)
	removed_lines: List[str] = field(default_factory=list)


class PatchParser:
	"""Parse and validate unified diff patches."""

	def parse_patch(self, patch_text: str, file_path: str) -> Dict[str, object]:
		"""Parse a unified diff patch into structured metadata.

		Args:
			patch_text: Unified diff text.
			file_path: Target file path from the proposal.

		Returns:
			Structured parsing result with hunks and counts.
		"""
		raw_patch = patch_text or ""
		lines = raw_patch.strip("\n").splitlines()

		if not lines:
			logger.warning("Empty patch text for %s", file_path)
			return self._invalid_result(file_path, raw_patch)

		try:
			header_index = self._find_header_index(lines)
			if header_index < 0 or header_index + 1 >= len(lines):
				logger.warning("Missing unified diff headers for %s", file_path)
				return self._invalid_result(file_path, raw_patch)

			if not lines[header_index].startswith("--- ") or not lines[header_index + 1].startswith("+++ "):
				logger.warning("Malformed unified diff headers for %s", file_path)
				return self._invalid_result(file_path, raw_patch)

			hunks = self._extract_hunks(lines[header_index + 2 :])
			if not hunks:
				logger.warning("No hunks found in patch for %s", file_path)
				return self._invalid_result(file_path, raw_patch)

			added_line_count = sum(len(h.added_lines) for h in hunks)
			removed_line_count = sum(len(h.removed_lines) for h in hunks)

			return {
				"file_path": file_path,
				"is_valid_format": True,
				"hunks": [h.__dict__ for h in hunks],
				"added_line_count": added_line_count,
				"removed_line_count": removed_line_count,
				"raw_patch": raw_patch,
			}
		except ValueError as exc:
			logger.warning("Invalid patch for %s: %s", file_path, exc)
			return self._invalid_result(file_path, raw_patch)

	def _find_header_index(self, lines: List[str]) -> int:
		for idx, line in enumerate(lines):
			if line.startswith("--- "):
				return idx
		return -1

	def _extract_hunks(self, lines: List[str]) -> List[Hunk]:
		hunks: List[Hunk] = []
		current: Hunk | None = None

		for line in lines:
			if line.startswith("@@"):
				if current:
					hunks.append(current)
				current = Hunk(header=line)
				continue

			if current is None:
				continue

			if line.startswith("+") and not line.startswith("+++"):
				current.added_lines.append(line)
			elif line.startswith("-") and not line.startswith("---"):
				current.removed_lines.append(line)

		if current:
			hunks.append(current)

		return hunks

	def _invalid_result(self, file_path: str, raw_patch: str) -> Dict[str, object]:
		return {
			"file_path": file_path,
			"is_valid_format": False,
			"hunks": [],
			"added_line_count": 0,
			"removed_line_count": 0,
			"raw_patch": raw_patch,
		}


__all__ = ["PatchParser"]
