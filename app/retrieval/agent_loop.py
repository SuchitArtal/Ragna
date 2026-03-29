"""Deterministic agent loop for Phase 2 tasks.

This module implements a lightweight, deterministic agent loop that uses
local filesystem tools to search and read files, analyze simple dependencies,
and produce structured edit proposals (without applying them).

The loop logs every step, enforces a maximum number of steps and recursion
depth, and returns a structured JSON edit proposal when it decides an edit is
needed.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class EditProposal:
    file_path: str
    modification_description: str
    edits: List[Dict[str, Any]]
    confidence: float = 0.8

    def to_json(self) -> str:
        return json.dumps({
            "file_path": self.file_path,
            "modification_description": self.modification_description,
            "edits": self.edits,
            "confidence": self.confidence,
        }, indent=2)


class AgentLoop:
    """Deterministic agent loop with a small toolset.

    Contract (inputs/outputs):
    - Inputs: task_description (str)
    - Outputs: either {'solved': True, 'proposal': EditProposal} or {'solved': False}

    Basic safety and behavior:
    - All steps are logged.
    - Limits on steps and recursion depth prevent infinite loops.
    - Deterministic: choice logic is fixed and depends only on observed data.
    """

    def __init__(self, workspace_root: str | Path, max_steps: int = 20, max_recursion: int = 3):
        self.root = Path(workspace_root)
        self.max_steps = int(max_steps)
        self.max_recursion = int(max_recursion)
        self.steps_taken = 0
        self.recursion_depth = 0
        self.log: List[str] = []

    # --- Tools -----------------------------------------------------------------
    def search_file(self, query: str) -> List[Path]:
        """Search files under the workspace for the query string. Returns matching paths.

        This is a simple, deterministic text-search implementation.
        """
        self._log(f"tool=search_file query={query!r}")
        matches: List[Path] = []
        for p in sorted(self.root.rglob("*")):
            if not p.is_file():
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except Exception:
                continue
            if query in text:
                matches.append(p)
        self._log(f"search_file -> {len(matches)} results")
        return matches

    def read_file(self, path: str | Path) -> Optional[str]:
        """Read a file's text. Returns None on failure.
        """
        p = Path(path)
        self._log(f"tool=read_file path={str(p)}")
        try:
            content = p.read_text(encoding="utf-8")
            return content
        except Exception as exc:
            self._log(f"read_file failed: {exc}")
            return None

    def analyze_dependencies(self, path: str | Path) -> List[str]:
        """Return a list of imported module names found in the file (best-effort).

        This is intentionally conservative and only looks for top-level import lines.
        """
        text = self.read_file(path)
        if text is None:
            return []
        imports: List[str] = []
        for line in text.splitlines():
            m = re.match(r"^\s*(?:from|import)\s+([a-zA-Z0-9_\.]+)", line)
            if m:
                imports.append(m.group(1))
        self._log(f"analyze_dependencies -> {imports}")
        return imports

    def propose_edit(self, file_path: str | Path, modification_description: str) -> EditProposal:
        """Return a structured edit proposal JSON object (does not apply changes).

        The caller should run additional verification before applying edits.
        """
        p = Path(file_path)
        self._log(f"tool=propose_edit path={str(p)} desc={modification_description!r}")
        # Minimal proposal: append a trailing comment describing the change.
        edit = {
            "action": "append",
            "content": f"# Proposed change: {modification_description}\n",
        }
        proposal = EditProposal(file_path=str(p), modification_description=modification_description, edits=[edit])
        self._log("propose_edit -> proposal created")
        return proposal

    # --- Agent loop -----------------------------------------------------------
    def run_task(self, task_description: str) -> Dict[str, Any]:
        """Run a deterministic loop until solved or limits reached.

        Simple deterministic policy used for prototype:
        - Search for key tokens from task_description.
        - Read the first matching file, analyze imports.
        - If a "TODO" or "FIXME" is found, propose an edit to that file.
        - Otherwise, if a missing dependency is detected (e.g., an import that
          looks like a local module not present), propose adding a comment.
        - Stop after max_steps.
        """
        self._log(f"task_start: {task_description}")
        self.steps_taken = 0
        self.recursion_depth = 0

        # deterministically derive a small set of search tokens
        tokens = [t for t in re.split(r"\s+|[,:;]", task_description) if t]

        while self.steps_taken < self.max_steps:
            self.steps_taken += 1
            self._log(f"loop_step {self.steps_taken}")

            # choose tool: deterministic ordering
            if tokens:
                token = tokens[0]
            else:
                token = "TODO"

            results = self.search_file(token)
            if results:
                target = results[0]
                content = self.read_file(target)
                if content is None:
                    continue

                # Observe: look for TODO/FIXME
                if "TODO" in content or "FIXME" in content:
                    desc = f"Address {token} found in {target.name}: add implementation or note"
                    proposal = self.propose_edit(target, desc)
                    self._log("task_solved -> edit proposed")
                    return {"solved": True, "proposal": proposal}

                # Analyze dependencies deterministically
                deps = self.analyze_dependencies(target)
                for dep in deps:
                    # If dependency looks local (no dots and file missing), propose edit
                    if self.recursion_depth >= self.max_recursion:
                        self._log("max_recursion reached; skipping deeper analysis")
                        break
                    dep_path = self.root / (dep.replace(".", "/") + ".py")
                    if not dep_path.exists():
                        desc = f"Dependency {dep} imported in {target.name} appears missing; add shim or update imports"
                        proposal = self.propose_edit(target, desc)
                        self._log("task_solved -> dependency edit proposed")
                        return {"solved": True, "proposal": proposal}

                # If nothing decisive, deterministically mark task unsolved and continue
                self._log(f"no decisive finding in {target}; continuing")

            else:
                self._log(f"no files matched token={token!r}")

            # update plan: rotate tokens deterministically
            if tokens:
                tokens = tokens[1:] + [tokens[0]]
            self.recursion_depth = min(self.recursion_depth + 1, self.max_recursion)

        self._log("max_steps reached; task not solved")
        return {"solved": False}

    # --- Helpers --------------------------------------------------------------
    def _log(self, msg: str) -> None:
        logger.info(msg)
        self.log.append(msg)


__all__ = ["AgentLoop", "EditProposal"]
