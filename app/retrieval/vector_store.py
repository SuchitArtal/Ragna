"""FAISS vector store for Ragna."""

from __future__ import annotations

import logging
from typing import Dict, List

import faiss
import numpy as np

logger = logging.getLogger(__name__)


class VectorStore:
    """Simple FAISS-backed vector store."""

    def __init__(self, dim: int):
        self.dim = dim
        self.index = self.initialize_index(dim)
        self.metadata: List[Dict[str, object]] = []

    @staticmethod
    def initialize_index(dim: int) -> faiss.Index:
        """Initialize a FAISS index for inner product search."""
        logger.info("Initializing FAISS index with dim=%d", dim)
        return faiss.IndexFlatIP(dim)

    def add_embeddings(self, vectors: List[List[float]], metadata: List[Dict[str, object]]) -> None:
        """Add embeddings and aligned metadata to the index."""
        if len(vectors) != len(metadata):
            raise ValueError("Vectors and metadata must be the same length")
        if not vectors:
            return

        logger.info("Adding %d embeddings", len(vectors))
        self.index.add(np.array(vectors, dtype="float32"))
        self.metadata.extend(metadata)

    def save_index(self, path: str) -> None:
        """Save FAISS index to disk."""
        logger.info("Saving FAISS index to %s", path)
        faiss.write_index(self.index, path)

    def load_index(self, path: str) -> None:
        """Load FAISS index from disk."""
        logger.info("Loading FAISS index from %s", path)
        self.index = faiss.read_index(path)

    def search(self, query_vector: List[float], top_k: int = 5) -> List[Dict[str, object]]:
        """Search index and return top matches with scores."""
        if self.index.ntotal == 0:
            return []

        logger.info("Searching FAISS index top_k=%d", top_k)
        q = np.array([query_vector], dtype="float32")
        scores, indices = self.index.search(q, top_k)

        results: List[Dict[str, object]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            item = dict(self.metadata[idx])
            item["score"] = float(score)
            results.append(item)

        return results
