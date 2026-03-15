"""A deterministic, minimal agent reasoning loop for Ragna (Phase 2).

This module implements a small deterministic agent that uses the vector store and
repository files to reason about tasks, call deterministic tools, and produce
structured edit proposals. It never applies patches; it only returns proposal
objects following the agreed contract.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, TYPE_CHECKING

# Import the class only for type checking to avoid editor/linter unresolved-import warnings.
if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer  # type: ignore


from .vector_store import VectorStore

logger = logging.getLogger(__name__)
MODEL_NAME = "all-MiniLM-L6-v2"


class Agent:
    """A small deterministic agent to reason over repository contents."""

    def __init__(
        self,
        vector_store: VectorStore,
        files: List[Dict[str, Any]],
        *,
        model_name: str = MODEL_NAME,
        repo_root: Optional[str] = None,
    ):
        self.vs = vector_store
        self.files = files
        # Lazy import of SentenceTransformer to avoid top-level import errors in editors.
        try:
            from sentence_transformers import SentenceTransformer as _ST  # type: ignore
        except Exception as exc:  # pragma: no cover - runtime import failure
            raise ImportError(
                "sentence-transformers is required by Agent. Install with: pip install -r requirements.txt"
            ) from exc
        self.model = _ST(model_name)
        self.step = 0
        self.log = logger
        # Optional repo root used to produce relative paths in patches
        self.repo_root = Path(repo_root).resolve() if repo_root else None

    def embed_query(self, query: str) -> List[float]:
        v = self.model.encode([query], show_progress_bar=False, normalize_embeddings=False)
        return v[0].tolist()

    # Tools ---------------------------------------------------------------
    def search_file(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Semantic search via vector store using an embedded query."""
        qv = self.embed_query(query)
        results = self.vs.search(qv, top_k=top_k)
        self.log.info("Tool(search_file) query=%s top_k=%d hits=%d", query, top_k, len(results))
        return results

    def read_file(self, path: str) -> Optional[str]:
        """Return file content for a path from the loaded files list."""
        for f in self.files:
            if f.get("file_path") == path or f.get("file_name") == path:
                self.log.info("Tool(read_file) %s -> length=%d", path, len(f.get("content", "")))
                return f.get("content", "")
        self.log.warning("Tool(read_file) path not found: %s", path)
        return None

    def analyze_dependencies(self, path: str) -> List[str]:
        """Lightweight dependency extraction for Python files (import statements)."""
        content = self.read_file(path)
        if content is None:
            return []
        imports = []
        for line in content.splitlines():
            m = re.match(r"\s*(?:from|import)\s+([a-zA-Z0-9_\.]+)", line)
            if m:
                imports.append(m.group(1))
        self.log.info("Tool(analyze_dependencies) %s -> %d imports", path, len(imports))
        return imports

    def propose_edit(self, file_path: str, modification_description: str, patch_text: str, confidence: float = 0.75) -> Dict[str, Any]:
        """Return a structured edit proposal (do not apply). The `patch_text` must be a unified diff string.

        Produces relative paths in unified-diff headers when possible to improve
        portability of the proposal. The returned dict matches the Edit Proposal Contract.
        """
        # Prefer relative paths in unified diff headers for portability.
        try:
            base = self.repo_root or Path.cwd()
            rel = Path(file_path).resolve().relative_to(base)
            target_path = str(rel)
        except Exception:
            target_path = Path(file_path).name

        # Ensure patch_text header uses relative path. If caller already provided
        # a full header, keep it; otherwise prepend a standard unified-diff header.
        header = f"--- a/{target_path}\n+++ b/{target_path}\n"
        if patch_text.startswith("--- a/") or patch_text.startswith("+++ b/"):
            full_patch = patch_text
        else:
            full_patch = header + patch_text

        proposal = {
            "action": "edit_file",
            "file_path": target_path,
            "proposed_patch": full_patch,
            "reasoning": modification_description,
            "confidence": float(confidence),
        }
        self.log.info("Tool(propose_edit) file=%s confidence=%.2f", target_path, confidence)
        return proposal

    # Agent loop ---------------------------------------------------------
    def run(self, task: str, max_steps: int = 10) -> List[Dict[str, Any]]:
        """Deterministic loop: think -> choose tool -> observe -> update plan.

        This implementation is intentionally small: it performs a sequence of
        semantic searches and basic reads, and returns any edit proposals it
        generates. It guards against infinite loops via max_steps.
        """
        proposals: List[Dict[str, Any]] = []
        plan = task
        self.log.info("Agent starting task: %s", task)

        for step in range(max_steps):
            self.step = step + 1
            # Think (deterministic): derive a focused query from plan
            query = plan
            self.log.info("Step %d: thinking. query=%s", self.step, query)

            # Choose tool: always try semantic search first
            hits = self.search_file(query, top_k=3)

            # Observe: read top hit if any and analyze dependencies
            if hits:
                top = hits[0]
                content = self.read_file(top.get("file_path", ""))
                deps = self.analyze_dependencies(top.get("file_path", "")) if content else []

                # Simple deterministic decision rule: if file contains 'TODO' propose an edit
                if content and "TODO" in content:
                    # Build a tiny unified-diff body (no file headers) so
                    # propose_edit can produce repo-relative headers deterministically.
                    patch_body = (
                        "@@\n"
                        "+# Proposed change: address TODO - add clarification comment\n"
                    )
                    desc = "Insert a comment to mark TODO for later developer action"
                    prop = self.propose_edit(top.get("file_path", ""), desc, patch_body, confidence=0.6)
                    proposals.append(prop)
                    # deterministic termination once a proposal is produced
                    self.log.info("Agent produced proposal for %s", top.get("file_path"))
                    break

                # Otherwise refine plan deterministically by inspecting imports
                if deps:
                    plan = f"Find usages of {deps[0]} related to {task}"
                else:
                    plan = f"Search more about {task} in repository"
            else:
                # no hits: broaden the plan search
                plan = f"Widen search for {task}"

        self.log.info("Agent finished after %d steps; proposals=%d", self.step, len(proposals))
        return proposals