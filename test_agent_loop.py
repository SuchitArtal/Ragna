import tempfile
from pathlib import Path

from app.retrieval.agent_loop import AgentLoop


def test_agent_proposes_edit_for_todo(tmp_path: Path):
    # Setup a tiny workspace with a file that contains a TODO
    workspace = tmp_path / "ws"
    workspace.mkdir()
    f = workspace / "sample.py"
    f.write_text("""# Sample file
# TODO: implement feature
def foo():
    pass
""")

    agent = AgentLoop(workspace_root=workspace, max_steps=10)
    res = agent.run_task("implement feature")
    assert isinstance(res, dict)
    assert res.get("solved") is True
    proposal = res.get("proposal")
    assert proposal is not None
    assert "sample.py" in proposal.file_path
    assert proposal.modification_description
