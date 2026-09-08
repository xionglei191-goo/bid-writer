from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from bid_writer_v2.database import Database
from bid_writer_v2.retrieval import HybridRetrievalService
from bid_writer_v2.settings import Settings
from bid_writer_v2.storage import ObjectStorage
from bid_writer_v2.utils import content_hash


class IndexRecoveryTest(unittest.TestCase):
    """Exercise publication/index boundaries without importing the ASGI app."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="index-recovery-test-")
        root = Path(self.temp.name)
        self.settings = Settings(
            workspace_root=root, app_root=root / "app", raw_root=root / "raw", knowledge_root=root / "knowledge",
            delivery_root=root / "delivery", data_root=root / "data", db_path=root / "data" / "test.sqlite3",
            upload_root=root / "uploads", cache_root=root / "cache", export_root=root / "exports", qa_root=root / "qa",
            operations_enabled=False, embedding_url="http://embedding.invalid", qdrant_url="http://qdrant.invalid",
            embedding_request_batch_size=2,
        )
        self.settings.ensure_directories()
        self.db = Database(self.settings.db_path)
        self.db.migrate()
        self.storage = ObjectStorage(self.db, self.settings)
        self.service = HybridRetrievalService(self.db, self.settings, self.storage)
        self.service.embedding = Mock(available=True)
        self.service.embedding.embed.side_effect = lambda texts: [[0.1, 0.2, 0.3] for _ in texts]
        self.service.embedding.rerank.side_effect = lambda _query, documents: [0.9 for _ in documents]
        self.publications = [self.publish(f"基坑排水方案 {index}", f"基坑排水采用截水沟和集水井，安排专人巡查排水沟并留存记录。方案编号 {index}。") for index in range(5)]
        self.lexical = HybridRetrievalService(self.db, replace(self.settings, qdrant_url="", embedding_url=""), self.storage)
        self.previous = self.lexical.build_index()
        self.qdrant = Mock()
        self.qdrant.count.return_value = Mock(count=5)
        self.qdrant_patch = patch("qdrant_client.QdrantClient", return_value=self.qdrant)
        self.qdrant_type = self.qdrant_patch.start()

    def tearDown(self) -> None:
        self.qdrant_patch.stop()
        self.temp.cleanup()

    def publish(self, title: str, content: str, *, classification: str = "internal") -> dict:
        digest = content_hash(content)
        with self.db.connect() as conn:
            unit_id = int(conn.execute(
                "INSERT INTO knowledge_units(unit_key,unit_type,title,content,cleaned_content,industry,tags_json,risk_level,status,content_fingerprint,classification) "
                "VALUES (?,'construction_method',?,?,?,'市政','[]','textual','published',?,?)",
                (content_hash(title), title, content, content, digest, classification),
            ).lastrowid)
            version_id = int(conn.execute(
                "INSERT INTO knowledge_versions(unit_id,version_no,content,content_hash,status) VALUES (?,1,?,?,'approved')",
                (unit_id, content, digest),
            ).lastrowid)
            publication_id = int(conn.execute(
                "INSERT INTO knowledge_publications(unit_id,version_id,publication_version,published_by,file_path,content_hash) VALUES (?,?,1,'fixture','fixture.md',?)",
                (unit_id, version_id, digest),
            ).lastrowid)
        return {"unit_id": unit_id, "publication_id": publication_id, "version_id": version_id, "content_hash": digest}

    def replace_publication(self, original: dict) -> dict:
        with self.db.connect() as conn:
            conn.execute("UPDATE knowledge_publications SET status='retired' WHERE id=?", (original["publication_id"],))
            publication_id = int(conn.execute(
                "INSERT INTO knowledge_publications(unit_id,version_id,publication_version,published_by,file_path,content_hash) VALUES (?,?,2,'fixture','replacement.md',?)",
                (original["unit_id"], original["version_id"], original["content_hash"]),
            ).lastrowid)
        return {**original, "publication_id": publication_id}

    def assert_previous_active(self) -> None:
        active = self.db.rows("SELECT id FROM retrieval_indexes WHERE status='active'")
        self.assertEqual([row["id"] for row in active], [self.previous["id"]])

    def test_dense_batches_are_written_before_next_batch_and_counted_exactly(self) -> None:
        events = []
        order = []
        self.service.embedding.embed.side_effect = lambda texts: order.append(("embed", len(texts))) or [[0.1, 0.2, 0.3] for _ in texts]
        self.qdrant.upsert.side_effect = lambda **kwargs: order.append(("upsert", len(kwargs["points"])))
        result = self.service.build_index(progress=lambda *args: events.append(args))
        self.assertEqual(order, [("embed", 2), ("upsert", 2), ("embed", 2), ("upsert", 2), ("embed", 1), ("upsert", 1)])
        self.assertEqual(result["dense_documents"], 5)
        progress_counts = [event[3]["dense_documents"] for event in events if event[0] == "embedding" and len(event) > 3]
        self.assertEqual(progress_counts, [2, 4, 5])
        self.assertEqual(len(self.qdrant.create_collection.call_args_list), 1)
        self.assertTrue(all(call.kwargs["wait"] is True for call in self.qdrant.upsert.call_args_list))
        self.assertTrue(self.qdrant.count.call_args.kwargs["exact"])
        self.assertEqual(self.db.row("SELECT status FROM retrieval_indexes WHERE id=?", (self.previous["id"],))["status"], "superseded")
        self.assertTrue(self.service.status()["index_consistent"])

    def test_cancelled_partial_or_completed_upload_keeps_previous_index_active(self) -> None:
        for cancel_at in (2, 5):
            with self.subTest(cancel_at=cancel_at):
                state = {"cancelled": False}

                def progress(stage, _percent, _message, details=None):
                    if stage == "embedding" and details and details.get("dense_documents", 0) >= cancel_at:
                        state["cancelled"] = True

                result = self.service.build_index(progress=progress, cancelled=lambda: state["cancelled"])
                self.assertTrue(result["cancelled"])
                self.assertEqual(result["dense_documents"], cancel_at)
                self.assert_previous_active()
                self.assertEqual(self.db.row("SELECT COUNT(*) AS count FROM retrieval_indexes")["count"], 1)

    def test_initial_cancel_does_not_write_storage_or_contact_services(self) -> None:
        with patch.object(self.storage, "put_bytes") as put:
            result = self.service.build_index(cancelled=lambda: True)
        self.assertTrue(result["cancelled"])
        put.assert_not_called()
        self.service.embedding.embed.assert_not_called()
        self.qdrant_type.assert_not_called()
        self.assert_previous_active()

    def test_embedding_batch_mismatch_or_upload_failure_keeps_previous_active(self) -> None:
        self.service.embedding.embed.side_effect = lambda _texts: [[0.1, 0.2, 0.3]]
        with self.assertRaisesRegex(RuntimeError, "索引向量数量不一致"):
            self.service.build_index()
        self.assert_previous_active()
        self.qdrant.upsert.assert_not_called()
        self.service.embedding.embed.side_effect = lambda texts: [[0.1, 0.2, 0.3] for _ in texts]
        self.qdrant.upsert.side_effect = RuntimeError("fixture upload failure")
        with self.assertRaisesRegex(RuntimeError, "fixture upload failure"):
            self.service.build_index()
        self.assert_previous_active()

    def test_qdrant_final_point_count_mismatch_never_activates(self) -> None:
        self.qdrant.count.return_value = Mock(count=4)
        with self.assertRaisesRegex(RuntimeError, "向量索引核对失败"):
            self.service.build_index()
        self.assert_previous_active()
        self.assertEqual(self.db.row("SELECT COUNT(*) AS count FROM retrieval_indexes")["count"], 1)

    def test_same_count_membership_change_during_build_keeps_previous_index(self) -> None:
        changed = []

        def progress(stage, _percent, _message, details=None):
            if stage == "embedding" and details and not changed:
                changed.append(self.replace_publication(self.publications[0]))

        with self.assertRaisesRegex(RuntimeError, "构建期间已发布知识发生变化"):
            self.service.build_index(progress=progress)
        self.assert_previous_active()
        self.assertEqual(len(self.service._published_members()), 5)
        self.assertFalse(self.service.status()["index_consistent"])

    def test_candidate_activation_checks_membership_even_when_counts_and_content_match(self) -> None:
        candidate = self.lexical.build_index(activate=False)
        self.assertEqual(candidate["status"], "building")
        self.assert_previous_active()
        self.replace_publication(self.publications[0])
        with self.assertRaisesRegex(ValueError, "候选索引与当前已发布知识不一致"):
            self.service.activate_index(candidate["id"])
        self.assert_previous_active()
        self.assertEqual(self.db.row("SELECT status FROM retrieval_indexes WHERE id=?", (candidate["id"],))["status"], "building")

    def test_matching_candidate_can_activate_and_clear_old_cache(self) -> None:
        self.lexical.search("基坑排水")
        candidate = self.lexical.build_index(activate=False)
        activated = self.lexical.activate_index(candidate["id"])
        self.assertEqual(activated["status"], "active")
        self.assertEqual(self.lexical._index_cache, {})
        result = self.lexical.search("基坑排水")
        self.assertTrue(result)
        self.assertTrue(all(row["index_version"] == candidate["version"] for row in result))

    def test_stale_active_index_uses_live_lexical_and_excludes_retired_publications(self) -> None:
        original = self.publications[0]
        replacement = self.replace_publication(original)
        results = self.service.search("基坑排水", limit=10)
        ids = {row["publication_id"] for row in results}
        self.assertNotIn(original["publication_id"], ids)
        self.assertIn(replacement["publication_id"], ids)
        self.assertEqual(len(ids), 5)
        self.assertTrue(all(row["index_version"] == "live-lexical" for row in results))
        self.qdrant_type.assert_not_called()
        self.service.embedding.embed.assert_not_called()
        self.assert_previous_active()

    def test_candidate_search_also_filters_retired_publications(self) -> None:
        candidate = self.lexical.build_index(activate=False)
        original = self.publications[0]
        self.replace_publication(original)
        results = self.lexical.search_index(candidate["id"], "基坑排水", limit=10)
        self.assertNotIn(original["publication_id"], {row["publication_id"] for row in results})
        self.assertEqual(len(results), 4)
        self.assertTrue(all(row["index_version"] == candidate["version"] for row in results))

    def test_public_knowledge_remains_searchable_before_and_after_index_becomes_stale(self) -> None:
        public = self.publish("基坑排水公开方案", "基坑排水采用截水沟和集水井。", classification="public")
        current = self.lexical.build_index()
        for stale in (False, True):
            with self.subTest(stale=stale):
                if stale:
                    self.replace_publication(self.publications[-1])
                results = self.lexical.search("基坑排水", limit=50)
                self.assertIn(public["publication_id"], {row["publication_id"] for row in results})
                expected_version = "live-lexical" if stale else current["version"]
                self.assertTrue(all(row["index_version"] == expected_version for row in results))

    def test_classification_scope_is_preserved_before_and_after_index_becomes_stale(self) -> None:
        public = self.publish("基坑排水公开方案", "基坑排水采用截水沟和集水井。", classification="public")
        private = self.publish("基坑排水私有方案", "基坑排水采用专用水泵和排水沟。", classification="private")
        self.lexical.build_index()
        internal_id = self.publications[0]["publication_id"]
        for stale in (False, True):
            if stale:
                self.replace_publication(self.publications[-1])
            for classification in ("internal", "public", "private"):
                with self.subTest(stale=stale, classification=classification):
                    results = self.lexical.search("基坑排水", limit=50, classification=classification)
                    ids = {row["publication_id"] for row in results}
                    self.assertIn(public["publication_id"], ids)
                    self.assertEqual(private["publication_id"] in ids, classification == "private")
                    self.assertEqual(internal_id in ids, classification == "internal")

    def test_status_requires_exact_manifest_not_just_a_matching_total(self) -> None:
        self.assertTrue(self.service.status()["index_consistent"])
        previous = self.service.status()["active_index"]
        self.replace_publication(self.publications[0])
        status = self.service.status()
        self.assertEqual(status["published_total"], previous["publication_count"])
        self.assertFalse(status["index_consistent"])
        self.assert_previous_active()

    def test_legacy_count_only_index_is_not_reported_as_verified(self) -> None:
        with self.db.connect() as conn:
            conn.execute("UPDATE retrieval_indexes SET metrics_json=? WHERE id=?",
                         (json.dumps({"bm25_documents": 5, "dense_documents": 5}), self.previous["id"]))
        self.assertFalse(self.service.status()["index_consistent"])


if __name__ == "__main__":
    unittest.main()
