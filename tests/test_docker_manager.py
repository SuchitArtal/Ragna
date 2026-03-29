import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.sandbox.docker_manager import DockerManager


def main() -> None:
    docker = DockerManager()

    created = docker.create_container(
        image="python:3.11",
        repo_path="D:/Ragna",
    )

    if not created.get("created"):
        print("Container creation failed:", created.get("errors"))
        return

    container_id = str(created.get("container_id"))

    output = docker.run_command(container_id, "python --version")
    print(output.get("stdout") or output)

    stopped = docker.stop_container(container_id)
    if not stopped.get("cleaned"):
        print("Container cleanup warnings:", stopped.get("errors"))


if __name__ == "__main__":
    main()
