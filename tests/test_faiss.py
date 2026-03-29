from app.retrieval.repo_loader import load_repository
from app.retrieval.parser import parse_repository
from app.retrieval.embeddings import embed_chunks
from app.retrieval.vector_store import VectorStore
from test_config import REPO_PATH

repo = load_repository(REPO_PATH)
chunks = parse_repository(repo)
vectors, metadata = embed_chunks(chunks)

store = VectorStore(dim=len(vectors[0]))
store.add_embeddings(vectors, metadata)

# test search
query = "database connection"
q_vec, _ = embed_chunks([
    {
        "chunk_id": "q",
        "file_path": "",
        "type": "query",
        "name": "query",
        "code": query,
    }
])

results = store.search(q_vec[0], top_k=3)

print("\nTop results:")
for r in results:
    print(r.get("name"), r.get("file_path"))
