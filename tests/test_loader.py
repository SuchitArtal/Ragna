from app.retrieval.repo_loader import load_repository
from test_config import REPO_PATH

files = load_repository(REPO_PATH)

print(f"Loaded {len(files)} files")
print(files[0]["file_name"]) if files else None
