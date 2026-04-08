"""Ragna command-line interface with polished interactive UX."""

from __future__ import annotations

import logging
import re
import shlex
from pathlib import Path
from typing import Any, Dict, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

logger = logging.getLogger("ragna.cli")
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
}


class DeterministicSynthesisLLM:
	"""Deterministic fallback synthesizer implementing an LLM-like interface."""

	def generate(
		self,
		*,
		system_prompt: str,
		user_prompt: str,
		temperature: float = 0.0,
		max_tokens: int = 600,
	) -> str:
		del system_prompt, temperature, max_tokens
		sections = re.findall(
			r"\[Source\s+(\d+)\]\nFile:\s*(.*?)\nContent:\n(.*?)(?=\n\[Source\s+\d+\]|\Z)",
			user_prompt,
			flags=re.DOTALL,
		)

		if not sections:
			return "Not enough information"

		query_match = re.search(r"Question:\n(.*?)\n\nContext:", user_prompt, flags=re.DOTALL)
		query = query_match.group(1).strip().lower() if query_match else ""

		def _extract_anchor(content: str) -> str:
			for line in content.splitlines():
				stripped = line.strip()
				if stripped.startswith(("def ", "async def ", "class ")):
					return stripped
			for line in content.splitlines():
				stripped = line.strip()
				if stripped and not stripped.startswith("#"):
					return stripped[:140]
			return "implementation details"

		scored_sections: list[tuple[int, str, str, str]] = []
		query_terms = [t for t in re.findall(r"[a-zA-Z_]{3,}", query) if t not in {"how", "what", "where", "when", "why"}]

		for source_id, file_path, content in sections:
			haystack = f"{file_path}\n{content}".lower()
			score = sum(1 for term in query_terms if term in haystack)
			scored_sections.append((score, source_id, _extract_anchor(content), file_path))

		scored_sections.sort(key=lambda x: x[0], reverse=True)
		top = scored_sections[:3]
		if not top:
			return "Not enough information"

		source_ids = [sid for _, sid, _, _ in top]
		citations = ", ".join(f"[Source {sid}]" for sid in source_ids)

		route_anchor = next((a for _, _, a, p in top if "route" in p.lower() or "main.py" in p.lower()), top[0][2])
		service_anchor = next((a for _, _, a, p in top if "service" in p.lower()), top[0][2])
		logic_anchor = next((a for _, _, a, p in top if "util" in p.lower() or "model" in p.lower()), top[-1][2])

		return (
			"The request flow starts at API entrypoints and route handlers, then passes into service-layer logic "
			f"where core operations are orchestrated ({route_anchor}; {service_anchor}). "
			"Data validation and helper/model-level behavior support this path before the final response is returned "
			f"to the caller ({logic_anchor}). {citations}"
		)


class SimpleRAGEngine:
	"""Lightweight RAG placeholder backed by VectorStore search."""

	def __init__(
		self,
		vector_store: Any,
		repo_path: str,
		llm: Optional[Any] = None,
		response_mode: str = "explain",
	):
		self.vector_store = vector_store
		self.repo_path = str(Path(repo_path).resolve())
		self.repo_path_normalized = self._normalize_path(self.repo_path)
		self.llm = llm or DeterministicSynthesisLLM()
		self.response_mode = response_mode

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

	def answer(self, query: str) -> Dict[str, Any]:
		from app.retrieval.embeddings import embed_chunks

		lowered = query.lower().strip()
		if self._is_overview_query(lowered):
			return self._build_codebase_overview()

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

		raw_results = self.vector_store.search(query_vectors[0], top_k=8) if query_vectors else []
		ranked = self._rank_results(query, raw_results)
		results = ranked[:5]

		if results:
			if self.response_mode == "locate":
				top_files = [str(item.get("file_path", "")) for item in results[:3] if item.get("file_path")]
				answer = "Most relevant locations: " + ", ".join(top_files)
			else:
				context = self._build_context(results)
				answer = self._synthesize_answer(query, context)
		else:
			answer = "No relevant context found yet."

		proposal = None
		if "fix" in lowered or "bug" in lowered:
			target_file = Path(results[0].get("file_path", "test.py")).name if results else "test.py"
			proposal = {
				"action": "edit_file",
				"file_path": target_file,
				"proposed_patch": """--- a/test.py
+++ b/test.py
@@ -1 +1 @@
-print(\"hello\")
+print(\"secure\")
""",
				"reasoning": "Placeholder proposal from ask flow",
				"confidence": 0.5,
			}

		return {"answer": answer, "results": results, "proposal": proposal}

	def _build_context(self, results: list[dict]) -> str:
		"""Build grounded synthesis context from retrieved code chunks."""
		blocks: list[str] = []

		for idx, item in enumerate(results, start=1):
			file_path = str(item.get("file_path", ""))
			code_chunk = str(item.get("code", "")).strip()
			if not code_chunk:
				code_chunk = "# code snippet unavailable in metadata"

			# Keep context size bounded for deterministic behavior.
			code_chunk = code_chunk[:2000]

			block = (
				f"[Source {idx}]\n"
				f"File: {file_path}\n"
				"Content:\n"
				f"{code_chunk}"
			)
			blocks.append(block)

		return "\n\n".join(blocks)

	def _synthesize_answer(self, query: str, context: str) -> str:
		"""Generate a grounded natural-language explanation from retrieved context."""
		if not context.strip():
			return "Not enough information"

		system_prompt = (
    "You are a senior software engineer analyzing a real-world codebase.\n\n"

    "Your task is to answer developer questions about the codebase accurately, clearly, and specifically.\n\n"

    "PRIMARY OBJECTIVE:\n"
    "- Directly answer the user's question based ONLY on provided context.\n"
    "- Tailor the response to the exact type of question being asked.\n\n"

    "GROUNDING RULES:\n"
    "- Use ONLY the provided retrieved context.\n"
    "- Do NOT invent files, functions, logic, or behavior.\n"
    "- If context is insufficient, respond exactly with: 'Not enough information.'\n\n"

    "RESPONSE RULES:\n"
    "- Do NOT describe sources individually.\n"
    "- Do NOT say phrases like 'Source 1 shows' or 'According to Source 2'.\n"
    "- Synthesize information naturally into one cohesive answer.\n"
    "- Be specific to THIS codebase, not generic.\n"
    "- If the answer could apply to any backend project, rewrite it to be more specific.\n\n"

    "QUESTION HANDLING:\n"
    "- If asked HOW something works → explain flow/interaction.\n"
    "- If asked WHAT something does → explain purpose/responsibility.\n"
    "- If asked WHERE something is → mention exact file/module.\n"
    "- If asked to LIST items → provide structured list.\n"
    "- If asked to FIND BUGS/ISSUES → identify concrete technical concerns.\n\n"

    "STYLE:\n"
    "- Be concise but technically meaningful.\n"
    "- Write like explaining to another engineer.\n"
    "- Prefer clarity over verbosity.\n\n"

    "CITATIONS:\n"
    "- Use citations only when helpful.\n"
    "- Format citations as [Source 1], [Source 2].\n"
)

		user_prompt = (
			f"Question:\n{query}\n\n"
			"Context:\n"
			f"{context}\n\n"
			"Task:\n"
			"Explain the answer by synthesizing the context.\n\n"
			"Focus on:\n"
			"- How the system works\n"
			"- Flow of data and control\n"
			"- Interaction between components\n\n"
			"DO NOT:\n"
			"- List sources individually\n"
			"- Repeat code snippets unnecessarily\n\n"
			"Write a clear, cohesive explanation.\n\n"
			"Think step-by-step internally about how the system works,\n"
			"but only output the final explanation."
		)

		try:
			response = self.llm.generate(
				system_prompt=system_prompt,
				user_prompt=user_prompt,
				temperature=0.0,
				max_tokens=700,
			)
			answer = str(response).strip()
			if not answer:
				return "Not enough information"
			return answer
		except Exception as exc:
			logger.warning("Synthesis fallback due to LLM error: %s", exc)
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

	def _rank_results(self, query: str, results: list[dict]) -> list[dict]:
		"""Deduplicate and rerank results using simple keyword-aware scoring."""
		query_terms = [term for term in query.lower().split() if len(term) > 2]
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
			item_copy = dict(item)
			item_copy["score"] = base_score + keyword_boost
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


def _guardrail_block_reason_for_query(query: str) -> Optional[str]:
	"""Block obvious unsafe edit-style prompts before proposal/apply steps."""
	stripped = query.strip()
	lowered = stripped.lower()

	# Strong signals of unsafe path manipulation.
	if re.search(r"\.\.[/\\]", stripped) or re.search(r"(^|\s)/etc/|(^|\s)c:[/\\]windows", lowered):
		return "Unsafe path operation detected in prompt"

	# Secret-like assignment in natural language prompts (e.g., API_KEY=\"123456\").
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
		_print_info("⏳ Thinking...")
		response = rag_engine.answer(query)
		answer = response.get("answer", "")
		proposal = response.get("proposal")
		results = response.get("results", [])

		console.print(
			Panel.fit(
				f"[bold cyan]💡 Answer:[/bold cyan]\n{answer}",
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

	try:
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


def _prefer_src_cli_app() -> None:
	"""Prefer src/ragna/cli.py implementation when present to avoid dual-CLI drift."""
	global app
	try:
		import importlib.util

		src_cli_path = Path(__file__).resolve().parents[1] / "src" / "ragna" / "cli.py"
		if not src_cli_path.exists():
			return

		spec = importlib.util.spec_from_file_location("_ragna_src_cli", src_cli_path)
		if spec is None or spec.loader is None:
			return

		module = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(module)
		src_app = getattr(module, "app", None)
		if src_app is not None:
			app = src_app
	except Exception as exc:
		logger.warning("Falling back to local ragna.cli implementation: %s", exc)


_prefer_src_cli_app()


if __name__ == "__main__":
	app()
