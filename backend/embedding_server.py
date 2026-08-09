from __future__ import annotations

import os
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI
from pydantic import BaseModel, Field


class EmbedPayload(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=128)


class RerankPayload(BaseModel):
    query: str
    documents: list[str] = Field(min_length=1, max_length=64)


def _device() -> str:
    configured = os.environ.get("BID_WRITER_EMBEDDING_DEVICE", "auto")
    if configured != "auto":
        return configured
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


@lru_cache(maxsize=1)
def embedding_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(os.environ.get("BID_WRITER_EMBEDDING_MODEL", "BAAI/bge-m3"), device=_device())


@lru_cache(maxsize=1)
def reranker_model():
    from FlagEmbedding import FlagReranker

    return FlagReranker(
        os.environ.get("BID_WRITER_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
        use_fp16=_device() == "cuda",
        devices=[_device()],
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
        "embedding_loaded": embedding_model.cache_info().currsize == 1,
        "reranker_loaded": reranker_model.cache_info().currsize == 1,
    }


@app.post("/embed")
def embed(payload: EmbedPayload) -> dict:
    vectors = embedding_model().encode(payload.texts, normalize_embeddings=True).tolist()
    return {"vectors": vectors, "model": os.environ.get("BID_WRITER_EMBEDDING_MODEL", "BAAI/bge-m3")}


@app.post("/rerank")
def rerank(payload: RerankPayload) -> dict:
    pairs = [[payload.query, document] for document in payload.documents]
    scores = reranker_model().compute_score(pairs, normalize=True)
    if not isinstance(scores, list):
        scores = [float(scores)]
    return {"scores": [float(value) for value in scores], "model": os.environ.get("BID_WRITER_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")}
