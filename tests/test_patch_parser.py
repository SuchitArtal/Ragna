from app.guardrails.patch_parser import PatchParser

mock_patch = """
--- a/test.py
+++ b/test.py
@@ -1,3 +1,3 @@
-print(\"hello\")
+print(\"hello secure\")
"""

parser = PatchParser()
result = parser.parse_patch(mock_patch, "test.py")

print(result)
