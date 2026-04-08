"""Sandbox execution orchestrator for validated edit proposals."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict

from app.guardrails.guardrail_pipeline import GuardrailPipeline
from app.sandbox.patch_applier import PatchApplier
from app.sandbox.docker_manager import DockerManager

logger = logging.getLogger(__name__)


class SandboxExecutor:
    """Coordinate sandbox operations for safe edit execution.

    Responsibilities:
    - Receive validated edit proposals.
    - Apply patch content in memory.
    - Prepare an isolated execution plan/environment.
    - Capture execution outputs and errors.
    """

    def __init__(
        self,
        patch_applier: PatchApplier | None = None,
        docker_manager: DockerManager | None = None,
        guardrail_pipeline: GuardrailPipeline | None = None,
    ) -> None:
        """Initialize executor dependencies."""
        self.patch_applier = patch_applier or PatchApplier()
        self.docker_manager = docker_manager or DockerManager()
        self.guardrail_pipeline = guardrail_pipeline or GuardrailPipeline()
        logger.debug("SandboxExecutor initialized")

    def execute_edit(self, repo_root: str, edit_proposal: Dict[str, object]) -> Dict[str, object]:
        """Run guardrail validation and in-memory patch application.

        Args:
            repo_root: Repository root directory.
            edit_proposal: Agent proposal containing `file_path` and `proposed_patch`.

        Returns:
            Structured execution result with validation and execution feedback.
        """
        file_path = str(edit_proposal.get("file_path", ""))
        logger.info("Executing sandbox flow for file: %s", file_path)

        validation_result = self.guardrail_pipeline.validate_edit(repo_root, edit_proposal)
        if not validation_result.get("allowed", False):
            logger.warning("Guardrail validation rejected edit for %s", file_path)
            return {
                "success": False,
                "patched_code": "",
                "execution_output": "",
                "execution_error": "Edit rejected by guardrails",
                "validation_result": validation_result,
            }

        try:
            full_path = self._resolve_repo_path(repo_root, file_path)
            original_content = full_path.read_text(encoding="utf-8", errors="replace")
            patched_code = self.patch_applier.apply_patch(
                original_content,
                str(edit_proposal.get("proposed_patch", "")),
            )

            execution_output = ""
            execution_error = ""
            # Preview mode keeps the patch in memory only so we can validate behavior
            # without mutating the repository during a dry run.
            write_back_enabled = bool(edit_proposal.get("write_back", True))
            preview_only = bool(edit_proposal.get("preview", False))

            run_command = str(edit_proposal.get("execution_command", "")).strip()
            run_in_docker = bool(edit_proposal.get("run_in_docker", False))
            run_tests = bool(edit_proposal.get("run_tests", False))
            if run_tests and not run_command:
                run_command = str(edit_proposal.get("test_command", "pytest -q"))
                run_in_docker = bool(edit_proposal.get("run_tests_in_docker", True))
            if run_in_docker and run_command:
                # Docker is optional and only used when the proposal explicitly requests
                # an isolated runtime command such as tests or linting.
                image = str(edit_proposal.get("docker_image", "python:3.11"))
                container_result = self.docker_manager.create_container(image=image, repo_path=repo_root)
                if not container_result.get("created", False):
                    execution_error = "; ".join(container_result.get("errors", []))
                else:
                    container_id = str(container_result.get("container_id", ""))
                    run_result = self.docker_manager.run_command(container_id, run_command)
                    execution_output = str(run_result.get("stdout", ""))
                    execution_error = str(run_result.get("stderr", ""))
                    self.docker_manager.stop_container(container_id)

            written_file = ""
            if not execution_error and write_back_enabled and not preview_only:
                # Controlled write-back is the final step: the file is only persisted after
                # validation and any requested sandbox execution have succeeded.
                full_path.write_text(patched_code, encoding="utf-8")
                written_file = str(full_path)
                logger.info("Patched file written to repository: %s", written_file)
            elif preview_only:
                logger.info("Preview mode enabled; patch not written for %s", file_path)

            logger.info("Sandbox patch apply succeeded for %s", file_path)

            success = not bool(execution_error)
            return {
                "success": success,
                "patched_code": patched_code,
                "execution_output": execution_output,
                "execution_error": execution_error,
                "write_back": write_back_enabled and not preview_only,
                "preview": preview_only,
                "written_file": written_file,
                "tests_ran": run_tests,
                "command_ran": run_command,
                "validation_result": validation_result,
            }
        except Exception as exc:
            logger.exception("Sandbox execution failed for %s", file_path)
            return {
                "success": False,
                "patched_code": "",
                "execution_output": "",
                "execution_error": str(exc),
                "validation_result": validation_result,
            }

    def execute_validated_edit(self, proposal: Dict[str, object], original_content: str) -> Dict[str, object]:
        """Execute a validated edit proposal inside sandbox flow.

        Args:
            proposal: Guardrail-approved edit proposal.
            original_content: Current file content to patch in memory.

        Returns:
            Execution result with outputs, status, and diagnostics.
        """
        logger.info("Executing validated proposal in sandbox flow")

        patch_text = str(proposal.get("proposed_patch", ""))
        patch_result = self.patch_applier.apply_patch_in_memory(original_content, patch_text)

        # TODO: Prepare language/runtime-specific execution context.
        # TODO: Run commands in local simulation first, Docker later.
        # TODO: Capture stdout/stderr/exit code from execution run.
        return {
            "success": False,
            "patch_result": patch_result,
            "stdout": "",
            "stderr": "",
            "exit_code": None,
            "errors": ["Not implemented"],
            "warnings": [],
        }

    def prepare_execution_environment(self, workspace_path: str) -> Dict[str, object]:
        """Prepare sandbox execution environment.

        Args:
            workspace_path: Path used to stage sandbox execution.

        Returns:
            Environment preparation details.
        """
        logger.info("Preparing sandbox execution environment: %s", workspace_path)
        # TODO: Add local simulation setup for staged workspace.
        # TODO: Integrate DockerManager lifecycle in next phase.
        return {
            "ready": False,
            "workspace": workspace_path,
            "errors": ["Not implemented"],
            "warnings": [],
        }

    def _resolve_repo_path(self, repo_root: str, file_path: str) -> Path:
        """Resolve and enforce repository-bounded file path."""
        root = Path(repo_root).expanduser().resolve()
        target = (root / file_path).resolve()

        # Fallback: if proposal uses short path (e.g., "auth.py"), try repo_root/app/<file>.
        if not target.exists():
            alt_path = Path(os.path.join(str(root), "app", file_path)).resolve()
            if alt_path.exists():
                target = alt_path

        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError("Resolved path escapes repository root") from exc
        if not target.exists():
            raise FileNotFoundError(f"Target file not found: {target}")
        return target
