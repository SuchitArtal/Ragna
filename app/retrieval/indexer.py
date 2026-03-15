"""Repository indexing orchestration for Ragna.

Responsibilities:
- Build/restore a FAISS index and aligned metadata stored under a repo-local index directory.
- Avoid re-embedding if an index already exists unless overwrite=True.
- Expose index_repository(repo_path, index_dir, overwrite) function.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Dict, Tuple

from .repo_loader import load_repository
from .parser import parse_repository
from .embeddings import embed_chunks, MODEL_NAME
from .vector_store import VectorStore

logger = logging.getLogger(__name__)

DEFAULT_INDEX_DIR = ".ragna_index"
INDEX_FILENAME = "index.faiss"
METADATA_FILENAME = "metadata.json"


def index_repository(repo_path: str, index_dir: str = DEFAULT_INDEX_DIR, overwrite: bool = False) -> Tuple[VectorStore, List[Dict[str, str]]]:
    """Index a local repository and persist the FAISS index + metadata.

    Args:
        repo_path: path to local repo
        index_dir: directory name under repo_path where index files are stored
        overwrite: if True, rebuild regardless of existing index

    Returns:
        (vector_store, files) where files is the list returned by load_repository
    """
    repo_root = Path(repo_path).expanduser().resolve()
    if not repo_root.exists() or not repo_root.is_dir():
        raise ValueError(f"Repository path does not exist or is not a directory: {repo_root}")

    out_dir = repo_root / index_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    idx_file = out_dir / INDEX_FILENAME
    meta_file = out_dir / METADATA_FILENAME

    files = load_repository(str(repo_root))

    # If index exists and we aren't forcing overwrite, load and return
    if idx_file.exists() and meta_file.exists() and not overwrite:
        logger.info("Found existing index at %s; loading", out_dir)
        vs = VectorStore(dim=1)
        try:
            vs.load_index(str(idx_file))
            vs.load_metadata(str(meta_file))
            # Update VectorStore.dim from loaded FAISS index if available
            try:
                vs.dim = getattr(vs.index, "d", vs.dim)
            except Exception:
                # keep existing dim if attribute unavailable
                pass
        except Exception as exc:
            logger.exception("Failed to load existing index; will rebuild: %s", exc)
        else:
            logger.info("Loaded index with %d vectors", getattr(vs.index, "ntotal", 0))
            return vs, files

    # Build new index
    logger.info("Parsing repository into chunks for embedding")
    chunks = parse_repository(files)
    if not chunks:
        logger.warning("No chunks produced for repository %s; returning empty VectorStore", repo_root)
        return VectorStore(dim=1), files

    vectors, metadata = embed_chunks(chunks, model_name=MODEL_NAME)
    if not vectors:
        logger.warning("Embedding produced no vectors; returning empty VectorStore")
        return VectorStore(dim=1), files

    dim = len(vectors[0])
    vs = VectorStore(dim=dim)
    vs.add_embeddings(vectors, metadata)

    try:
        vs.save_index(str(idx_file))
        vs.save_metadata(str(meta_file))
        logger.info("Saved index and metadata to %s", out_dir)
    except Exception as exc:
        logger.exception("Failed to persist index/metadata: %s", exc)

    return vs, files