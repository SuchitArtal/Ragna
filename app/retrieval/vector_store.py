"""FAISS vector store for Ragna."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, TYPE_CHECKING, Any

# Use TYPE_CHECKING to allow type-checkers to resolve the optional native
# dependencies while avoiding hard import-time failures in editors/linters.
if TYPE_CHECKING:
    import faiss  # type: ignore
    import numpy as np  # type: ignore

# Perform runtime imports lazily so a helpful error message is raised if the
# native dependencies are missing at runtime.
try:
    import faiss  # type: ignore
except Exception:  # pragma: no cover - environment-dependent
    faiss = None  # type: ignore

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - environment-dependent
    np = None  # type: ignore

logger = logging.getLogger(__name__)


class VectorStore:
    """Simple FAISS-backed vector store."""

    def __init__(self, dim: int):
        self.dim = dim
        self.index = self.initialize_index(dim)
        self.metadata: List[Dict[str, object]] = []

    @staticmethod
    def initialize_index(dim: int) -> Any:
        """Initialize a FAISS index for inner product search."""
        if faiss is None:
            raise ImportError("faiss is required for VectorStore. Install faiss before using the vector store")
        logger.info("Initializing FAISS index with dim=%d", dim)
        return faiss.IndexFlatIP(dim)

    def add_embeddings(self, vectors: List[List[float]], metadata: List[Dict[str, object]]) -> None:
        """Add embeddings and aligned metadata to the index."""
        if len(vectors) != len(metadata):
            raise ValueError("Vectors and metadata must be the same length")
        if not vectors:
            return

        if np is None:
            raise ImportError("numpy is required for adding embeddings")
        logger.info("Adding %d embeddings", len(vectors))
        self.index.add(np.array(vectors, dtype="float32"))
        self.metadata.extend(metadata)

    def save_index(self, path: str) -> None:
        """Save FAISS index to disk."""
        if faiss is None:
            raise ImportError("faiss is required to save the index")
        logger.info("Saving FAISS index to %s", path)
        faiss.write_index(self.index, path)

    def load_index(self, path: str) -> None:
        """Load FAISS index from disk."""
        if faiss is None:
            raise ImportError("faiss is required to load the index")
        logger.info("Loading FAISS index from %s", path)
        self.index = faiss.read_index(path)

    def save_metadata(self, path: str) -> None:
        """Save metadata mapping (aligned list) to disk as JSON."""
        logger.info("Saving metadata to %s", path)
        p = Path(path)
        p.write_text(json.dumps(self.metadata, indent=2), encoding="utf-8")

    def load_metadata(self, path: str) -> None:
        """Load metadata mapping from disk."""
        logger.info("Loading metadata from %s", path)
        p = Path(path)
        if not p.exists():
            logger.warning("Metadata file %s not found", path)
            return
        try:
            self.metadata = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.exception("Failed to load metadata from %s: %s", path, exc)

    def search(self, query_vector: List[float], top_k: int = 5) -> List[Dict[str, object]]:
        """Search index and return top matches with scores."""
        if getattr(self.index, "ntotal", 0) == 0:
            return []

        if np is None:
            raise ImportError("numpy is required to perform searches")
        logger.info("Searching FAISS index top_k=%d", top_k)
        q = np.array([query_vector], dtype="float32")
        scores, indices = self.index.search(q, top_k)

        results: List[Dict[str, object]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            # Guard against inconsistent metadata length
            if idx < len(self.metadata):
                item = dict(self.metadata[idx])
            else:
                item = {"file_path": "", "chunk_id": None}
            item["score"] = float(score)
            results.append(item)

        return results