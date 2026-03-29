import sys
import tempfile
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.sandbox.sandbox_executor import SandboxExecutor


with tempfile.TemporaryDirectory() as tmp_dir:
    repo_root = Path(tmp_dir)
    target = repo_root / "test.py"
    target.write_text('print("hello")\n', encoding="utf-8")

    executor = SandboxExecutor()

    edit = {
        "file_path": "test.py",
        "proposed_patch": """
--- a/test.py
+++ b/test.py
@@ -1 +1 @@
-print("hello")
+print("secure")
""",
    }

    result = executor.execute_edit(str(repo_root), edit)
    print(result)
