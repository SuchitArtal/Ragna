"""Run a small demo of AgentLoop against a temporary workspace.

Creates a file containing a TODO and runs the agent to demonstrate it returns
an EditProposal and logs its steps.
"""
from pathlib import Path
import tempfile
import json
import sys

# Make repo root importable when running this script directly.
# This allows `from app.retrieval.agent_loop import AgentLoop` to work.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.retrieval.agent_loop import AgentLoop


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        sample = ws / "sample.py"
        sample.write_text("""# Sample file
# TODO: implement feature
def foo():
    pass
""")

        agent = AgentLoop(workspace_root=ws, max_steps=20)
        result = agent.run_task("implement feature")

        if result.get("solved"):
            proposal = result["proposal"]
            print("PROPOSAL JSON:")
            print(proposal.to_json())
        else:
            print("No proposal; task not solved.")

        print("\nAGENT LOG:")
        for entry in agent.log:
            print(entry)


if __name__ == "__main__":
    main()
