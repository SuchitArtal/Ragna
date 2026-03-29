from app.retrieval.repo_loader import load_repository
from app.retrieval.parser import parse_repository
from test_config import REPO_PATH

repo = load_repository(REPO_PATH)
chunks = parse_repository(repo)

print("Total chunks:", len(chunks))
print(chunks[0]["type"], chunks[0]["name"]) if chunks else None
