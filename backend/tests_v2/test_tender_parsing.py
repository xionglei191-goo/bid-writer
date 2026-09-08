from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bid_writer_v2.database import Database
from bid_writer_v2.knowledge.service import KnowledgeService
from bid_writer_v2.production.api import build_router
from bid_writer_v2.production.service import ProductionService
from bid_writer_v2.settings import Settings
from bid_writer_v2.utils import content_hash


class TenderParsingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="tender-parser-test-")
        root = Path(self.temp.name)
        settings = Settings(
            workspace_root=root, app_root=root / "app", raw_root=root / "raw", knowledge_root=root / "knowledge",
            delivery_root=root / "delivery", data_root=root / "data", db_path=root / "data" / "test.sqlite3",
            upload_root=root / "uploads", cache_root=root / "cache", export_root=root / "exports", qa_root=root / "qa",
            operations_enabled=False,
        )
        settings.ensure_directories()
        self.db = Database(settings.db_path)
        self.db.migrate()
        self.service = ProductionService(self.db, settings, KnowledgeService(self.db, settings))
        app = FastAPI()
        app.include_router(build_router(self.service))
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def parse(self, text: str) -> list[dict]:
        project = self.service.create_project({"name": "滨河公共建筑改造工程", "source_text": text})
        self.project_id = project["id"]
        return self.service.parse_requirements(project["id"])["requirements"]

    def test_wrapped_clauses_keep_page_and_excluded_work(self) -> None:
        requirements = self.parse("""[第3页]
1
第一章招标公告
滨河公共建筑改造工程
2.5 招标范围：施工图纸范围内全部内容（不含高低压变配电、医用
气体、消防系统、污水处理等专业工程）；
2.6 计划工期：850 日历天。
[第4页]
2
3.9 存在控股关系的不同单位，不得参加同一标段或者未划分标段的同
一招标项目的投标。
""")
        self.assertEqual(len(requirements), 3)
        self.assertEqual([item["source_page"] for item in requirements], [3, 3, 4])
        self.assertIn("不含高低压变配电、医用气体、消防系统、污水处理等专业工程", requirements[0]["content"])
        self.assertIn("同一招标项目", requirements[2]["content"])
        self.assertEqual(requirements[2]["kind"], "veto")
        self.assertEqual(requirements[2]["priority"], "high")

    def test_scoring_rows_preserve_short_titles_weights_and_cross_page_conditions(self) -> None:
        requirements = self.parse("""[第26页]
24
2.2.4
(1)
施工
组织
设计
评分
标准
（总分 100
分）
评分因素 参考评分标准
施工期间的保
通措施
10
确保施工期间交通畅通的措施合理、可行。
资源配备计划 5
劳动力配备计划及主要施工机械配备计划合理、
可行。
项目管理班子
的配备
5
项目经理、技术负责人、施工员、安全员等人员配备齐全合理。
扬尘污染防治
方案及建筑垃
圾处置方案
5
施工现场扬尘治理达到8个100%，包括车辆冲洗率、
[第27页]
25
运土车辆封闭率；建筑垃圾处置方案合理、可行。
水性漆的应用
方案
3 水性漆的应用方案合理、可行
非道路移动机
械排放污染的
管控措施
2
使用符合要求的非道路移动机械，禁止使用国二
及以下排放标准的非道路移动机械。
1、各档次的标准设定如下：
缺少相关方案将不得分。
2.2.4
(2)
评审项目 标准分 评分因素
服务承诺 50 分 工程保修服务承诺。
2.2.4
(3)
投标报价的评分按以下公式计算。
""")
        scores = [item for item in requirements if item["kind"] == "scoring" and "分）：" in item["content"]]
        expected = [("施工期间的保通措施", 10, 26), ("资源配备计划", 5, 26), ("项目管理班子的配备", 5, 26),
                    ("扬尘污染防治方案及建筑垃圾处置方案", 5, 26), ("水性漆的应用方案", 3, 27),
                    ("非道路移动机械排放污染的管控措施", 2, 27), ("服务承诺", 50, 27)]
        self.assertEqual(len(scores), len(expected))
        for item, (title, weight, page) in zip(scores, expected):
            self.assertTrue(item["content"].startswith(f"{title}（{weight}分）："), item)
            self.assertEqual(item["source_page"], page)
            self.assertEqual(item["priority"], "high")
        self.assertIn("运土车辆封闭率", scores[3]["content"])
        self.assertIn("禁止使用国二及以下排放标准", scores[5]["content"])
        self.assertNotIn("投标报价", scores[-1]["content"])
        self.assertFalse(any(item["content"] == "评分因素 参考评分标准" for item in requirements))
        headings = [item for item in requirements if "（总分 100分）" in item["content"]]
        self.assertEqual(len(headings), 1)
        self.assertEqual(headings[0]["classification"]["suggested_category"], "reference")
        self.assertTrue(headings[0]["formal_technical"])
        self.assertEqual(headings[0]["classification"]["status"], "pending")

    def test_numeric_terms_outside_score_tables_are_not_scores(self) -> None:
        requirements = self.parse("[第7页]\n5\n1.3.2 计划工期\n850 日历天。\n1.3.3 质量要求\n符合相关技术标准合格要求。")
        self.assertEqual(len(requirements), 2)
        self.assertTrue(all(item["kind"] != "scoring" for item in requirements))
        self.assertIn("850 日历天", requirements[0]["content"])

    def test_short_prohibitions_are_not_discarded(self) -> None:
        requirements = self.parse("[第3页]\n1\n不得转包。\n严禁挂靠。")
        self.assertEqual([item["content"] for item in requirements], ["不得转包。", "严禁挂靠。"])
        self.assertTrue(all(item["priority"] == "high" for item in requirements))

    def test_real_tender_pages_16_17_keep_all_twelve_exclusion_children(self) -> None:
        # Verbatim exclusion list from the supplied 120-page hospital tender.
        clauses = [
            "（1）为招标人不具有独立法人资格的附属机构（单位）；",
            "（2）为本项目前期准备提供设计或咨询服务的，但设计施工总承包的除外；",
            "（3）为本项目的监理人；",
            "（4）为本项目的代建人；",
            "（5）为本项目提供招标代理服务的；",
            "（6）与本项目的监理人或代建人或招标代理机构同为一个法定代表人的；",
            "（7）与本项目的监理人或代建人或招标代理机构相互控股或参股的；",
            "（8）与本项目的监理人或代建人或招标代理机构相互任职或工作的；",
            "（9）被责令停业的；",
            "（10）被暂停或取消投标资格的；",
            "（11）财产被接管或冻结的；",
            "（12）在最近三年内有骗取中标或严重违约或重大工程质量问题的。",
        ]
        requirements = self.parse(
            "[第16页]\n14\n1.4.3 投标人不得存在下列情形之一：\n[第17页]\n15\n"
            + "\n".join(clauses)
            + "\n1.5 费用承担\n投标人准备和参加投标活动发生的费用自理。\n1.6 保密要求\n投标人应保护招标文件中的秘密。"
        )
        children = [item for item in requirements if item["content"] in clauses]
        self.assertEqual([item["content"] for item in children], clauses)
        self.assertTrue(all(item["source_page"] == 17 and item["kind"] == "veto" and item["priority"] == "high" for item in children))
        self.assertEqual(requirements[0]["source_page"], 16)
        self.assertEqual(requirements[-1]["kind"], "technical")
        self.assertEqual(requirements[-1]["priority"], "normal")

    def test_exclusion_list_children_wrap_pages_and_stop_at_a_new_clause(self) -> None:
        requirements = self.parse("""[第40页]
8.3 申请人不得具有以下情况：
(1)资产被冻结的；
(2)与评审机构具有
[第41页]
39
直接管理关系的；
(3)被责令停业的。
8.4 施工要求
(1)施工前应检查现场条件。
""")
        self.assertEqual([item["content"] for item in requirements[:4]], [
            "8.3 申请人不得具有以下情况：", "(1)资产被冻结的；", "(2)与评审机构具有直接管理关系的；", "(3)被责令停业的。",
        ])
        self.assertEqual([item["source_page"] for item in requirements[:4]], [40, 40, 40, 41])
        self.assertTrue(all(item["kind"] == "veto" and item["priority"] == "high" for item in requirements[:4]))
        self.assertTrue(all(item["kind"] != "veto" for item in requirements[4:]))

    def test_chinese_exclusion_numbering_does_not_leak_across_chapter_headers(self) -> None:
        requirements = self.parse("""[第5页]
申请人不得存在下列行为：
（一）相互串通；
[第6页]
（二）弄虚作假；
第三章施工技术要求
（三）施工前应检查现场条件。
""")
        self.assertEqual(len(requirements), 4)
        self.assertEqual([item["kind"] for item in requirements], ["veto", "veto", "veto", "technical"])
        self.assertEqual([item["source_page"] for item in requirements], [5, 5, 6, 6])

    def test_scoring_and_performance_words_are_not_vetoes_but_subcontracting_is(self) -> None:
        requirements = self.parse("""[第27页]
该项清单偏差率超出范围的，不得分。
未提供施工方案的不得分或扣除相应分值。
我方在此承诺，承担由于自身工作不得力而产生的责任；
施工主体结构不得分包。
本工程不得分拆项目规避管理。
施工方案缺项不得分，但严禁伪造施工记录。
""")
        self.assertEqual([item["kind"] for item in requirements], ["scoring", "scoring", "commitment", "veto", "veto", "veto"])
        self.assertEqual(requirements[2]["priority"], "normal")
        self.assertTrue(all(item["priority"] == "high" for item in requirements[3:]))

    def test_painting_and_completion_records_map_to_the_expected_technical_sections(self) -> None:
        requirements = self.parse("""[第27页]
水性漆的应用方案应合理可行。
涂装方案应明确过程检查。
涂料使用应符合产品说明。
承包人提交的竣工资料必须及时、真实、准确、完整。
""")
        outline = self.service.build_outline(self.project_id)
        ids_by_title = {item["title"]: item["requirement_ids"] for item in outline["sections"]}
        self.assertTrue(all(item["id"] in ids_by_title["主要施工方案与技术措施"] for item in requirements[:3]))
        self.assertIn(requirements[3]["id"], ids_by_title["质量保证体系与措施"])

    def test_page_headers_alone_do_not_become_requirements(self) -> None:
        requirements = self.parse("[第1页]\n滨河公共建筑改造工程\n招 标 文 件\n[第2页]\n目录\n[第3页]\n1\n第一章招标公告\n滨河公共建筑改造工程")
        self.assertEqual(requirements, [])

    def test_unpaginated_input_remains_supported_without_inventing_pages(self) -> None:
        requirements = self.parse("投标人必须编制施工方案。\n工程质量应达到合格要求。")
        self.assertEqual(len(requirements), 2)
        self.assertTrue(all(item["source_page"] is None for item in requirements))

    def test_reparse_is_blocked_and_outline_supplement_preserves_existing_signed_drafts(self) -> None:
        original_requirements = self.parse("投标人必须编制施工方案。")
        outline = self.service.build_outline(self.project_id)
        section_id = outline["sections"][0]["id"]
        text = "施工前组织现场核对，并将检查结果形成记录。"
        with self.db.connect() as conn:
            draft_id = int(conn.execute(
                "INSERT INTO project_drafts(project_id,section_id,content,content_hash,version_no) VALUES (?,?,?,?,1)",
                (self.project_id, section_id, text, content_hash(text)),
            ).lastrowid)
        run_id = self.service.evidence.create_generation_run(self.project_id, section_id, content_hash(text), "fixture", "1", "1", None, [])
        self.service.evidence.analyze_draft(run_id, draft_id, text, [])
        self.service.confirm_draft(draft_id, "隔离测试责任人")
        before = self.service.get_project(self.project_id)
        response = self.client.post(f"/api/projects/{self.project_id}/requirements/parse")
        self.assertEqual(response.status_code, 409, response.text)
        supplemented = self.client.post(f"/api/projects/{self.project_id}/outline")
        self.assertEqual(supplemented.status_code, 200, supplemented.text)
        after = self.service.get_project(self.project_id)
        for key in ("id", "content", "source_page", "kind"):
            self.assertEqual([item[key] for item in after["requirements"]], [item[key] for item in original_requirements])
        self.assertEqual(json.dumps(after["sections"], sort_keys=True), json.dumps(before["sections"], sort_keys=True))
        self.assertEqual(after["sections"][0]["draft"]["status"], "reviewed")


if __name__ == "__main__":
    unittest.main()
