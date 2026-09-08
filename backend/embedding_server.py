from __future__ import annotations

import os
import threading
from contextlib import asynccontextmanager
from functools import lru_cache

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel, Field


class EmbedPayload(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=128)


class RerankPayload(BaseModel):
    query: str
    documents: list[str] = Field(min_length=1, max_length=64)


def _positive_int(name: str, default: int, maximum: int | None = None) -> int:
    value = max(1, int(os.environ.get(name, str(default))))
    return min(value, maximum) if maximum else value


def _device() -> str:
    configured = os.environ.get("BID_WRITER_EMBEDDING_DEVICE", "auto")
    if configured != "auto":
        return configured
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _fp16_enabled() -> bool:
    return _device() == "cuda" and os.environ.get("BID_WRITER_EMBEDDING_FP16", "1") == "1"


def _split_text(text: str) -> list[str]:
    """Split long knowledge units before tokenization while retaining local context."""
    text = str(text or "").strip()
    if not text:
        return [""]
    max_chars = _positive_int("BID_WRITER_EMBEDDING_MAX_CHARS", 4000)
    overlap = min(_positive_int("BID_WRITER_EMBEDDING_CHUNK_OVERLAP", 300), max_chars // 3)
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        hard_end = min(len(text), start + max_chars)
        end = hard_end
        if hard_end < len(text):
            search_start = start + max_chars // 2
            boundary = max(
                text.rfind("\n", search_start, hard_end),
                text.rfind("。", search_start, hard_end),
                text.rfind("；", search_start, hard_end),
            )
            if boundary >= search_start:
                end = boundary + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


@lru_cache(maxsize=1)
def embedding_model():
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(
        os.environ.get("BID_WRITER_EMBEDDING_MODEL", "BAAI/bge-m3"),
        device=_device(),
    )
    if _fp16_enabled():
        model.half()
    return model


@lru_cache(maxsize=1)
def reranker_model():
    from FlagEmbedding import FlagReranker

    return FlagReranker(
        os.environ.get("BID_WRITER_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
        use_fp16=_fp16_enabled(),
        devices=[_device()],
    )


# Two bounded inference lanes keep the RTX 4070 busy without allowing the
# 40-thread worker pool to create an unbounded CUDA memory spike.
_inference_slots = threading.BoundedSemaphore(
    _positive_int("BID_WRITER_EMBEDDING_CONCURRENCY", 2, maximum=4)
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    embedding_model()
    reranker_model()
    yield


app = FastAPI(title="Bid Writer BGE Service", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "device": _device(),
        "fp16": _fp16_enabled(),
        "batch_size": _positive_int("BID_WRITER_EMBEDDING_BATCH_SIZE", 4),
        "concurrency": _positive_int("BID_WRITER_EMBEDDING_CONCURRENCY", 2, maximum=4),
        "max_chars": _positive_int("BID_WRITER_EMBEDDING_MAX_CHARS", 4000),
        "embedding_loaded": embedding_model.cache_info().currsize == 1,
        "reranker_loaded": reranker_model.cache_info().currsize == 1,
    }


@app.post("/embed")
def embed(payload: EmbedPayload) -> dict:
    chunks: list[str] = []
    owners: list[int] = []
    for owner, text in enumerate(payload.texts):
        text_chunks = _split_text(text)
        chunks.extend(text_chunks)
        owners.extend([owner] * len(text_chunks))

    with _inference_slots:
        chunk_vectors = embedding_model().encode(
            chunks,
            batch_size=_positive_int("BID_WRITER_EMBEDDING_BATCH_SIZE", 4),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )

    # A long unit still maps to one Qdrant point. Mean-pool its normalized chunk
    # vectors, then normalize again so cosine distance remains well-defined.
    dimensions = int(chunk_vectors.shape[1])
    vectors = np.zeros((len(payload.texts), dimensions), dtype=np.float32)
    counts = np.zeros(len(payload.texts), dtype=np.int32)
    for owner, vector in zip(owners, chunk_vectors):
        vectors[owner] += vector.astype(np.float32, copy=False)
        counts[owner] += 1
    vectors /= np.maximum(counts, 1)[:, None]
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    vectors /= np.maximum(norms, 1e-12)
    return {
        "vectors": vectors.tolist(),
        "model": os.environ.get("BID_WRITER_EMBEDDING_MODEL", "BAAI/bge-m3"),
        "chunks": len(chunks),
    }


@app.post("/rerank")
def rerank(payload: RerankPayload) -> dict:
    pairs = [[payload.query, document] for document in payload.documents]
    with _inference_slots:
        scores = reranker_model().compute_score(
            pairs,
            batch_size=_positive_int("BID_WRITER_RERANK_BATCH_SIZE", 8),
            normalize=True,
        )
    if not isinstance(scores, list):
        scores = [float(scores)]
    return {
        "scores": [float(value) for value in scores],
        "model": os.environ.get("BID_WRITER_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
    }
