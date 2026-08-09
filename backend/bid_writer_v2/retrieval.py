from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import httpx

from .database import Database
from .settings import Settings
from .storage import ObjectStorage
from .utils import content_hash, parse_json


def tokenize(text: str) -> list[str]:
    text = text.lower()
    latin = re.findall(r"[a-z0-9][a-z0-9._-]+", text)
    chinese_blocks = re.findall(r"[\u4e00-\u9fff]+", text)
    tokens: list[str] = list(latin)
    try:
        import jieba

        for block in chinese_blocks:
            tokens.extend(word.strip() for word in jieba.cut(block) if len(word.strip()) >= 2)
    except ImportError:
        for block in chinese_blocks:
            tokens.extend(block[index:index + 2] for index in range(max(1, len(block) - 1)))
    return tokens or [text.strip()]


def bm25_scores(query_tokens: list[str], documents: list[list[str]], k1: float = 1.5, b: float = 0.75) -> list[float]:
    if not documents:
        return []
    document_count = len(documents)
    average_length = sum(len(item) for item in documents) / document_count or 1
    frequencies = Counter(token for document in documents for token in set(document))
    output: list[float] = []
    for document in documents:
        counts = Counter(document)
        score = 0.0
        for token in query_tokens:
            frequency = counts[token]
            if not frequency:
                continue
            inverse = math.log(1 + (document_count - frequencies[token] + 0.5) / (frequencies[token] + 0.5))
            score += inverse * frequency * (k1 + 1) / (frequency + k1 * (1 - b + b * len(document) / average_length))
        output.append(score)
    return output


class EmbeddingClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def available(self) -> bool:
        return bool(self.settings.embedding_url)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.available or not texts:
            return []
        response = httpx.post(f"{self.settings.embedding_url}/embed", json={"texts": texts}, timeout=120)
        response.raise_for_status()
        return response.json()["vectors"]

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        if not self.available or not documents:
            return []
        response = httpx.post(
            f"{self.settings.embedding_url}/rerank",
            json={"query": query, "documents": documents},
            timeout=120,
        )
        response.raise_for_status()
        return [float(value) for value in response.json()["scores"]]


class HybridRetrievalService:
    def __init__(self, db: Database, settings: Settings, storage: ObjectStorage) -> None:
        self.db = db
        self.settings = settings
        self.storage = storage
        self.embedding = EmbeddingClient(settings)
        self._index_cache: dict[str, Any] = {}

    def _published_rows(self, industry: str = "", unit_type: str = "", classification: str = "") -> list[dict[str, Any]]:
        clauses = ["p.status='published'"]
        params: list[Any] = []
        if industry:
            clauses.append("u.industry=?")
            params.append(industry)
        if unit_type:
            clauses.append("u.unit_type=?")
            params.append(unit_type)
        if classification:
            clauses.append("u.classification=?")
            params.append(classification)
        return self.db.rows(
            f"""
            SELECT p.id AS publication_id,p.publication_version,p.file_path,p.content_hash,
                u.id AS unit_id,u.title,u.unit_type,u.industry,u.tags_json,u.classification,v.content
            FROM knowledge_publications p JOIN knowledge_units u ON u.id=p.unit_id
            JOIN knowledge_versions v ON v.id=p.version_id
            WHERE {' AND '.join(clauses)} ORDER BY u.id
            """,
            params,
        )

    def build_index(self, progress=None, cancelled=None) -> dict[str, Any]:
        progress = progress or (lambda *_args, **_kwargs: None)
        cancelled = cancelled or (lambda: False)
        rows = self._published_rows()
        progress("indexing", 10, "读取已发布知识", {"publications": len(rows)})
        if cancelled():
            return {"cancelled": True}
        corpus = [
            {
                **row,
                "tags": parse_json(row.pop("tags_json", "[]"), []),
                "tokens": tokenize(f"{row['title']} {row['content']}"),
            }
            for row in rows
        ]
        source_hash = content_hash("|".join(str(row["content_hash"]) for row in rows) or "empty")
        version = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{source_hash[:10]}"
        collection = f"published_knowledge_{version.replace('-', '_')}"
        object_key = f"indexes/{version}/bm25.json"
        stored = self.storage.put_bytes(object_key, json.dumps(corpus, ensure_ascii=False).encode("utf-8"), "application/json")
        progress("embedding", 35, "生成知识向量")
        dense_indexed = 0
        if rows and self.settings.qdrant_url and self.embedding.available and not cancelled():
            vectors = self.embedding.embed([f"{row['title']}\n{row['content']}" for row in rows])
            if vectors:
                from qdrant_client import QdrantClient, models

                client = QdrantClient(url=self.settings.qdrant_url, timeout=60)
                client.create_collection(
                    collection_name=collection,
                    vectors_config=models.VectorParams(size=len(vectors[0]), distance=models.Distance.COSINE),
                )
                client.upsert(
                    collection_name=collection,
                    points=[
                        models.PointStruct(
                            id=int(row["unit_id"]),
                            vector=vector,
                            payload={
                                "publication_id": row["publication_id"],
                                "industry": row["industry"],
                                "unit_type": row["unit_type"],
                                "classification": row["classification"],
                                "content_hash": row["content_hash"],
                            },
                        )
                        for row, vector in zip(rows, vectors)
                    ],
                )
                dense_indexed = len(vectors)
        metrics = {"bm25_documents": len(rows), "dense_documents": dense_indexed}
        with self.db.connect() as conn:
            conn.execute("UPDATE retrieval_indexes SET status='superseded' WHERE status='active'")
            cursor = conn.execute(
                """
                INSERT INTO retrieval_indexes(
                    version,embedding_model,reranker_model,bm25_object_key,qdrant_collection,
                    publication_count,content_hash,status,metrics_json,activated_at
                ) VALUES (?,?,?,?,?,?,?,'active',?,CURRENT_TIMESTAMP)
                """,
                (
                    version,
                    self.settings.embedding_model,
                    self.settings.reranker_model,
                    object_key,
                    collection,
                    len(rows),
                    source_hash,
                    json.dumps(metrics, ensure_ascii=False),
                ),
            )
            index_id = int(cursor.lastrowid)
        self._index_cache = {"version": version, "corpus": corpus}
        progress("completed", 100, "检索索引已激活", metrics)
        return {"id": index_id, "version": version, "object": stored, **metrics}

    def _active_index(self) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        index = self.db.row("SELECT * FROM retrieval_indexes WHERE status='active' ORDER BY id DESC LIMIT 1")
        if not index:
            return None, []
        if self._index_cache.get("version") == index["version"]:
            return index, self._index_cache["corpus"]
        try:
            with self.storage.open(index["bm25_object_key"]) as handle:
                corpus = json.loads(handle.read().decode("utf-8"))
        except Exception:
            corpus = []
        self._index_cache = {"version": index["version"], "corpus": corpus}
        return index, corpus

    def search(
        self,
        query: str,
        industry: str = "",
        unit_type: str = "",
        limit: int = 12,
        *,
        project_id: int | None = None,
        classification: str = "internal",
        created_by: int | None = None,
    ) -> list[dict[str, Any]]:
        started = time.perf_counter()
        limit = max(1, min(int(limit), 50))
        index, corpus = self._active_index()
        if not index or not corpus:
            corpus = [
                {**row, "tags": parse_json(row.pop("tags_json", "[]"), []), "tokens": tokenize(f"{row['title']} {row['content']}")}
                for row in self._published_rows(industry, unit_type, classification)
            ]
            index = {"version": "live-lexical", "qdrant_collection": ""}
        eligible = [
            row for row in corpus
            if (not industry or row.get("industry") == industry)
            and (not unit_type or row.get("unit_type") == unit_type)
            and row.get("classification", "internal") in {classification, "public"}
        ]
        lexical_scores = bm25_scores(tokenize(query), [row.get("tokens") or tokenize(f"{row['title']} {row['content']}") for row in eligible])
        lexical_rank = [index for index, score in sorted(enumerate(lexical_scores), key=lambda item: item[1], reverse=True) if score > 0][:60]
        dense_ids: list[int] = []
        if self.settings.qdrant_url and self.embedding.available and index.get("qdrant_collection") and eligible:
            try:
                from qdrant_client import QdrantClient, models

                vector = self.embedding.embed([query])[0]
                filters = []
                if industry:
                    filters.append(models.FieldCondition(key="industry", match=models.MatchValue(value=industry)))
                if unit_type:
                    filters.append(models.FieldCondition(key="unit_type", match=models.MatchValue(value=unit_type)))
                response = QdrantClient(url=self.settings.qdrant_url, timeout=20).query_points(
                    collection_name=index["qdrant_collection"],
                    query=vector,
                    query_filter=models.Filter(must=filters) if filters else None,
                    limit=60,
                    with_payload=True,
                )
                dense_ids = [int(point.id) for point in response.points]
            except Exception:
                dense_ids = []
        row_by_id = {int(row["unit_id"]): row for row in eligible}
        rrf: dict[int, float] = {}
        channels: dict[int, dict[str, Any]] = {}
        for rank, position in enumerate(lexical_rank, 1):
            unit_id = int(eligible[position]["unit_id"])
            rrf[unit_id] = rrf.get(unit_id, 0) + 1 / (60 + rank)
            channels.setdefault(unit_id, {})["bm25"] = {"rank": rank, "score": lexical_scores[position]}
        for rank, unit_id in enumerate(dense_ids, 1):
            if unit_id not in row_by_id:
                continue
            rrf[unit_id] = rrf.get(unit_id, 0) + 1 / (60 + rank)
            channels.setdefault(unit_id, {})["dense"] = {"rank": rank}
        fused = sorted(rrf, key=rrf.get, reverse=True)[:30]
        if not fused and eligible:
            fused = [int(row["unit_id"]) for row in eligible[:limit]]
        rerank_scores: list[float] = []
        try:
            rerank_scores = self.embedding.rerank(query, [f"{row_by_id[item]['title']}\n{row_by_id[item]['content']}" for item in fused])
        except Exception:
            rerank_scores = []
        if rerank_scores:
            ranked = sorted(zip(fused, rerank_scores), key=lambda item: item[1], reverse=True)
            ordered = [item for item, score in ranked if score >= self.settings.reranker_min_score]
            rerank_map = dict(zip(fused, rerank_scores))
        else:
            ordered = fused
            rerank_map = {}
        results: list[dict[str, Any]] = []
        for unit_id in ordered[:limit]:
            row = dict(row_by_id[unit_id])
            row.pop("tokens", None)
            row.pop("file_path", None)
            row["sources"] = self.db.rows(
                """
                SELECT s.id,s.file_name,s.relative_path,us.page_start,us.excerpt
                FROM knowledge_unit_sources us JOIN source_files s ON s.id=us.source_id WHERE us.unit_id=?
                """,
                (unit_id,),
            )
            row["scores"] = {**channels.get(unit_id, {}), "rrf": rrf.get(unit_id, 0), "reranker": rerank_map.get(unit_id)}
            row["index_version"] = index["version"]
            results.append(row)
        latency_ms = int((time.perf_counter() - started) * 1000)
        with self.db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO retrieval_runs_v2(
                    project_id,query,filters_json,index_version,bm25_count,dense_count,result_count,
                    latency_ms,results_json,created_by
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    project_id,
                    query,
                    json.dumps({"industry": industry, "unit_type": unit_type, "classification": classification}, ensure_ascii=False),
                    index["version"],
                    len(lexical_rank),
                    len(dense_ids),
                    len(results),
                    latency_ms,
                    json.dumps([{"unit_id": item["unit_id"], "scores": item["scores"]} for item in results], ensure_ascii=False),
                    created_by,
                ),
            )
            run_id = int(cursor.lastrowid)
        for item in results:
            item["retrieval_run_id"] = run_id
        return results

    def feedback(self, run_id: int, action: str, unit_id: int | None, notes: str, user_id: int | None) -> dict[str, Any]:
        if action not in {"used", "rejected", "missing", "irrelevant"}:
            raise ValueError("未知检索反馈类型")
        with self.db.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO retrieval_feedback(retrieval_run_id,unit_id,action,notes,created_by) VALUES (?,?,?,?,?)",
                (run_id, unit_id, action, notes, user_id),
            )
            feedback_id = int(cursor.lastrowid)
        return {"id": feedback_id, "status": "recorded"}

    def status(self) -> dict[str, Any]:
        active = self.db.row("SELECT * FROM retrieval_indexes WHERE status='active' ORDER BY id DESC LIMIT 1")
        return {"active_index": active, "embedding_available": self.embedding.available, "qdrant_configured": bool(self.settings.qdrant_url)}
