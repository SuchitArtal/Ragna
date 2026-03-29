"""Smoke test for agent -> guardrails -> sandbox flow.

This test reproduces the demo flow in CI-friendly way by mocking out
DockerManager so tests don't require Docker to be installed or running.

Test steps:
1. Create a temporary repository with a single Python file.
2. Build a unified-diff patch that modifies the file.
3. Use the agent_output helpers to build and validate the proposal.
4. Create a SandboxExecutor instance with a mocked DockerManager that
   simulates a successful container lifecycle.
5. Call `execute_edit()` and assert that the patch was applied in memory
   and guardrails allowed the edit.

This test focuses on integration between agent output validation,
guardrail pipeline, and in-memory patch application. It intentionally
does not execute commands inside Docker.
"""

import os
import sys
from tempfile import TemporaryDirectory
from pathlib import Path

# Ensure repository root is on sys.path so tests can import `app.*` modules.
sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.agents.agent_output import build_edit_proposal, parse_agent_output
from app.sandbox.sandbox_executor import SandboxExecutor


class DummyDockerManager:
    """Minimal stub for DockerManager used during tests.

    It simulates container creation, command execution, and cleanup
    without invoking the real Docker CLI.
    """

    def create_container(self, image: str, repo_path: str):
        return {"created": True, "container_id": "dummy", "errors": []}

    def run_command(self, container_id: str, command: str):
        return {"ran": True, "stdout": "ok", "stderr": "", "exit_code": 0}

    def stop_container(self, container_id: str):
        return {"cleaned": True, "errors": []}


def test_sandbox_flow_applies_patch_in_memory():
    with TemporaryDirectory() as td:
        repo = Path(td)
        target = repo / "hello.py"
        target.write_text('print("hello")\n', encoding="utf-8")

        # Simple unified-diff patch that replaces the print statement.
        patch = (
            "--- a/hello.py\n"
            "+++ b/hello.py\n"
            "@@ -1 +1 @@\n"
            "-print(\"hello\")\n"
            "+print(\"secure\")\n"
        )

        # Build and validate proposal using the agent helper.
        proposal = build_edit_proposal("hello.py", patch, "Make message secure", 0.9)
        validated = parse_agent_output(proposal)

        # Inject dummy docker manager to avoid external dependency.
        executor = SandboxExecutor(docker_manager=DummyDockerManager())
        result = executor.execute_edit(str(repo), validated)

        # Guardrails should allow the patch and patch_applier should have produced patched code.
        assert result.get("validation_result", {}).get("allowed") is True
        assert result.get("patched_code") is not None
        assert "secure" in result.get("patched_code")
