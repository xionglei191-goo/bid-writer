from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from docx import Document

from bid_writer_v2.database import Database
from bid_writer_v2.knowledge.service import KnowledgeService
from bid_writer_v2.production.service import DEFAULT_OUTLINE, ProductionService
from bid_writer_v2.utils import content_hash
from test_v2_workflow import build_settings


FIXTURE_ROOT = Path(__file__).with_name("fixtures") / "pilots"


class PilotWorkflowTest(unittest.TestCase):
    def run_pilot(self, fixture_name: str) -> dict:
        fixture = json.loads((FIXTURE_ROOT / fixture_name).read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = build_settings(root)
            settings.ensure_directories()
            db = Database(settings.db_path)
            db.migrate()
            knowledge = KnowledgeService(db, settings)
            production = ProductionService(db, settings, knowledge)
            knowledge_item = fixture.pop("knowledge")
            publication_id = 0
            with db.connect() as conn:
                for index, outline_title in enumerate(DEFAULT_OUTLINE, 1):
                    content = f"{outline_title}按项目要求进行策划并形成过程记录。{knowledge_item['content']}"
                    digest = content_hash(content)
                    unit_id = int(
                        conn.execute(
                            """
                            INSERT INTO knowledge_units(
                                unit_key,unit_type,title,content,cleaned_content,industry,tags_json,risk_level,status,content_fingerprint
                            ) VALUES (?,?,?,?,?,?,'[]','textual','published',?)
                            """,
                            (f"pilot-{fixture_name}-{index}", knowledge_item["unit_type"], outline_title, content, content, fixture["industry"], digest),
                        ).lastrowid
                    )
                    version_id = int(
                        conn.execute(
                            "INSERT INTO knowledge_versions(unit_id,version_no,content,content_hash,status) VALUES (?,1,?,?,'approved')",
                            (unit_id, content, digest),
                        ).lastrowid
                    )
                    publication_id = int(
                        conn.execute(
                            "INSERT INTO knowledge_publications(unit_id,version_id,publication_version,published_by,file_path,content_hash) VALUES (?,?,1,'fixture','fixture.md',?)",
                            (unit_id, version_id, digest),
                        ).lastrowid
                    )
                    conn.execute(
                        "INSERT INTO published_units_fts(unit_id,title,content,tags,industry,unit_type) VALUES (?,?,?,?,?,?)",
                        (unit_id, outline_title, content, "[]", fixture["industry"], knowledge_item["unit_type"]),
                    )
            started = time.perf_counter()
            previous = os.environ.get("BID_WRITER_DISABLE_LLM")
            os.environ["BID_WRITER_DISABLE_LLM"] = "1"
            try:
                project = production.create_project(fixture)
                parsed = production.parse_requirements(project["id"])
                outline = production.build_outline(project["id"])
                matrix = production.coverage_matrix(project["id"])
                self.assertFalse(matrix["unmapped_high"], matrix)
                generated = production.generate_all(project["id"])
                self.assertEqual(generated["failed"], 0, generated)
                detail = production.get_project(project["id"])
                for section in detail["sections"]:
                    draft = section["draft"]
                    resolutions = [
                        {"index": index, "resolution": "演练项目已核对项目输入和知识来源"}
                        for index, _item in enumerate(draft["confirmations"])
                    ]
                    production.confirm_draft(draft["id"], "演练技术负责人", resolutions)
                quality = production.quality_gate(project["id"])
                self.assertTrue(quality["ready"], quality)
                delivery = production.export_project(project["id"], "docx")
                self.assertTrue(Path(delivery["file_path"]).is_file())
                self.assertTrue(production.list_manifests(project["id"])[0]["manifest_hash"])
                rendered = Document(delivery["file_path"])
                self.assertTrue(any(fixture["name"] in paragraph.text for paragraph in rendered.paragraphs))
                return {
                    "project_id": project["id"],
                    "requirements": len(parsed["requirements"]),
                    "sections": len(outline["sections"]),
                    "claims": quality["metrics"]["claims"]["total"],
                    "support_rate": quality["metrics"]["claims"]["support_rate"],
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                    "publication_id": publication_id,
                }
            finally:
                if previous is None:
                    os.environ.pop("BID_WRITER_DISABLE_LLM", None)
                else:
                    os.environ["BID_WRITER_DISABLE_LLM"] = previous

    def test_building_construction_pilot(self) -> None:
        report = self.run_pilot("building-construction.json")
        self.assertEqual(report["sections"], 11)
        self.assertGreater(report["claims"], 0)

    def test_water_environment_pilot(self) -> None:
        report = self.run_pilot("water-environment.json")
        self.assertEqual(report["sections"], 11)
        self.assertGreater(report["claims"], 0)


if __name__ == "__main__":
    unittest.main()
