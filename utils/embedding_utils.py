import hashlib
from typing import List, Optional

import numpy as np

from config import config

EMBEDDING_DIM = config.EMBEDDING_DIM


def generate_embedding(text: str) -> List[float]:
    """
    Generates a DETERMINISTIC mock embedding vector for PostgreSQL pgvector.

    The previous implementation used Python's built-in hash(), which is
    randomized per-process (PYTHONHASHSEED), so the same text produced a
    different vector on every run. We now derive the seed from a SHA-256
    digest so the vector is stable across processes and restarts.

    NOTE: this is still a MOCK. It does not capture real semantic meaning.
    In production, replace the body with a call to a real embedding model
    (e.g. OpenAI text-embedding-3-small) and keep the same signature.
    """
    if not text:
        text = " "
    seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16) % (2 ** 32)
    rng = np.random.default_rng(seed)
    vec = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec.tolist()


def build_content_embedding_text(title: str, description: str, tags: Optional[List[str]] = None) -> str:
    """Builds the canonical text used to embed a catalog item."""
    parts = [title or "", description or ""]
    if tags:
        parts.append(" ".join(tags))
    return " ".join(p for p in parts if p).strip()


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    v1 = np.array(vec1)
    v2 = np.array(vec2)
    denom = np.linalg.norm(v1) * np.linalg.norm(v2)
    if denom == 0:
        return 0.0
    return float(np.dot(v1, v2) / denom)
