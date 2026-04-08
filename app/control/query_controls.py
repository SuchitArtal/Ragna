"""Query validation, routing, relevance and answer controls."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


BANNED_GENERIC_PHRASES = [
    "request flow starts",
    "multi-step flow",
    "request handling connects",
    "this area mainly provides",
    "tighten the code paths",
]


@dataclass
class QueryValidationResult:
    valid: bool
    message: str = ""
    requires_clarification: bool = False


@dataclass
class AnswerValidationResult:
    valid: bool
    reason: str = ""


class QueryControlPipeline:
    """Pluggable middleware-style query controls."""

    def __init__(self, repo_root: str, max_retries: int = 2, min_relevance: float = 0.22):
        self.repo_root = str(Path(repo_root).resolve())
        self.max_retries = max_retries
        self.min_relevance = min_relevance

    def validate_query(self, query: str) -> QueryValidationResult:
        text = (query or "").strip()
        if not text:
            return QueryValidationResult(False, "Query is empty. Ask a concrete code question.")

        if len(text) < 3:
            return QueryValidationResult(False, "Query is too short. Add details.")

        # Reject vague prompts early so the assistant can ask for the missing file/module
        # instead of guessing and producing a broad or incorrect answer.
        vague_patterns = [
            r"^fix\s+it$",
            r"^change\s+auth$",
            r"^optimize$",
            r"^refactor$",
            r"^debug$",
        ]
        if any(re.match(p, text.lower()) for p in vague_patterns):
            return QueryValidationResult(
                valid=False,
                message="Please specify target file/module and expected change.",
                requires_clarification=True,
            )

        # Block command-like instructions that could be misread as a request to execute
        # destructive shell actions rather than analyze or edit code.
        if re.search(r"(^|\s)(rm\s+-rf|del\s+/s|format\s+c:|shutdown\s+/s)", text.lower()):
            return QueryValidationResult(
                valid=False,
                message="Dangerous command-like instruction blocked. Rephrase as a safe code request.",
                requires_clarification=True,
            )

        return QueryValidationResult(valid=True)

    def detect_intent(self, query: str) -> str:
        q = query.lower()
        # Intent routing is intentionally simple and deterministic so the demo can explain
        # why a query was treated as list, locate, security review, or general explain.
        if any(k in q for k in ["compare", "vs", "difference", "tradeoff"]):
            return "compare"
        if any(k in q for k in ["summarize", "summary", "overview"]):
            return "summarize"
        if any(k in q for k in ["generate fix", "propose fix", "patch", "edit file"]):
            return "generate_fix"
        if any(k in q for k in ["optimize", "improve", "performance", "speed up"]):
            return "improve"
        if any(k in q for k in ["refactor", "cleanup", "restructure"]):
            return "refactor"
        if any(k in q for k in ["security", "vulnerability", "secret", "credential"]):
            return "security_review"
        if any(k in q for k in ["bug", "error", "failing", "broken", "issue"]):
            return "bug_find"
        if any(k in q for k in ["locate", "where", "find file", "which file"]):
            return "locate"
        if any(k in q for k in ["list", "all", "routes", "endpoints"]):
            return "list"
        if any(k in q for k in ["analyze", "inspect", "review"]):
            return "analyze"
        if any(k in q for k in ["explain", "how", "flow", "works"]):
            return "explain"
        return "summarize"

    def extract_explicit_paths(self, query: str, metadata: List[Dict[str, object]]) -> List[str]:
        q = query.strip()
        candidates: List[str] = []

        # Extract raw filesystem paths and module-like references first so Windows paths
        # survive intact and can override generic semantic retrieval.
        path_patterns = [
            r"([A-Za-z]:\\[^\s'\"]+\.[A-Za-z0-9_]+)",
            r"(\.?\.?/[\w./-]+\.[A-Za-z0-9_]+)",
            r"([\w./-]+\.[A-Za-z0-9_]+)",
        ]
        for pattern in path_patterns:
            for match in re.findall(pattern, q):
                cleaned = str(match).strip("'\"")
                if cleaned and cleaned not in candidates:
                    candidates.append(cleaned)

        module_refs = re.findall(r"(?:check|inspect|debug|analyze)\s+([A-Za-z0-9_.-]+\.(?:py|js|ts|tsx|jsx|json|yaml|yml))", q, flags=re.IGNORECASE)
        for ref in module_refs:
            if ref not in candidates:
                candidates.append(ref)

        known_paths = [str(item.get("file_path", "")) for item in metadata if item.get("file_path")]
        known_norm = {self._norm_path(p): p for p in known_paths}
        resolved: List[str] = []

        for raw in candidates:
            raw_norm = self._norm_path(raw)
            if raw_norm in known_norm:
                resolved.append(known_norm[raw_norm])
                continue

            # Basename fallback lets the assistant resolve user-friendly references like
            # "check_config.js" even when the query omits the full absolute path.
            basename = Path(raw.replace("\\", "/")).name.lower()
            for p in known_paths:
                if Path(p.replace("\\", "/")).name.lower() == basename:
                    resolved.append(p)

            abs_candidate = Path(raw)
            if not abs_candidate.is_absolute():
                abs_candidate = Path(self.repo_root) / raw
            if abs_candidate.exists():
                resolved.append(str(abs_candidate.resolve()))

        # unique preserve order
        uniq: List[str] = []
        seen = set()
        for p in resolved:
            n = self._norm_path(p)
            if n in seen:
                continue
            seen.add(n)
            uniq.append(p)
        return uniq

    def sanitize_context_snippet(self, code: str) -> str:
        """Prompt-injection defense for retrieved content."""
        snippet = str(code or "")
        injection_patterns = [
            r"(?i)ignore\s+previous\s+instructions",
            r"(?i)system\s+prompt",
            r"(?i)you\s+are\s+chatgpt",
            r"(?i)do\s+not\s+follow",
        ]
        for pattern in injection_patterns:
            snippet = re.sub(pattern, "[SANITIZED]", snippet)
        return snippet

    def is_relevant(self, results: List[Dict[str, object]]) -> bool:
        if not results:
            return False
        top = float(results[0].get("score", 0.0))
        return top >= self.min_relevance

    def validate_answer(self, answer: str, query: str, results: List[Dict[str, object]]) -> AnswerValidationResult:
        text = (answer or "").strip().lower()
        if not text:
            return AnswerValidationResult(False, "empty answer")

        if any(p in text for p in BANNED_GENERIC_PHRASES):
            return AnswerValidationResult(False, "banned generic phrase")

        if text in {"not enough information", "no relevant context found yet."}:
            return AnswerValidationResult(True)

        query_terms = [t for t in re.findall(r"[a-z0-9_]+", query.lower()) if len(t) > 3]
        overlap = sum(1 for t in query_terms if t in text)
        if query_terms and overlap == 0:
            return AnswerValidationResult(False, "answer not query-specific")

        source_paths = " ".join(str(item.get("file_path", "")).lower() for item in results[:4])
        if source_paths and not any(Path(p).name.lower() in text for p in source_paths.split() if "." in p):
            # soft condition, allow pass
            return AnswerValidationResult(True)

        return AnswerValidationResult(True)

    def validate_citations(self, answer: str, results: List[Dict[str, object]]) -> bool:
        cited = re.findall(r"\[Source\s+(\d+)\]", answer or "")
        if not cited:
            return True
        max_idx = len(results)
        for idx in cited:
            if int(idx) < 1 or int(idx) > max_idx:
                return False
        return True

    def compute_confidence(
        self,
        *,
        results: List[Dict[str, object]],
        answer_valid: bool,
        citations_valid: bool,
        patch_complexity: float = 0.0,
    ) -> float:
        if not results:
            return 0.2
        top = max(0.0, min(1.0, float(results[0].get("score", 0.0))))
        source_factor = min(1.0, len(results) / 6.0)
        certainty = 0.15 if answer_valid else -0.2
        cite_bonus = 0.05 if citations_valid else -0.1
        complexity_penalty = min(0.2, max(0.0, patch_complexity))
        score = 0.35 * top + 0.25 * source_factor + 0.3 + certainty + cite_bonus - complexity_penalty
        return round(max(0.05, min(0.99, score)), 2)

    def _norm_path(self, path: str) -> str:
        try:
            p = Path(path)
            if p.is_absolute():
                return str(p.resolve()).replace("\\", "/").lower()
            return str((Path(self.repo_root) / p).resolve()).replace("\\", "/").lower()
        except Exception:
            return str(path).replace("\\", "/").lower()
