"""Embeddings module for Ragna."""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple

from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

MODEL_NAME = "all-MiniLM-L6-v2"
DEFAULT_BATCH_SIZE = 32


def embed_chunks(
    chunks: List[Dict[str, object]],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    model_name: str = MODEL_NAME,
) -> Tuple[List[List[float]], List[Dict[str, object]]]:
    """Embed parsed code chunks into vectors.

    Args:
        chunks: List of parsed chunk dictionaries.
        batch_size: Batch size for embedding.
        model_name: SentenceTransformer model name.

    Returns:
        A tuple of (vectors, metadata) aligned by index.
    """
    if not chunks:
        return [], []

    logger.info("Loading embedding model: %s", model_name)
    model = SentenceTransformer(model_name)

    texts = [str(chunk.get("code", "")) for chunk in chunks]
    metadata = [
        {
            "chunk_id": chunk.get("chunk_id"),
            "file_path": chunk.get("file_path"),
            "type": chunk.get("type"),
            "name": chunk.get("name"),
            "class_name": chunk.get("class_name", ""),
            "function_name": chunk.get("function_name", ""),
        }
        for chunk in chunks
    ]

    vectors: List[List[float]] = []
    total = len(texts)

    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        logger.info("Embedding chunks %d-%d of %d", start + 1, end, total)
        batch_vectors = model.encode(
            texts[start:end],
            batch_size=batch_size,
            show_progress_bar=False,
            normalize_embeddings=False,
        )
        vectors.extend(batch_vectors.tolist())

    logger.info("Generated %d embeddings", len(vectors))
    return vectors, metadata
