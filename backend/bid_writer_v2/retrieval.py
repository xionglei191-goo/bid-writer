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
        batch_size = self.settings.embedding_request_batch_size
        vectors: list[list[float]] = []
        with httpx.Client(timeout=self.settings.embedding_timeout_seconds) as client:
            for start in range(0, len(texts), batch_size):
                batch = texts[start:start + batch_size]
                response = client.post(f"{self.settings.embedding_url}/embed", json={"texts": batch})
                response.raise_for_status()
                batch_vectors = response.json().get("vectors") or []
                if len(batch_vectors) != len(batch):
                    raise RuntimeError(
                        f"embedding响应数量不一致: expected={len(batch)}, actual={len(batch_vectors)}"
                    )
                vectors.extend(batch_vectors)
        return vectors

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        if not self.available or not documents:
            return []
        # The GPU endpoint accepts at most 64 documents. Cross-encoder scores are
        # absolute, so independent batches can be concatenated without changing order.
        batch_size = min(64, self.settings.embedding_request_batch_size)
        scores: list[float] = []
        with httpx.Client(timeout=self.settings.embedding_timeout_seconds) as client:
            for start in range(0, len(documents), batch_size):
                batch = documents[start:start + batch_size]
                response = client.post(
                    f"{self.settings.embedding_url}/rerank",
                    json={"query": query, "documents": batch},
                )
                response.raise_for_status()
                batch_scores = response.json().get("scores") or []
                if len(batch_scores) != len(batch):
                    raise RuntimeError(
                        f"rerank响应数量不一致: expected={len(batch)}, actual={len(batch_scores)}"
                    )
                scores.extend(float(value) for value in batch_scores)
        return scores


class HybridRetrievalService:
    def __init__(self, db: Database, settings: Settings, storage: ObjectStorage) -> None:
        self.db = db
        self.settings = settings
        self.storage = storage
        self.embedding = EmbeddingClient(settings)
        self._index_cache: dict[str, Any] = {}
        self._index_override: tuple[dict[str, Any], list[dict[str, Any]]] | None = None

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

    def build_index(self, progress=None, cancelled=None, *, activate: bool = True) -> dict[str, Any]:
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
        version = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}-{source_hash[:10]}"
        collection = f"published_knowledge_{version.replace('-', '_')}"
        object_key = f"indexes/{version}/bm25.json"
        stored = self.storage.put_bytes(object_key, json.dumps(corpus, ensure_ascii=False).encode("utf-8"), "application/json")
        progress("embedding", 35, "生成知识向量")
        dense_indexed = 0
        if rows and self.settings.qdrant_url and self.embedding.available:
            from qdrant_client import QdrantClient, models

            client = QdrantClient(url=self.settings.qdrant_url, timeout=60)
            batch_size = self.settings.embedding_request_batch_size
            for start in range(0, len(rows), batch_size):
                if cancelled():
                    return {"cancelled": True, "dense_documents": dense_indexed}
                batch = rows[start:start + batch_size]
                vectors = self.embedding.embed([f"{row['title']}\n{row['content']}" for row in batch])
                if len(vectors) != len(batch):
                    raise RuntimeError(f"索引向量数量不一致：需要{len(batch)}条，收到{len(vectors)}条")
                if start == 0:
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
                        for row, vector in zip(batch, vectors)
                    ],
                    wait=True,
                )
                dense_indexed += len(vectors)
                progress("embedding", 35 + int(55 * dense_indexed / len(rows)),
                         f"检索向量已写入 {dense_indexed}/{len(rows)} 条",
                         {"dense_documents": dense_indexed, "publications": len(rows)})
            actual_count = int(client.count(collection_name=collection, exact=True).count)
            if actual_count != len(rows):
                raise RuntimeError(f"向量索引核对失败：发布{len(rows)}条，索引{actual_count}条")
        if cancelled():
            return {"cancelled": True, "dense_documents": dense_indexed}
        latest = self._published_rows()
        if self._publication_members(rows) != self._publication_members(latest):
            raise RuntimeError("构建期间已发布知识发生变化，已保留原索引，请重新构建")
        metrics = {"bm25_documents": len(rows), "dense_documents": dense_indexed,
                   "publication_manifest_hash": self._members_hash(self._publication_members(rows))}
        with self.db.connect() as conn:
            if activate:
                conn.execute("UPDATE retrieval_indexes SET status='superseded' WHERE status='active'")
            cursor = conn.execute(
                """
                INSERT INTO retrieval_indexes(
                    version,embedding_model,reranker_model,bm25_object_key,qdrant_collection,
                    publication_count,content_hash,status,metrics_json,activated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    version,
                    self.settings.embedding_model,
                    self.settings.reranker_model,
                    object_key,
                    collection,
                    len(rows),
                    source_hash,
                    "active" if activate else "building",
                    json.dumps(metrics, ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat(timespec="seconds") if activate else None,
                ),
            )
            index_id = int(cursor.lastrowid)
        if activate:
            self._index_cache = {"version": version, "corpus": corpus}
        progress("completed", 100, "检索索引已激活" if activate else "候选检索索引已构建", metrics)
        return {"id": index_id, "version": version, "status": "active" if activate else "building", "object": stored, **metrics}

    def activate_index(self, index_id: int) -> dict[str, Any]:
        index = self.db.row("SELECT * FROM retrieval_indexes WHERE id=?", (index_id,))
        if not index:
            raise KeyError("检索索引不存在")
        with self.storage.open(index["bm25_object_key"]) as handle:
            corpus = json.loads(handle.read().decode("utf-8"))
        if self._publication_members(corpus) != self._published_members():
            raise ValueError("候选索引与当前已发布知识不一致，请重新构建")
        with self.db.connect() as conn:
            conn.execute("UPDATE retrieval_indexes SET status='superseded' WHERE status='active' AND id<>?", (index_id,))
            conn.execute("UPDATE retrieval_indexes SET status='active',activated_at=CURRENT_TIMESTAMP WHERE id=?", (index_id,))
        self._index_cache = {}
        return self.db.row("SELECT * FROM retrieval_indexes WHERE id=?", (index_id,)) or {}

    @staticmethod
    def _publication_members(rows: list[dict[str, Any]]) -> set[tuple[int, int, str]]:
        return {(int(row["publication_id"]), int(row["unit_id"]), str(row["content_hash"])) for row in rows}

    def _published_members(self) -> set[tuple[int, int, str]]:
        rows = self.db.rows("SELECT id AS publication_id,unit_id,content_hash FROM knowledge_publications WHERE status='published'")
        return self._publication_members(rows)

    @staticmethod
    def _members_hash(members: set[tuple[int, int, str]]) -> str:
        return content_hash(json.dumps(sorted(members), separators=(",", ":")))

    def _active_index(self) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        if self._index_override is not None:
            return self._index_override
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
        current_members = self._published_members()
        if not index or not corpus or (self._index_override is None and self._publication_members(corpus) != current_members):
            corpus = [
                {**row, "tags": parse_json(row.pop("tags_json", "[]"), []), "tokens": tokenize(f"{row['title']} {row['content']}")}
                for row in self._published_rows(industry, unit_type)
            ]
            index = {"version": "live-lexical", "qdrant_collection": ""}
        eligible = [
            row for row in corpus
            if (int(row["publication_id"]), int(row["unit_id"]), str(row["content_hash"])) in current_members
            and (not industry or row.get("industry") == industry)
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

    def search_index(
        self,
        index_id: int,
        query: str,
        industry: str = "",
        unit_type: str = "",
        limit: int = 12,
        classification: str = "internal",
    ) -> list[dict[str, Any]]:
        index = self.db.row("SELECT * FROM retrieval_indexes WHERE id=?", (index_id,))
        if not index:
            raise KeyError("检索索引不存在")
        with self.storage.open(index["bm25_object_key"]) as handle:
            corpus = json.loads(handle.read().decode("utf-8"))
        previous_override = self._index_override
        try:
            self._index_override = (index, corpus)
            return self.search(query, industry, unit_type, limit, classification=classification)
        finally:
            self._index_override = previous_override

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
        members = self._published_members()
        metrics = parse_json((active or {}).get("metrics_json"), {})
        consistent = bool(active) and int(active["publication_count"]) == len(members) and metrics.get("publication_manifest_hash") == self._members_hash(members)
        return {"active_index": active, "embedding_available": self.embedding.available,
                "qdrant_configured": bool(self.settings.qdrant_url),
                "published_total": len(members), "index_consistent": consistent}
