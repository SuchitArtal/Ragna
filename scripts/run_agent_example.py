# scripts/run_agent_example.py
import sys
from pathlib import Path
import logging
import json

# ensure repo root is on sys.path so "app" package imports resolve
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO)

from app.retrieval.indexer import index_repository
from app.retrieval.agent import Agent


def main():
    repo_path = str(REPO_ROOT)  # repo root
    vs, files = index_repository(repo_path, overwrite=False)
    print("Vectors:", getattr(vs.index, "ntotal", 0))

    # pass repo_root so Agent emits repo-relative paths in patches
    agent = Agent(vs, files, repo_root=str(REPO_ROOT))
    proposals = agent.run("fix TODOs in project", max_steps=5)
    print(json.dumps(proposals, indent=2))


if __name__ == "__main__":
    main()