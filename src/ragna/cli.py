"""Ragna command-line interface with polished interactive UX."""

from __future__ import annotations

import logging
import re
import shlex
import sys
from difflib import unified_diff
from pathlib import Path
from typing import Any, Dict, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

logger = logging.getLogger("ragna.cli")
audit_logger = logging.getLogger("ragna.audit")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Reduce noisy third-party logs in interactive mode.
for noisy_logger in [
    "sentence_transformers",
    "transformers",
    "huggingface_hub",
    "httpx",
    "urllib3",
    "faiss.loader",
    "app.retrieval.vector_store",
]:
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)

app = typer.Typer(help="Ragna CLI - safe AI-powered repository assistant")
console = Console()

state: Dict[str, Any] = {
    "repo_path": None,
    "vector_store": None,
    "rag_engine": None,
    "last_edit": None,
    "executor": None,
    "docker_manager": None,
    "history": [],
    "last_query": "",
    "last_intent": "",
    "last_targets": [],
    "last_confidence": 0.0,
}


class DeterministicSynthesisLLM:
    """Deterministic fallback synthesizer implementing an LLM-like interface."""

    def generate(
        self,
        *,
        prompt: Optional[str] = None,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 600,
    ) -> str:
        del temperature, max_tokens
        composed_prompt = prompt or f"{system_prompt or ''}\n\n{user_prompt or ''}"

        query_match = re.search(r"Question:\n(.*?)\n\n(?:Detected Intent|Intent):", composed_prompt, flags=re.DOTALL)
        query = query_match.group(1).strip() if query_match else ""

        intent_match = re.search(r"(?:Detected Intent|Intent):\n(.*?)\n\nContext:", composed_prompt, flags=re.DOTALL)
        intent = intent_match.group(1).strip().lower() if intent_match else "general"

        sections = re.findall(
            r"\[Source\s+(\d+)\]\nFile:\s*(.*?)\nCode:\n(.*?)(?=\n\[Source\s+\d+\]|\Z)",
            composed_prompt,
            flags=re.DOTALL,
        )
        if not sections:
            return "Not enough information"

        citations = ", ".join(f"[Source {sid}]" for sid, _, _ in sections[:3])
        joined_code = "\n".join(code for _, _, code in sections)
        file_paths = [path for _, path, _ in sections if path]

        if intent == "list":
            route_entries: list[tuple[str, str, str]] = []
            for _, file_path, code in sections:
                matches = re.findall(r"@[A-Za-z_][A-Za-z0-9_]*\.(get|post|put|delete|patch)\(\s*[\"']([^\"']+)[\"']", code)
                for method, path in matches:
                    route_entries.append((method.upper(), path, file_path))

            if route_entries:
                seen = set()
                bullets: list[str] = []
                for method, path, file_path in route_entries:
                    key = (method, path)
                    if key in seen:
                        continue
                    seen.add(key)
                    bullets.append(f"- {method} {path} ({file_path})")
                    if len(bullets) >= 10:
                        break
                return "\n".join(bullets) + f"\n{citations}"

            if re.search(r"route|endpoint|api", query, flags=re.IGNORECASE):
                return "Not enough information"

            symbols = re.findall(r"(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", joined_code)
            if not symbols:
                return "Not enough information"
            unique_symbols = list(dict.fromkeys(symbols))[:10]
            return f"Relevant components include: {', '.join(unique_symbols)}. {citations}"

        if intent == "locate":
            if not file_paths:
                return "Not enough information"
            unique_paths = list(dict.fromkeys(file_paths))[:5]
            return f"Relevant location(s): {', '.join(unique_paths)}. {citations}"

        if intent == "analyze":
            checks = [
                (r"(?i)api[_-]?key\s*=\s*['\"]", "Possible hardcoded API key"),
                (r"(?i)password\s*=\s*['\"]", "Possible hardcoded password"),
                (r"\beval\(", "Use of eval() can be unsafe"),
                (r"(?i)md5|sha1", "Weak hashing algorithm usage"),
                (r"execute\(f[\"']", "Potential SQL injection via formatted query"),
            ]
            findings = [message for pattern, message in checks if re.search(pattern, joined_code)]
            if not findings:
                return f"No obvious high-confidence issues found in retrieved snippets. {citations}"
            return f"Potential risks detected: {'; '.join(findings[:4])}. {citations}"

        if intent in {"security_review", "bug_find", "generate_fix"}:
            checks = [
                (r"(?i)api[_-]?key\s*=\s*['\"]", "Possible hardcoded API key"),
                (r"(?i)password\s*=\s*['\"]", "Possible hardcoded password"),
                (r"offset\s*=\s*page\s*\*\s*limit", "Pagination offset bug in task listing"),
            ]
            findings = [message for pattern, message in checks if re.search(pattern, joined_code)]
            if not findings:
                return f"No obvious high-confidence issues found in retrieved snippets. {citations}"
            return f"Potential risks detected: {'; '.join(findings[:4])}. {citations}"

        if intent == "improve":
            suggestions: list[str] = []
            if re.search(r"DEFAULT_ADMIN_PASSWORD", joined_code):
                suggestions.append("Move the default admin password to environment configuration and hash it before storage")
            if re.search(r"password\s*!=\s*db_password|plaintext password", joined_code, flags=re.IGNORECASE):
                suggestions.append("Store password hashes instead of plaintext and verify with a password hash library")
            if re.search(r"offset\s*=\s*page\s*\*\s*limit", joined_code):
                suggestions.append("Fix pagination offset to `(page - 1) * limit`")
            if re.search(r"for i in range\(len\(titles\)\):.*for j in range\(i \+ 1", joined_code, flags=re.DOTALL):
                suggestions.append("Replace the O(n^2) duplicate scan with `Counter` or a SQL `GROUP BY` query")
            if re.search(r"sqlite3\.connect\(", joined_code):
                suggestions.append("Centralize SQLite settings in `get_connection()` and consider row factories, WAL mode, or tuned timeouts")
            if not suggestions:
                if "database" in query.lower():
                    return f"Focus on connection reuse, indexed queries, and avoiding extra round trips. {citations}"
                return f"The main improvement is to tighten the code paths in the retrieved modules. {citations}"
            return "Improvement ideas: " + "; ".join(suggestions[:5]) + f". {citations}"

        if intent == "describe":
            key_defs = re.findall(r"(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", joined_code)
            if not key_defs:
                return "Not enough information"
            focus = ", ".join(list(dict.fromkeys(key_defs))[:5])
            return f"This module focuses on {focus} for the requested behavior. {citations}"

        if intent == "summarize":
            focus_files = ", ".join(list(dict.fromkeys(file_paths))[:4])
            return f"Summary: relevant logic is concentrated in {focus_files or 'the retrieved files'}. {citations}"

        if intent == "compare":
            symbols = list(dict.fromkeys(re.findall(r"(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", joined_code)))[:6]
            return f"Comparison points from retrieved code include: {', '.join(symbols) if symbols else 'not enough distinct symbols'}. {citations}"

        # explain/general
        route_section = next((item for item in sections if "/routes/" in item[1].replace("\\", "/")), None)
        service_section = next((item for item in sections if "/services/" in item[1].replace("\\", "/")), None)
        util_section = next((item for item in sections if "/utils/" in item[1].replace("\\", "/")), None)

        flow_parts: list[str] = []

        if route_section:
            _, route_path, route_code = route_section
            endpoints = re.findall(r"@router\.(get|post|put|delete|patch)\(\s*[\"']([^\"']+)[\"']", route_code)
            calls = re.findall(r"return\s+([A-Za-z_][A-Za-z0-9_]*)\(", route_code)
            if endpoints:
                ep_text = ", ".join(f"{m.upper()} {p}" for m, p in endpoints[:3])
                flow_parts.append(f"Entry points include {ep_text} in {route_path}")
            if calls:
                flow_parts.append(f"Route handlers delegate to {', '.join(list(dict.fromkeys(calls))[:3])}")

        if service_section:
            _, service_path, service_code = service_section
            service_defs = re.findall(r"def\s+([A-Za-z_][A-Za-z0-9_]*)\(", service_code)
            token_calls = re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\(", service_code)
            flow_parts.append(f"Service logic is implemented in {service_path}")
            if service_defs:
                flow_parts.append(f"Core service functions are {', '.join(list(dict.fromkeys(service_defs))[:4])}")
            if "generate_access_token" in token_calls:
                flow_parts.append("Authentication success path generates an access token")

        if util_section:
            _, util_path, util_code = util_section
            util_defs = re.findall(r"def\s+([A-Za-z_][A-Za-z0-9_]*)\(", util_code)
            if util_defs:
                flow_parts.append(f"Utility support comes from {util_path} ({', '.join(list(dict.fromkeys(util_defs))[:3])})")

        if not flow_parts:
            file_names = [Path(path).name for _, path, _ in sections[:3] if path]
            if not file_names and not query.strip():
                return "Not enough information"
            flow_parts.append(f"Relevant logic appears in {', '.join(file_names) or 'core modules'}")

        return ". ".join(flow_parts) + f". {citations}"


def _ensure_project_root_on_path() -> None:
    """Ensure repository root is on sys.path for editable installs.

    The current runtime package is loaded from src/ragna, while core modules
    currently live under top-level app/. This helper keeps CLI imports working
    in local editable mode.
    """
    project_root = Path(__file__).resolve().parents[2]
    root_str = str(project_root)
    if root_str not in sys.path:
        sys.path.append(root_str)


class SimpleRAGEngine:
    """Lightweight RAG placeholder backed by VectorStore search."""

    def __init__(
        self,
        vector_store: Any,
        repo_path: str,
        llm: Optional[Any] = None,
        response_mode: str = "explain",
    ):
        _ensure_project_root_on_path()
        from app.control.query_controls import QueryControlPipeline

        self.vector_store = vector_store
        self.repo_path = str(Path(repo_path).resolve())
        self.repo_path_normalized = self._normalize_path(self.repo_path)
        self.llm = llm or DeterministicSynthesisLLM()
        self.response_mode = response_mode
        self.controls = QueryControlPipeline(self.repo_path)
        self.memory: Dict[str, Any] = {
            "last_analyzed_file": "",
            "last_module": "",
            "last_patch": None,
            "last_query": "",
            "last_intent": "",
        }

    def _audit(self, event: str, **data: Any) -> None:
        """Structured audit/trace logging."""
        payload = {"event": event, **data}
        audit_logger.info("AUDIT %s", payload)

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Normalize paths for stable dedupe/filter behavior across OSes."""
        if not path:
            return ""
        try:
            normalized = str(Path(path).resolve())
        except Exception:
            normalized = str(path)
        return normalized.replace("\\", "/").lower().rstrip("/")

    def _to_repo_relative_path(self, path: str) -> str:
        """Convert absolute file path to repo-relative path when possible."""
        if not path:
            return ""
        try:
            p = Path(path).resolve()
            root = Path(self.repo_path).resolve()
            return str(p.relative_to(root)).replace("\\", "/")
        except Exception:
            return path.replace("\\", "/")

    def answer(self, query: str) -> Dict[str, Any]:
        _ensure_project_root_on_path()
        from app.retrieval.embeddings import embed_chunks

        lowered = query.lower().strip()
        validation = self.controls.validate_query(query)
        if not validation.valid:
            self._audit("query_rejected", query=query, reason=validation.message)
            return {
                "answer": validation.message,
                "results": [],
                "proposal": None,
                "confidence": 0.0,
            }

        intent = self.controls.detect_intent(query)
        explicit_targets = self.controls.extract_explicit_paths(query, getattr(self.vector_store, "metadata", []))
        self.memory["last_query"] = query
        self.memory["last_intent"] = intent
        if explicit_targets:
            self.memory["last_analyzed_file"] = explicit_targets[0]

        if self._is_casual_chat_query(lowered):
            return {
                "answer": "I'm doing well — ask me about the repo, a file, a route, or a bug.",
                "results": [],
                "proposal": None,
                "confidence": 0.9,
            }
        if self._is_overview_query(lowered):
            overview = self._build_codebase_overview()
            overview["confidence"] = 0.86
            return overview

        query_vectors, _ = embed_chunks(
            [
                {
                    "chunk_id": "query",
                    "file_path": "",
                    "type": "query",
                    "name": "query",
                    "code": query,
                }
            ],
            log_progress=False,
        )

        raw_results = self.vector_store.search(query_vectors[0], top_k=20) if query_vectors else []
        ranked = self._rank_results(query, raw_results, intent=intent, explicit_targets=explicit_targets)

        # File-scoping: prioritize the explicit target first so the answer stays grounded
        # in the exact file the user named, instead of drifting to semantically similar files.
        scoped_results = ranked
        if explicit_targets:
            scoped_results = [
                r for r in ranked if any(self._normalize_path(str(r.get("file_path", ""))) == self._normalize_path(t) for t in explicit_targets)
            ]
            if not scoped_results:
                scoped_results = self._file_fallback_results(explicit_targets)

        if explicit_targets:
            # Strict mode: never mix unrelated files into the answer when the user supplied
            # an explicit path. This is the main anti-wrong-file safeguard for demos.
            results = scoped_results[:8]
        else:
            results = self._expand_multihop_results(query, scoped_results[:10])[:8]

        if not self.controls.is_relevant(results):
            self._audit("low_relevance", query=query, intent=intent, top_score=float(results[0].get("score", 0.0)) if results else 0.0)
            return {
                "answer": "Not enough relevant information found.",
                "results": results[:5],
                "proposal": None,
                "confidence": 0.15,
            }

        if results:
            if self.response_mode == "locate":
                top_files = [str(item.get("file_path", "")) for item in results[:3] if item.get("file_path")]
                answer = "Most relevant locations: " + ", ".join(top_files)
            else:
                answer = self._synthesize_answer(query, results, intent=intent)
                if (
                    answer.strip().lower() == "not enough information"
                    and intent == "list"
                    and re.search(r"route|endpoint|api", query, flags=re.IGNORECASE)
                ):
                    fallback = self._list_routes_from_index()
                    if fallback:
                        answer = fallback
                # If synthesis is still too generic, use a deterministic file-specific fallback
                # so explicit-path queries always produce something rooted in the target file.
                if answer.strip().lower() in {
                    "not enough information",
                    "not enough information.",
                    "not enough relevant information found.",
                } and explicit_targets:
                    answer = self._fallback_explicit_target_answer(query, results, intent, explicit_targets)
        else:
            answer = "No relevant context found yet."

        if "request flow starts" in answer.lower():
            answer += "\n\n[Warning: answer may be too generic]"

        # Build a patch proposal only from the same scoped context used for the answer.
        proposal = self._build_fix_proposal(query, results, explicit_targets=explicit_targets)

        answer_validation = self.controls.validate_answer(answer, query, results)
        if not answer_validation.valid:
            if explicit_targets:
                answer = self._fallback_explicit_target_answer(query, results, intent, explicit_targets)
            else:
                answer = "Not enough information"

        citations_valid = self.controls.validate_citations(answer, results)
        if not citations_valid:
            answer = re.sub(r"\s*\[Source\s+\d+\]", "", answer).strip()

        confidence = self.controls.compute_confidence(
            results=results,
            answer_valid=answer_validation.valid,
            citations_valid=citations_valid,
            patch_complexity=min(0.2, 0.02 * len(str(proposal.get("proposed_patch", "")).splitlines())) if proposal else 0.0,
        )

        if proposal:
            self.memory["last_patch"] = proposal

        self._audit(
            "answer_generated",
            query=query,
            intent=intent,
            explicit_targets=explicit_targets,
            source_count=len(results),
            confidence=confidence,
            proposal=bool(proposal),
        )

        return {"answer": answer, "results": results, "proposal": proposal, "confidence": confidence, "intent": intent}

    def _file_fallback_results(self, explicit_targets: list[str]) -> list[dict]:
        """Fallback when explicit file is requested but retrieval has no chunk hit."""
        results: list[dict] = []
        for target in explicit_targets:
            path = Path(target)
            if not path.is_absolute():
                path = Path(self.repo_path) / target
            if not path.exists() or not path.is_file():
                continue
            try:
                code = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if not code.strip():
                continue
            results.append(
                {
                    "chunk_id": "file_fallback",
                    "file_path": str(path.resolve()),
                    "type": "file",
                    "name": path.name,
                    "code": code[:2200],
                    "score": 0.95,
                }
            )
        return results

    def _expand_multihop_results(self, query: str, results: list[dict]) -> list[dict]:
        """Heuristic multi-hop expansion (route->service->db/util)."""
        if not results:
            return results
        lowered = query.lower()
        if not any(k in lowered for k in ["flow", "how", "trace", "request", "security", "auth", "database"]):
            return results

        metadata = getattr(self.vector_store, "metadata", [])
        existing = {self._normalize_path(str(r.get("file_path", ""))) for r in results}
        expanded = list(results)

        needs = ["services", "database", "auth", "utils", "routes"]
        for item in metadata:
            p = str(item.get("file_path", ""))
            norm = self._normalize_path(p)
            if not p or norm in existing:
                continue
            lowered_path = p.replace("\\", "/").lower()
            if any(k in lowered_path for k in needs):
                candidate = dict(item)
                candidate["score"] = float(candidate.get("score", 0.0)) + 0.15
                expanded.append(candidate)
                existing.add(norm)
            if len(expanded) >= 12:
                break

        expanded.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
        return expanded

    def _build_fix_proposal(
        self,
        query: str,
        results: list[dict],
        *,
        explicit_targets: Optional[list[str]] = None,
    ) -> Optional[Dict[str, object]]:
        """Build a concrete edit proposal from retrieved files when query asks for fixes."""
        lowered = query.lower()
        if not any(k in lowered for k in ["fix", "bug", "issue", "vulnerability", "security", "propose"]):
            return None

        explicit_norm = {self._normalize_path(p) for p in (explicit_targets or [])}

        candidate_results = list(results[:5])
        if explicit_norm:
            candidate_results = [
                item
                for item in results
                if self._normalize_path(str(item.get("file_path", ""))) in explicit_norm
            ]

        for item in candidate_results:
            abs_path = str(item.get("file_path", ""))
            rel_path = self._to_repo_relative_path(abs_path)
            if not rel_path:
                continue

            file_path = Path(self.repo_path) / rel_path
            if not file_path.exists() or not file_path.is_file():
                continue

            try:
                original = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            updated = original
            reasoning = ""

            if "THIRD_PARTY_API_KEY" in original and ("hardcoded" in lowered or "security" in lowered):
                updated = re.sub(
                    r'(?m)^THIRD_PARTY_API_KEY\s*=\s*["\'][^"\']*["\']\s*$',
                    'THIRD_PARTY_API_KEY = ""  # TODO: load from environment',
                    updated,
                    count=1,
                )
                reasoning = "Removed hardcoded API key and replaced with environment placeholder"

            if updated == original and "DEFAULT_ADMIN_PASSWORD" in original:
                updated = re.sub(
                    r'(?m)^DEFAULT_ADMIN_PASSWORD\s*=\s*["\'][^"\']*["\']\s*(#.*)?$',
                    'DEFAULT_ADMIN_PASSWORD = ""  # TODO: set via environment variable',
                    updated,
                    count=1,
                )
                reasoning = "Removed hardcoded default admin password"

            if updated == original:
                continue

            patch = self._make_unified_patch(rel_path, original, updated)
            if not patch.strip():
                continue

            return {
                "action": "edit_file",
                "file_path": rel_path,
                "proposed_patch": patch,
                "reasoning": reasoning or "Generated targeted fix from retrieved context",
                "confidence": 0.7,
            }

        return None

    def _fallback_explicit_target_answer(
        self,
        query: str,
        results: list[dict],
        intent: str,
        explicit_targets: list[str],
    ) -> str:
        """Generate a deterministic, file-specific fallback answer for explicit path queries."""
        if not explicit_targets:
            return "Not enough information"

        target = explicit_targets[0]
        target_norm = self._normalize_path(target)
        target_item = next(
            (r for r in results if self._normalize_path(str(r.get("file_path", ""))) == target_norm),
            None,
        )

        if not target_item:
            return "Not enough information"

        code = str(target_item.get("code", ""))
        rel = self._to_repo_relative_path(str(target_item.get("file_path", target)))
        ql = query.lower()

        suggestions: list[str] = []
        if re.search(r"process\.env|dotenv|env", code, flags=re.IGNORECASE):
            suggestions.append("validate required environment variables at startup and fail fast with clear errors")
        if re.search(r"console\.log\(|console\.error\(", code):
            suggestions.append("avoid logging sensitive values; sanitize config values before printing")
        if re.search(r"==\s*['\"][^'\"]+['\"]", code):
            suggestions.append("prefer strict equality checks and centralized validation helpers for config flags")
        if re.search(r"TODO|FIXME", code, flags=re.IGNORECASE):
            suggestions.append("resolve TODO/FIXME items in config checks and convert them into enforced validations")

        if intent in {"improve", "security_review", "analyze"} and suggestions:
            return f"For {rel}, key improvements are: " + "; ".join(suggestions[:4]) + "."

        if "security" in ql:
            return f"For {rel}, enforce strict env-var validation, avoid secret logging, and return non-sensitive error messages."

        if intent == "improve":
            return f"For {rel}, improve robustness by validating required config keys, normalizing defaults, and hard-failing on unsafe/missing settings."

        return "Not enough information"

    @staticmethod
    def _make_unified_patch(file_path: str, original: str, updated: str) -> str:
        """Create unified diff patch text for a single file."""
        original_lines = original.splitlines()
        updated_lines = updated.splitlines()
        diff = unified_diff(
            original_lines,
            updated_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm="",
        )
        return "\n".join(diff)

    def _list_routes_from_index(self) -> str:
        """Extract routes directly from indexed metadata as a fallback for list-route queries."""
        metadata = getattr(self.vector_store, "metadata", [])
        route_lines: list[str] = []
        seen = set()

        for item in metadata:
            file_path = str(item.get("file_path", ""))
            if not file_path:
                continue
            normalized = self._normalize_path(file_path)
            if self.repo_path_normalized and not normalized.startswith(self.repo_path_normalized):
                continue

            code = str(item.get("code", ""))
            matches = re.findall(r"@[A-Za-z_][A-Za-z0-9_]*\.(get|post|put|delete|patch)\(\s*[\"']([^\"']+)[\"']", code)
            for method, path in matches:
                key = (method.upper(), path)
                if key in seen:
                    continue
                seen.add(key)
                rel = self._to_repo_relative_path(file_path)
                route_lines.append(f"- {method.upper()} {path} ({rel})")
                if len(route_lines) >= 12:
                    return "\n".join(route_lines)

        return "\n".join(route_lines)

    def _detect_intent(query: str) -> str:
        return self.controls.detect_intent(query)

    def _build_context(self, results: list[dict]) -> str:
        """Build bounded synthesis context from top retrieved chunks."""
        context_blocks: list[str] = []
        snippets_by_file: dict[str, int] = {}

        for item in results[:6]:
            file_path = str(item.get("file_path", ""))
            snippets_used = snippets_by_file.get(file_path, 0)
            if snippets_used >= 2:
                continue

            snippet = self.controls.sanitize_context_snippet(str(item.get("code", "")).strip()[:700])
            if not snippet:
                snippet = "# code snippet unavailable"

            context_blocks.append(
                f"[Source {len(context_blocks) + 1}]\n"
                f"File: {file_path}\n"
                "Code:\n"
                f"{snippet}"
            )

            snippets_by_file[file_path] = snippets_used + 1

        return "\n\n".join(context_blocks)

    def _build_prompt(self, query: str, context: str, intent: str) -> str:
        return f"""
You are a senior backend engineer analyzing a real codebase.

Question:
{query}

Intent:
{intent}

Context:
{context}

INSTRUCTIONS:

1. Answer STRICTLY based on intent:

- explain → describe step-by-step flow
- list → return bullet list of items
- describe → explain purpose clearly
- analyze → identify concrete issues
- locate → mention exact file/module
- bug_find → identify likely bug and where
- security_review → identify security risks and mitigations
- refactor → suggest concrete refactors
- generate_fix → suggest actionable patch-level fix
- summarize → concise summary
- compare → compare alternatives/components

2. Your answer MUST directly address the question.

3. DO NOT give generic answers.

4. NEVER say phrases like:
- "multi-step flow"
- "request handling connects"
- "this area mainly provides"

5. Use file names when possible (e.g., app/auth.py)

6. If information is insufficient:
    say "Not enough information"

7. The answer MUST change depending on the question.
    If it looks reusable across questions → rewrite it.

Now produce the final answer.
"""

    def _synthesize_answer(self, query: str, results: list[dict], intent: Optional[str] = None) -> str:
        """Generate a query-specific grounded answer from retrieved results."""
        intent = intent or self._detect_intent(query)
        context = self._build_context(results)
        if not context.strip():
            return "Not enough information"

        prompt = self._build_prompt(query, context, intent)

        last_error = None
        for _ in range(self.controls.max_retries + 1):
            try:
                response = self.llm.generate(prompt=prompt, temperature=0.1)
                answer = str(response).strip() or "Not enough information"
                validation = self.controls.validate_answer(answer, query, results)
                if validation.valid:
                    return answer
                last_error = validation.reason
                prompt += "\n\nYour previous answer was invalid. Rewrite to be specific and grounded in context."
            except Exception as exc:
                last_error = str(exc)
                logger.warning("Synthesis retry due to LLM error: %s", exc)

        logger.warning("Synthesis fallback after retries: %s", last_error)
        return "Not enough information"

    def _build_codebase_overview(self) -> Dict[str, Any]:
        """Return a concise repository overview from indexed metadata."""
        metadata = getattr(self.vector_store, "metadata", [])
        files = []
        for item in metadata:
            file_path = str(item.get("file_path", ""))
            if file_path and self._normalize_path(file_path).startswith(self.repo_path_normalized):
                files.append(file_path)

        unique_files = sorted(set(files))
        if not unique_files:
            return {"answer": "No indexed files available.", "results": [], "proposal": None}

        priority_hints = ["main.py", "routes", "services", "database", "config"]
        highlights = []
        for hint in priority_hints:
            for f in unique_files:
                if hint in f.replace("\\", "/"):
                    highlights.append(f)
            if len(highlights) >= 5:
                break

        highlights = list(dict.fromkeys(highlights))[:5]
        answer = (
            f"Indexed {len(unique_files)} files. "
            "Key areas include API routes, services, database access, and configuration."
        )
        results = [{"file_path": path, "score": 1.0} for path in highlights]
        return {"answer": answer, "results": results, "proposal": None}

    def _rank_results(self, query: str, results: list[dict], *, intent: str = "general", explicit_targets: Optional[list[str]] = None) -> list[dict]:
        """Deduplicate and rerank results using simple keyword-aware scoring."""
        lowered_query = query.lower()
        query_terms = [term for term in re.findall(r"[a-z0-9_]+", lowered_query) if len(term) > 2]
        seen: set[str] = set()
        ranked: list[dict] = []

        for item in results:
            path = str(item.get("file_path", ""))
            if not path:
                continue
            normalized_path = self._normalize_path(path)
            if self.repo_path_normalized and not normalized_path.startswith(self.repo_path_normalized):
                continue
            if normalized_path in seen:
                continue
            seen.add(normalized_path)

            base_score = float(item.get("score", 0.0))
            lowered_path = path.lower()
            keyword_boost = sum(0.2 for t in query_terms if t in lowered_path)
            intent_boost = 0.0

            if intent in {"list", "locate"} or any(k in lowered_query for k in ["route", "routes", "endpoint", "endpoints"]):
                if "/routes/" in lowered_path or "routes" in lowered_path:
                    intent_boost += 1.2
                if lowered_path.endswith("main.py"):
                    intent_boost += 0.4

            if intent in {"analyze", "bug_find", "refactor"} or any(k in lowered_query for k in ["database", "db", "sql", "session"]):
                if any(k in lowered_path for k in ["database", "db", "models", "repository"]):
                    intent_boost += 1.0
                if "task_service" in lowered_path:
                    intent_boost += 0.6

            if intent in {"security_review", "generate_fix"} or any(k in lowered_query for k in ["auth", "login", "token", "security", "vulnerability", "password"]):
                if any(k in lowered_path for k in ["auth", "security", "config", "settings"]):
                    intent_boost += 0.9
                if "utils/security" in lowered_path:
                    intent_boost += 0.5

            if explicit_targets:
                normalized_target_set = {self._normalize_path(t) for t in explicit_targets}
                if normalized_path in normalized_target_set:
                    intent_boost += 2.0

            item_copy = dict(item)
            item_copy["score"] = base_score + keyword_boost + intent_boost
            ranked.append(item_copy)

        ranked.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
        return ranked

    @staticmethod
    def _is_overview_query(lowered_query: str) -> bool:
        """Detect repository-overview style questions more robustly."""
        if "overview" in lowered_query or "architecture" in lowered_query:
            return True
        if "codebase" in lowered_query and re.search(r"\b(explain|describe|summarize|summary|walk me through)\b", lowered_query):
            return True
        if re.search(r"\b(project|repo|repository)\b", lowered_query) and "structure" in lowered_query:
            return True
        return False

    @staticmethod
    def _is_casual_chat_query(lowered_query: str) -> bool:
        """Detect non-code conversational prompts that should bypass retrieval."""
        if not lowered_query:
            return True

        greeting_patterns = [
            r"^(hi|hello|hey|yo|sup)\b",
            r"\bhow are you\b",
            r"\bgood morning\b",
            r"\bgood afternoon\b",
            r"\bgood evening\b",
        ]
        if any(re.search(pattern, lowered_query) for pattern in greeting_patterns):
            code_keywords = ["file", "repo", "repository", "route", "bug", "fix", "security", "analyze", "ask", "check"]
            if not any(keyword in lowered_query for keyword in code_keywords):
                return True

        return False


def _guardrail_block_reason_for_query(query: str) -> Optional[str]:
    """Block obvious unsafe edit-style prompts before proposal/apply steps."""
    stripped = query.strip()
    lowered = stripped.lower()

    # Strong signals of unsafe path manipulation.
    if re.search(r"\.\.[/\\]", stripped) or re.search(r"(^|\s)/etc/|(^|\s)c:[/\\]windows", lowered):
        return "Unsafe path operation detected in prompt"

    # Secret-like assignment in natural language prompts (e.g., API_KEY="123456").
    _ensure_project_root_on_path()
    from app.guardrails.secret_scanner import SecretScanner

    scanner = SecretScanner()
    secret_result = scanner.scan_patch_for_secrets([f"+{stripped}"])
    if secret_result.get("has_secrets", False):
        return "Potential hardcoded secret detected in requested change"

    # Catch short but obvious API key assignments that may evade strict regex length checks.
    if re.search(r"(?i)(api[_-]?key|token|secret|password)\s*[=:]", stripped):
        return "Sensitive credential assignment detected in requested change"

    return None


def _record_history(command: str) -> None:
    """Store interactive commands for quick review."""
    history = state.setdefault("history", [])
    history.append(command)
    state["history"] = history[-10:]


def _print_success(message: str) -> None:
    console.print(f"[green]{message}[/green]")


def _print_error(message: str) -> None:
    console.print(f"[red]{message}[/red]")


def _print_info(message: str) -> None:
    console.print(f"[cyan]{message}[/cyan]")


def _show_welcome_banner() -> None:
    """Display a polished welcome banner for interactive mode."""
    console.print(
        Panel.fit(
            "[bold cyan]⚡ Ragna[/bold cyan]\n"
            "[white]Safe AI Coding Assistant[/white]\n\n"
            "[dim]Type 'help' for commands, 'exit' to quit[/dim]",
            border_style="cyan",
        )
    )


def _show_help() -> None:
    """Show available interactive commands and descriptions."""
    table = Table(title="Commands", header_style="bold cyan", box=None, show_lines=False)
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Description", style="white")
    table.add_row("analyze <path>", "Index a repository")
    table.add_row("ask <query>", "Ask Ragna a question")
    table.add_row("apply", "Apply the last proposed edit")
    table.add_row("run <command>", "Run a command in Docker sandbox")
    table.add_row("status", "Show current CLI status")
    table.add_row("clear", "Clear the interactive screen")
    table.add_row("history", "Show last commands")
    table.add_row("help", "Show this help")
    table.add_row("exit / quit", "Leave interactive mode")
    console.print(Panel(table, title="Help", border_style="blue"))


def _show_history() -> None:
    """Print the last few interactive commands."""
    history = state.get("history", [])
    if not history:
        console.print("[dim]No command history yet.[/dim]")
        return

    table = Table(title="Last Commands", header_style="bold magenta", box=None)
    table.add_column("#", style="magenta", no_wrap=True)
    table.add_column("Command", style="white")
    for index, item in enumerate(history[-5:], start=1):
        table.add_row(str(index), item)
    console.print(Panel(table, border_style="magenta"))


def _print_status() -> None:
    """Print a concise runtime status panel."""
    repo_value = state.get("repo_path") or "not loaded"
    last_edit = "available" if state.get("last_edit") else "none"
    vector_ready = "ready" if state.get("vector_store") else "not ready"
    docker_ready = "ready" if state.get("docker_manager") else "not ready"
    table = Table(title="📊 Ragna Status", header_style="bold cyan", box=None)
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")
    table.add_row("Repo", f"loaded ({repo_value})")
    table.add_row("Vector DB", vector_ready)
    table.add_row("Last Edit", last_edit)
    table.add_row("Docker", docker_ready)
    console.print(Panel(table, border_style="green"))


def _handle_analyze(repo_path: str) -> bool:
    """Analyze repository, build vector store, initialize RAG engine, and store state."""
    try:
        _print_info("⏳ Indexing repository...")
        _ensure_project_root_on_path()
        from app.retrieval.embeddings import embed_chunks
        from app.retrieval.parser import parse_repository
        from app.retrieval.repo_loader import load_repository
        from app.retrieval.vector_store import VectorStore

        repo = Path(repo_path).expanduser().resolve()
        logger.info("Analyzing repository: %s", repo)

        files = load_repository(str(repo))
        chunks = parse_repository(files)
        vectors, metadata = embed_chunks(chunks)
        if not vectors:
            _print_error("No embeddings generated. Ensure repository has supported code files.")
            return False

        vector_store = VectorStore(dim=len(vectors[0]))
        vector_store.add_embeddings(vectors, metadata)
        rag_engine = SimpleRAGEngine(vector_store, str(repo))

        state["repo_path"] = str(repo)
        state["vector_store"] = vector_store
        state["rag_engine"] = rag_engine
        state["last_edit"] = None

        _print_success("✅ Done — repository indexed and RAG engine ready.")
        console.print(
            Panel.fit(
                f"[bold]Repository:[/bold] {repo}\n"
                f"[cyan]Files loaded:[/cyan] {len(files)}\n"
                f"[cyan]Chunks:[/cyan] {len(chunks)}\n"
                f"[cyan]Embeddings:[/cyan] {len(vectors)}",
                border_style="green",
            )
        )
        return True
    except Exception as exc:
        logger.exception("Analyze failed")
        _print_error(f"Analyze failed: {exc}")
        return False


def _handle_ask(query: str) -> bool:
    """Answer query using RAG engine and optionally store proposed edit."""
    rag_engine = state.get("rag_engine")
    if rag_engine is None:
        _print_error("Repository not analyzed. Run: analyze <path>")
        return False

    blocked_reason = _guardrail_block_reason_for_query(query)
    if blocked_reason:
        state["last_edit"] = None
        console.print(
            Panel.fit(
                f"[bold red]❌ Blocked by guardrails[/bold red]\n{blocked_reason}",
                border_style="red",
                title="Ragna",
            )
        )
        return True

    try:
        lowered = query.strip().lower()
        if lowered in {"fix that", "fix this", "explain further", "continue", "apply previous"}:
            last_query = str(state.get("last_query", "")).strip()
            if not last_query:
                _print_error("No previous query context available.")
                return False
            query = f"{last_query} (follow-up: {lowered})"

        _print_info("⏳ Thinking...")
        response = rag_engine.answer(query)
        answer = response.get("answer", "")
        proposal = response.get("proposal")
        results = response.get("results", [])
        confidence = float(response.get("confidence", 0.0))
        intent = str(response.get("intent", ""))

        state["last_query"] = query
        state["last_intent"] = intent
        state["last_confidence"] = confidence
        state["last_targets"] = [str(item.get("file_path", "")) for item in results[:3] if item.get("file_path")]

        console.print(
            Panel.fit(
                f"[bold cyan]💡 Answer:[/bold cyan]\n{answer}\n\n"
                f"[dim]intent={intent or 'n/a'} confidence={confidence:.2f}[/dim]",
                border_style="cyan",
                title="Ragna",
            )
        )

        source_lines = [str(item.get("file_path", "")) for item in results if item.get("file_path")]
        source_lines = list(dict.fromkeys(source_lines))
        if source_lines:
            source_table = Table(title="📂 Sources", header_style="bold green", box=None)
            source_table.add_column("#", style="green", no_wrap=True)
            source_table.add_column("File", style="white")
            for index, item in enumerate(source_lines[:5], start=1):
                source_table.add_row(str(index), item)
            console.print(Panel(source_table, border_style="green"))

        if proposal:
            state["last_edit"] = proposal
            _print_success("🛠 Proposed fix generated and stored as last edit.")
            console.print(
                Panel.fit(
                    f"[bold]📌 Proposed Edit[/bold]\n"
                    f"[cyan]File:[/cyan] {proposal.get('file_path')}\n"
                    f"[cyan]Confidence:[/cyan] {proposal.get('confidence')}\n"
                    f"[cyan]Reasoning:[/cyan] {proposal.get('reasoning')}",
                    border_style="yellow",
                )
            )
        return True
    except Exception as exc:
        logger.exception("Ask failed")
        _print_error(f"Ask failed: {exc}")
        return False


def _handle_apply(preview: bool = False) -> bool:
    """Apply last proposed edit through sandbox executor."""
    proposal = state.get("last_edit")
    repo_path = state.get("repo_path")
    if not proposal:
        _print_error("No edit available. Run ask that generates a fix proposal first.")
        return False
    if not repo_path:
        _print_error("Repository not analyzed. Run: analyze <path>")
        return False

    action = str(proposal.get("action", "edit_file")) if isinstance(proposal, dict) else "edit_file"
    requires_confirmation = action in {"delete_file"}
    if isinstance(proposal, dict) and bool(proposal.get("touches_many_files", False)):
        requires_confirmation = True
    if requires_confirmation:
        confirmed = typer.confirm("This is a protected action. Continue?", default=False)
        if not confirmed:
            _print_info("Apply cancelled.")
            return False

    try:
        _ensure_project_root_on_path()
        from app.sandbox.sandbox_executor import SandboxExecutor

        _print_info("⏳ Applying edit in sandbox...")
        executor = state.get("executor") or SandboxExecutor()
        state["executor"] = executor
        state["docker_manager"] = getattr(executor, "docker_manager", None)

        proposal_to_apply = dict(proposal) if isinstance(proposal, dict) else {}
        if preview:
            proposal_to_apply["preview"] = True
            proposal_to_apply["write_back"] = False

        result = executor.execute_edit(repo_path, proposal_to_apply)
        success = bool(result.get("success", False))
        validation = result.get("validation_result", {})

        console.print(
            Panel.fit(
                f"[bold]🛡 Guardrails:[/bold] {'PASSED' if validation.get('allowed') else 'FAILED'}\n"
                f"[bold]🐳 Sandbox:[/bold] {'EXECUTED' if success else 'EXECUTION FAILED'}\n"
                f"[bold]✅ Result:[/bold] {'SUCCESS' if success else 'FAILED'}",
                border_style="green" if success else "red",
            )
        )

        validation_table = Table(title="Validation Result", header_style="bold cyan", box=None)
        validation_table.add_column("Check", style="cyan", no_wrap=True)
        validation_table.add_column("Value", style="white")
        for key, value in validation.items():
            validation_table.add_row(str(key), str(value))
        console.print(Panel(validation_table, border_style="cyan"))

        if result.get("execution_output"):
            console.print(Panel.fit(f"[bold]stdout[/bold]\n{result.get('execution_output')}", border_style="cyan"))
        if result.get("execution_error"):
            console.print(Panel.fit(f"[bold]stderr[/bold]\n{result.get('execution_error')}", border_style="red"))
        if result.get("written_file"):
            _print_success(f"Patched file written: {result.get('written_file')}")
        elif preview and success:
            _print_info("Preview mode: patch validated/applied in memory only; no file was written.")

        if success:
            _print_success("Apply completed")
        else:
            _print_error("Apply failed")
        return success
    except Exception as exc:
        logger.exception("Apply failed")
        _print_error(f"Apply failed: {exc}")
        return False


def _handle_run(command: str) -> bool:
    """Run command in Docker and print stdout/stderr."""
    _ensure_project_root_on_path()
    from app.sandbox.docker_manager import DockerManager

    repo_path = state.get("repo_path") or str(Path.cwd())
    manager = state.get("docker_manager") or DockerManager()
    state["docker_manager"] = manager

    try:
        _print_info("⚙ Running command in sandbox...")
        created = manager.create_container(image="python:3.11", repo_path=repo_path)
        if not created.get("created"):
            _print_error(f"Container creation failed: {created.get('errors')}")
            return False

        container_id = str(created.get("container_id"))
        result = manager.run_command(container_id, command)
        manager.stop_container(container_id)

        if result.get("ran"):
            _print_success("✅ Command completed.")
        else:
            _print_error("Command failed.")

        if result.get("stdout"):
            console.print(Panel.fit(f"[bold]stdout[/bold]\n{result.get('stdout')}", border_style="green"))
        if result.get("stderr"):
            console.print(Panel.fit(f"[bold]stderr[/bold]\n{result.get('stderr')}", border_style="red"))

        console.print(Panel(Text(f"exit code: {result.get('exit_code')}", style="dim"), border_style="blue"))
        return bool(result.get("ran"))
    except Exception as exc:
        logger.exception("Run failed")
        _print_error(f"Run failed: {exc}")
        return False


def _run_interactive_mode() -> None:
    """Interactive shell mode with banner, help, history, and natural query fallback."""
    _show_welcome_banner()
    while True:
        raw = console.input("[bold cyan]ragna> [/]").strip()
        if not raw:
            continue

        lowered = raw.lower()
        if lowered in {"exit", "quit"}:
            _print_success("Goodbye.")
            break

        _record_history(raw)

        if lowered == "status":
            _print_status()
            continue
        if lowered == "clear":
            console.clear()
            continue
        if lowered == "help":
            _show_help()
            continue
        if lowered == "history":
            _show_history()
            continue

        # Preserve raw Windows paths with backslashes (shlex can consume backslashes).
        if lowered.startswith("analyze "):
            path_arg = raw[len("analyze ") :].strip()
            if (path_arg.startswith('"') and path_arg.endswith('"')) or (
                path_arg.startswith("'") and path_arg.endswith("'")
            ):
                path_arg = path_arg[1:-1]
            if not path_arg:
                _print_error("Usage: analyze <path>")
                continue
            _handle_analyze(path_arg)
            continue

        # Preserve full shell command text for sandbox execution.
        if lowered.startswith("run "):
            command_arg = raw[len("run ") :].strip()
            if not command_arg:
                _print_error("Usage: run <command>")
                continue
            _handle_run(command_arg)
            continue

        # Preserve ask query text exactly as typed (important for Windows paths).
        if lowered.startswith("ask "):
            query_arg = raw[len("ask ") :].strip()
            if (query_arg.startswith('"') and query_arg.endswith('"')) or (
                query_arg.startswith("'") and query_arg.endswith("'")
            ):
                query_arg = query_arg[1:-1]
            if not query_arg:
                _print_error("Usage: ask <query>")
                continue
            _handle_ask(query_arg)
            continue

        try:
            parts = shlex.split(raw)
        except ValueError as exc:
            _print_error(f"Invalid input: {exc}")
            continue

        if not parts:
            continue

        cmd = parts[0].lower()
        args = parts[1:]

        if cmd == "apply":
            preview = False
            if args:
                if len(args) == 1 and args[0] == "--preview":
                    preview = True
                else:
                    _print_error("Usage: apply [--preview]")
                    continue
            _handle_apply(preview=preview)
        else:
            _handle_ask(raw)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """CLI entrypoint; launch shell when no explicit subcommand is provided."""
    if ctx.invoked_subcommand is None:
        _run_interactive_mode()


@app.command()
def analyze(repo_path: str = typer.Argument(..., help="Path to repository")) -> None:
    """Analyze repository and initialize vector/RAG state."""
    if not _handle_analyze(repo_path):
        raise typer.Exit(code=1)


@app.command()
def ask(query: str = typer.Argument(..., help="Question to ask Ragna")) -> None:
    """Ask a question and optionally generate an edit proposal."""
    if not _handle_ask(query):
        raise typer.Exit(code=1)


@app.command()
def apply(
    preview: bool = typer.Option(False, "--preview", help="Validate/apply in memory only; do not write file"),
) -> None:
    """Apply the last proposed edit in sandbox flow."""
    if not _handle_apply(preview=preview):
        raise typer.Exit(code=1)


@app.command("run")
def run_cmd(command: str = typer.Argument(..., help="Command to execute inside Docker sandbox")) -> None:
    """Run command inside Docker sandbox."""
    if not _handle_run(command):
        raise typer.Exit(code=1)


@app.command()
def status() -> None:
    """Show current CLI runtime state."""
    _print_status()


if __name__ == "__main__":
    app()
