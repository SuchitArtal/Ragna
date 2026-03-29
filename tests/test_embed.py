from app.retrieval.repo_loader import load_repository
from app.retrieval.parser import parse_repository
from app.retrieval.embeddings import embed_chunks
from test_config import REPO_PATH

repo = load_repository(REPO_PATH)
chunks = parse_repository(repo)

vectors, metadata = embed_chunks(chunks)

print("chunks:", len(chunks))
print("embeddings:", len(vectors))
