"""Docker lifecycle manager for sandbox isolation."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)


class DockerManager:
    """Manage Docker resources for isolated sandbox execution.

    Uses Docker CLI via subprocess to create containers, execute commands,
    and clean up resources.
    """

    def __init__(self, mount_target: str = "/workspace") -> None:
        """Initialize Docker manager.

        Args:
            mount_target: Container path where repository is mounted.
        """
        self.mount_target = mount_target
        logger.debug("DockerManager initialized")

    def create_container(self, image: str, repo_path: str) -> Dict[str, object]:
        """Create an isolated container for execution.

        Args:
            image: Docker image reference.
            repo_path: Host repository directory to mount.

        Returns:
            Creation result with container id.
        """
        host_repo = Path(repo_path).expanduser().resolve()
        if not host_repo.exists() or not host_repo.is_dir():
            error = f"Repository path is invalid: {host_repo}"
            logger.error(error)
            return {
                "created": False,
                "container_id": None,
                "errors": [error],
            }

        logger.info("Creating docker container for image=%s", image)
        cmd = [
            "docker",
            "run",
            "-d",
            "--rm",
            "-v",
            f"{host_repo}:{self.mount_target}",
            "-w",
            self.mount_target,
            image,
            "tail",
            "-f",
            "/dev/null",
        ]

        completed = self._run_cli(cmd)
        if completed["ok"]:
            container_id = completed["stdout"].strip()
            return {
                "created": True,
                "container_id": container_id,
                "errors": [],
            }

        error_message = completed["stderr"] or "Failed to create container"
        if "context deadline exceeded" in error_message.lower():
            error_message = (
                f"{error_message}\nHint: Docker could not pull the image (network timeout). "
                "Ensure internet access/VPN/proxy is configured, or pre-pull the image and retry."
            )

        return {
            "created": False,
            "container_id": None,
            "errors": [error_message],
        }

    def run_command(self, container_id: str, command: str) -> Dict[str, object]:
        """Run a command in an existing container.

        Args:
            container_id: Container identifier.
            command: Command string to execute.

        Returns:
            Command execution placeholder result.
        """
        logger.info("Running command in container=%s", container_id)
        cmd = ["docker", "exec", container_id, "sh", "-lc", command]
        completed = self._run_cli(cmd)

        return {
            "ran": completed["ok"],
            "stdout": completed["stdout"],
            "stderr": completed["stderr"],
            "exit_code": completed["exit_code"],
            "errors": [] if completed["ok"] else [completed["stderr"] or "Command failed"],
        }

    def stop_container(self, container_id: str) -> Dict[str, object]:
        """Stop and remove an execution container.

        Args:
            container_id: Container identifier.

        Returns:
            Cleanup status result.
        """
        logger.info("Stopping/removing container id=%s", container_id)
        stop_result = self._run_cli(["docker", "stop", container_id])
        # With `docker run --rm`, successful `docker stop` auto-removes container.
        # Only call `docker rm` when stop did not succeed.
        rm_result = {"ok": True, "stdout": "", "stderr": "", "exit_code": 0}
        if not stop_result["ok"]:
            rm_result = self._run_cli(["docker", "rm", container_id], log_errors=False)

        stop_missing = self._is_no_such_container(stop_result.get("stderr", ""))
        rm_missing = self._is_no_such_container(rm_result.get("stderr", ""))

        cleaned = stop_result["ok"] or rm_result["ok"] or stop_missing or rm_missing
        errors = []
        if not stop_result["ok"] and not stop_missing and stop_result["stderr"]:
            errors.append(stop_result["stderr"])
        if not rm_result["ok"] and not rm_missing and rm_result["stderr"]:
            errors.append(rm_result["stderr"])

        return {
            "cleaned": cleaned,
            "errors": errors,
        }

    def _is_no_such_container(self, stderr: str) -> bool:
        """Return True when Docker reports missing container during cleanup."""
        message = (stderr or "").lower()
        return "no such container" in message

    def _run_cli(self, command: list[str], log_errors: bool = True) -> Dict[str, object]:
        """Execute docker CLI command and capture outputs."""
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )
            stdout = proc.stdout.strip()
            stderr = proc.stderr.strip()
            ok = proc.returncode == 0
            if not ok and log_errors:
                logger.error("Docker command failed (%s): %s", proc.returncode, " ".join(command))
            return {
                "ok": ok,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": proc.returncode,
            }
        except FileNotFoundError:
            msg = "Docker CLI not found. Ensure Docker is installed and on PATH."
            logger.error(msg)
            return {
                "ok": False,
                "stdout": "",
                "stderr": msg,
                "exit_code": 127,
            }
        except Exception as exc:
            msg = str(exc)
            logger.exception("Unexpected Docker CLI error")
            return {
                "ok": False,
                "stdout": "",
                "stderr": msg,
                "exit_code": 1,
            }
