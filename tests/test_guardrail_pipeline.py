from app.guardrails.guardrail_pipeline import GuardrailPipeline

pipeline = GuardrailPipeline()

# Test with a valid edit proposal
edit_proposal = {
    "file_path": "app/retrieval/repo_loader.py",
    "proposed_patch": """--- a/app/retrieval/repo_loader.py
+++ b/app/retrieval/repo_loader.py
@@ -10,3 +10,4 @@
 def load_repository(repo_path: str):
     pass
+    # Added comment
""",
}

repo_root = "D:/Ragna"
result = pipeline.validate_edit(repo_root, edit_proposal)

print("Allowed:", result["allowed"])
print("Checks:", result["checks"])
print("Errors:", result["errors"])
print("Warnings:", result["warnings"])

# Test with a malicious edit
print("\n--- Testing malicious edit ---")
malicious_proposal = {
    "file_path": "../../etc/passwd",
    "proposed_patch": """--- a/test.py
+++ b/test.py
@@ -1,3 +1,3 @@
-print("hello")
+AWS_KEY="AKIAIOSFODNN7EXAMPLE"
""",
}

result2 = pipeline.validate_edit(repo_root, malicious_proposal)
print("Allowed:", result2["allowed"])
print("Checks:", result2["checks"])
print("Errors:", result2["errors"])
