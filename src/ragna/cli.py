"""Ragna command-line interface with polished interactive UX."""

from __future__ import annotations

import logging
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

logger = logging.getLogger("ragna.cli")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

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

    def __init__(self, vector_store: Any):
        self.vector_store = vector_store

    def answer(self, query: str) -> Dict[str, Any]:
        _ensure_project_root_on_path()
        from app.retrieval.embeddings import embed_chunks

        query_vectors, _ = embed_chunks(
            [
                {
                    "chunk_id": "query",
                    "file_path": "",
                    "type": "query",
                    "name": "query",
                    "code": query,
                }
            ]
        )

        results = self.vector_store.search(query_vectors[0], top_k=3) if query_vectors else []
        if results:
            top_files = [str(r.get("file_path", "")) for r in results if r.get("file_path")]
            answer = "Most relevant locations: " + ", ".join(top_files[:3])
        else:
            answer = "No relevant context found yet."

        proposal = None
        lowered = query.lower()
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
        rag_engine = SimpleRAGEngine(vector_store)

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


def _handle_apply() -> bool:
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
        _ensure_project_root_on_path()
        from app.sandbox.sandbox_executor import SandboxExecutor

        _print_info("⏳ Applying edit in sandbox...")
        executor = state.get("executor") or SandboxExecutor()
        state["executor"] = executor
        state["docker_manager"] = getattr(executor, "docker_manager", None)

        result = executor.execute_edit(repo_path, proposal)
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
        if lowered == "help":
            _show_help()
            continue
        if lowered == "history":
            _show_history()
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

        if cmd == "analyze":
            if not args:
                _print_error("Usage: analyze <path>")
                continue
            _handle_analyze(args[0])
        elif cmd == "apply":
            _handle_apply()
        elif cmd == "run":
            if not args:
                _print_error("Usage: run <command>")
                continue
            _handle_run(" ".join(args))
        elif cmd == "ask":
            if not args:
                _print_error("Usage: ask <query>")
                continue
            _handle_ask(" ".join(args))
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
def apply() -> None:
    """Apply the last proposed edit in sandbox flow."""
    if not _handle_apply():
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
