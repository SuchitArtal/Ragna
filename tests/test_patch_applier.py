import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.sandbox.patch_applier import PatchApplier

original = 'print("hello")'

patch = """
--- a/test.py
+++ b/test.py
@@ -1 +1 @@
-print("hello")
+print("secure")
"""

applier = PatchApplier()
result = applier.apply_patch(original, patch)

print(result)
