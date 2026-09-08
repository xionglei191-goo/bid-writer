from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bid_writer_v2.database import Database
from bid_writer_v2.evidence import EvidenceService, claim_sentences
from bid_writer_v2.project_evidence import PROJECT_EVIDENCE_VERSION, ProjectEvidenceIndex, number_bindings, project_source_snapshot
from bid_writer_v2.utils import content_hash


SOURCE = """[第3页]
标段一（南区）建筑面积117413.82平方米，地上76534.76平方米，地下40870.06平方米；
标段二（北区）建筑面积141127.03平方米，地上58880.48平方米，地下82246.55平方米。
计划工期：850日历天；
质量要求：符合国家、省、市相关规范和技术标准合格要求，争创鲁班奖。
[第45页]
发包人由于市政工程、竣工交房、合同终止等原因要求承包人腾退人员、场地的，承包人应在发包人通知之日起【10】天内完成腾退，否则由此造成损失的，由承包人承担全部责任。
[第52页]
如承包人拒绝实施有效设计变更，发包人有权另择施工单位完成，所发生的费用另需支付20%的施工违约金。
施工单位仅适用于夜间停诊区域，除紧急抢险外不得施工。
主体结构不得违法分包。
"""
PROFILE = {"duration": "850日历天", "building_area_m2": 141127.03, "aboveground_area_m2": 58880.48,
           "underground_area_m2": 82246.55, "quality_target": "符合国家、省、市相关规范和技术标准合格要求，争创鲁班奖。"}


def project(**changes):
    return {"id": 1, "name": "医院主体施工标段二（北区）", "source_text": SOURCE, "profile": dict(PROFILE), **changes}


class ProjectEvidenceMatchingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.index = ProjectEvidenceIndex(project())

    def test_project_numeric_facts_and_quality_goal_bind_to_page_and_full_source(self) -> None:
        for claim in (
            "计划工期：850日历天", "总建筑面积141127.03平方米",
            "建筑规模：总建筑面积141,127.03 m²，其中地上建筑面积58,880.48 m²，地下建筑面积82,246.55 m²。",
            "质量目标：符合国家、省、市相关规范和技术标准合格要求，争创鲁班奖。",
        ):
            with self.subTest(claim=claim):
                result = self.index.evaluate(claim)
                self.assertTrue(result["supported"], result)
                self.assertTrue(all(match["source_kind"] == "project_tender" and match["source_page"] == 3 for match in result["matches"]))
                self.assertTrue(all(match["source_hash"] == content_hash(SOURCE) for match in result["matches"]))
        self.assertEqual(self.index.profile_conflicts, [])

    def test_notice_paraphrase_keeps_event_deadline_object_and_liability(self) -> None:
        for claim in ("通知后10天内腾退场地", "接到腾退通知10天内完成人员场地腾退，逾期损失自担。"):
            with self.subTest(claim=claim):
                result = self.index.evaluate(claim)
                self.assertTrue(result["supported"], result)
                self.assertTrue(all(match["source_page"] == 45 for match in result["matches"]))
                number = result["matches"][0]["numbers"][0]
                self.assertEqual(number["object"], "evacuation_period")
                self.assertEqual(number["conditions"]["trigger"], "evacuation_notice")
                self.assertEqual(number["conditions"]["bound"], "max")

    def test_changed_event_calendar_bound_and_area_object_are_rejected(self) -> None:
        for claim in (
            "开工后10天内腾退场地", "通知后10个工作日内腾退场地", "通知后至少10天腾退场地",
            "地上建筑面积82246.55平方米", "本标段总建筑面积117413.82平方米", "计划工期850工作日",
        ):
            with self.subTest(claim=claim):
                self.assertFalse(self.index.evaluate(claim)["supported"])

    def test_explicit_notice_issuer_must_match_and_implicit_recipient_is_allowed(self) -> None:
        for claim in ("监理通知后10天内腾退场地", "承包人通知后10天内腾退场地"):
            with self.subTest(claim=claim):
                self.assertFalse(self.index.evaluate(claim)["supported"])
        for claim in ("发包人通知后10天内腾退场地", "业主通知后10天内腾退场地", "承包人接到通知后10天内腾退场地"):
            with self.subTest(claim=claim):
                result = self.index.evaluate(claim)
                self.assertTrue(result["supported"], result)
        self.assertEqual(number_bindings("承包人接到发包人的通知后10天内腾退场地")[0]["conditions"]["notice_actor"], "employer")
        self.assertEqual(number_bindings("承包人接到通知后10天内腾退场地")[0]["conditions"]["notice_actor"], "")

    def test_acceptance_and_approval_prerequisites_cannot_be_omitted(self) -> None:
        examples = (
            ("经验收合格后方可拆除模板。", "可拆除模板。", "经验收合格后，可拆除模板。"),
            ("经监理批准后方可拆除模板。", "经业主批准后方可拆除模板。", "经监理工程师批准后方可拆除模板。"),
            ("满足设计要求后方可拆除模板。", "可拆除模板。", "满足设计要求后方可拆除模板。"),
        )
        for source, unsupported, supported in examples:
            for kind in ("project_tender", "knowledge_publication"):
                with self.subTest(source=source, kind=kind):
                    index = ProjectEvidenceIndex(project(source_text="[第8页]" + source if kind == "project_tender" else "", profile={}),
                                                 [] if kind == "project_tender" else [{"publication_id": 2, "unit_id": 2, "title": "模板拆除", "content": source}])
                    self.assertFalse(index.evaluate(unsupported)["supported"])
                    result = index.evaluate(supported)
                    self.assertTrue(result["supported"], result)

    def test_same_percentage_for_penalty_does_not_support_site_reserve(self) -> None:
        result = self.index.evaluate("场地按需求预留20%余量")
        self.assertFalse(result["supported"])
        self.assertTrue(any(row["value"] == "20" for passage in self.index.passages for row in passage["numbers"]))

    def test_compound_claim_requires_every_numeric_and_commitment_assertion(self) -> None:
        for claim in (
            "计划工期850日历天，场地预留20%余量。",
            "计划工期850日历天，确保医院区域环境零投诉。",
            "建筑面积141127.03平方米，地上建筑面积99999平方米。",
            "主体结构阶段工期850日历天，装修阶段工期120日历天。",
            "本项目分为六个阶段完成施工。",
        ):
            with self.subTest(claim=claim):
                self.assertFalse(self.index.evaluate(claim)["supported"])

    def test_negation_scope_exception_and_award_strength_cannot_expand(self) -> None:
        for claim in ("主体结构允许违法分包", "除所有情况外均可施工", "确保获得鲁班奖", "本工程已获鲁班奖"):
            with self.subTest(claim=claim):
                self.assertFalse(self.index.evaluate(claim)["supported"])
        restrictive = ProjectEvidenceIndex(project(source_text="[第8页]仅适用于夜间停诊区域施工，除紧急抢险外不得施工。", profile={}))
        self.assertFalse(restrictive.evaluate("适用于所有医院区域施工") ["supported"])
        self.assertFalse(restrictive.evaluate("不得施工") ["supported"])

    def test_other_project_knowledge_never_proves_this_project_facts(self) -> None:
        index = ProjectEvidenceIndex(project(source_text="[第1页]项目施工范围待图纸明确。", profile={}), [
            {"publication_id": 1, "unit_id": 1, "title": "另一项目", "content": "计划工期850日历天。总建筑面积141127.03平方米。"},
        ])
        self.assertFalse(index.evaluate("计划工期850日历天")["supported"])
        self.assertFalse(index.evaluate("总建筑面积141127.03平方米")["supported"])

    def test_general_knowledge_is_preserved_but_changed_grade_is_not(self) -> None:
        index = ProjectEvidenceIndex(project(profile={}), [{
            "publication_id": 2, "unit_id": 2, "title": "施工通用知识",
            "content": "施工前组织图纸会审和技术交底，并形成过程记录。混凝土强度等级必须达到C30。钢筋直径为20mm。",
        }])
        good = index.evaluate("施工前组织图纸会审和技术交底，并形成过程记录。")
        self.assertTrue(good["supported"], good)
        self.assertTrue(all(match["source_kind"] == "knowledge_publication" for match in good["matches"]))
        self.assertFalse(index.evaluate("混凝土强度等级必须达到C60。")["supported"])
        self.assertFalse(index.evaluate("管道直径为20mm。")["supported"])

    def test_profile_conflict_never_supplies_missing_source_evidence(self) -> None:
        conflicting = ProjectEvidenceIndex(project(profile={**PROFILE, "duration": "900日历天"}))
        self.assertEqual(conflicting.profile_conflicts[0]["field"], "duration")
        self.assertFalse(conflicting.evaluate("计划工期900日历天")["supported"])
        self.assertFalse(conflicting.evaluate("计划工期850日历天")["supported"])
        profile_only = ProjectEvidenceIndex(project(source_text="", profile=PROFILE))
        self.assertFalse(profile_only.evaluate("计划工期850日历天")["supported"])

    def test_source_hash_includes_all_facts_but_excludes_confirmation_metadata(self) -> None:
        original = project_source_snapshot(project())["project_source_hash"]
        for workflow in ({"professional_reviewer": "fixture reviewer"}, {"delivery_confirmation": {"approved": True}}, {"final_approved": True}):
            self.assertEqual(project_source_snapshot(project(profile={**PROFILE, **workflow}))["project_source_hash"], original)
        self.assertNotEqual(project_source_snapshot(project(profile={**PROFILE, "duration": "900日历天"}))["project_source_hash"], original)
        self.assertNotEqual(project_source_snapshot(project(source_text=SOURCE + "新条件"))["project_source_hash"], original)
        self.assertNotEqual(project_source_snapshot(project(id=2))["project_source_hash"], original)

    def test_chinese_stage_counts_and_material_grades_remain_exact(self) -> None:
        self.assertEqual(number_bindings("分为十二个阶段")[0]["value"], "12")
        self.assertEqual(number_bindings("分为五大阶段")[0]["value"], "5")
        self.assertEqual(number_bindings("C60混凝土")[0]["unit"], "grade:c")

    def test_long_late_and_short_high_risk_assertions_are_never_silently_skipped(self) -> None:
        body = "\n".join(f"第{index}项施工措施应形成完整的现场检查记录。" for index in range(301)) + "\n保证7天完成全部施工。"
        claims = claim_sentences(body)
        self.assertGreater(len(claims), 300)
        self.assertIn("保证7天完成全部施工。", claims)
        self.assertFalse(self.index.evaluate(claims[-1])["supported"])
        long_claim = "计划工期850日历天，" + "施工过程资料应按合同要求收集保存，" * 40 + "场地预留20%余量。"
        self.assertGreater(len(long_claim), 500)
        self.assertEqual(claim_sentences(long_claim), [long_claim])
        self.assertFalse(self.index.evaluate(long_claim)["supported"])
        for short in ("零投诉。", "工期7天。", "禁止施工。"):
            self.assertEqual(claim_sentences(short), [short])


class ProjectEvidencePersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="project-evidence-tests-")
        self.addCleanup(self.temporary.cleanup)
        self.db = Database(Path(self.temporary.name) / "test.sqlite3")
        self.db.migrate()
        self.service = EvidenceService(self.db)
        with self.db.connect() as conn:
            self.project_id = int(conn.execute("INSERT INTO projects(name,source_text,profile_json) VALUES (?,?,?)", (project()["name"], SOURCE, json.dumps(PROFILE))).lastrowid)
            self.section_id = int(conn.execute("INSERT INTO project_sections(project_id,order_no,title) VALUES (?,1,'工期与质量')", (self.project_id,)).lastrowid)
            self.body = "本项目计划工期为850日历天。总建筑面积为141127.03平方米。"
            self.draft_id = int(conn.execute("INSERT INTO project_drafts(project_id,section_id,content,content_hash) VALUES (?,?,?,?)", (self.project_id, self.section_id, self.body, content_hash(self.body))).lastrowid)

    def analyze(self):
        run = self.service.create_generation_run(self.project_id, self.section_id, "input", "fixture", "1", "1", None, [])
        return self.service.analyze_draft(run, self.draft_id, self.body, [])

    def review_args(self):
        return {"reviewer": "实际测试核验人", "target_hash": content_hash(self.body),
                "project_source_hash": self.service.project_source_status(self.project_id)["current_project_source_hash"]}

    def test_analysis_loads_project_source_automatically_and_returns_auditable_links(self) -> None:
        analysis = self.analyze()
        self.assertEqual(analysis["unsupported_high"], [])
        self.assertEqual(analysis["supported"], 2)
        claims = self.service.list_claims(self.draft_id)
        self.assertTrue(all(row["support_status"] == "supported" for row in claims))
        link = claims[0]["evidence"][0]
        self.assertEqual(link["source_kind"], "project_tender")
        self.assertEqual(link["page"], 3)
        self.assertIn("duration", link["source_meta"]["objects"])
        self.assertEqual(link["project_source_hash"], analysis["current_project_source_hash"])
        self.assertFalse(self.service.project_source_status(self.project_id)["stale"])

    def test_changed_source_invalidates_visible_support_without_writing_in_read_helper(self) -> None:
        self.analyze()
        before = self.db.row("SELECT support_status FROM claims WHERE draft_id=? ORDER BY id LIMIT 1", (self.draft_id,))
        with self.db.connect() as conn:
            conn.execute("UPDATE projects SET source_text=? WHERE id=?", (SOURCE.replace("850日历天", "900日历天"), self.project_id))
            with patch.object(self.db, "connect", side_effect=AssertionError("must use supplied connection")):
                status = self.service.project_source_status(self.project_id, conn=conn)
                visible = self.service.list_claims(self.draft_id, conn=conn)
        self.assertEqual(status["stale_draft_ids"], [self.draft_id])
        self.assertTrue(status["profile_conflicts"])
        self.assertEqual(visible[0]["support_status"], "invalidated")
        self.assertEqual(self.db.row("SELECT support_status FROM claims WHERE draft_id=? ORDER BY id LIMIT 1", (self.draft_id,)), before)

    def test_old_rule_version_is_stale_until_reanalysis_even_with_unchanged_source(self) -> None:
        analysis = self.analyze()
        before = self.db.rows("SELECT * FROM claims WHERE draft_id=? ORDER BY id", (self.draft_id,))
        original_source_hash = analysis["project_source_hash"]
        with self.db.connect() as conn:
            conn.execute("UPDATE generation_runs SET rule_version='project-evidence-1.0.0' WHERE id=?", (analysis["run_id"],))
            with patch.object(self.db, "connect", side_effect=AssertionError("read helpers must use supplied connection")):
                status = self.service.project_source_status(self.project_id, conn=conn)
                claims = self.service.list_claims(self.draft_id, conn=conn)
        self.assertEqual(status["stale_draft_ids"], [self.draft_id])
        self.assertEqual(status["current_project_source_hash"], original_source_hash)
        self.assertTrue(all(row["source_stale"] and row["support_status"] == "invalidated" for row in claims))
        self.assertTrue(all(link["support_level"] == "invalidated" for row in claims for link in row["evidence"]))
        self.assertIn("规则已更新", status["drafts"][0]["reason"])
        self.assertEqual(self.db.rows("SELECT * FROM claims WHERE draft_id=? ORDER BY id", (self.draft_id,)), before)
        with self.assertRaisesRegex(ValueError, "规则已更新"):
            self.service.resolve_claim(claims[0]["id"], "confirm", "依据招标原文第三页逐字核对", **self.review_args())
        refreshed = self.service.refresh_project_evidence(self.project_id)
        self.assertFalse(refreshed["source_status"]["stale"])
        self.assertEqual(refreshed["current_project_source_hash"], original_source_hash)
        self.assertTrue(all(row["analyzed_rule_version"] == PROJECT_EVIDENCE_VERSION and not row["source_stale"] for row in self.service.list_claims(self.draft_id)))
        self.assertEqual(self.db.row("SELECT content FROM project_drafts WHERE id=?", (self.draft_id,))["content"], self.body)

    def test_refresh_uses_caller_transaction_and_never_edits_saved_text(self) -> None:
        self.analyze()
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE projects SET profile_json=? WHERE id=?", (json.dumps({**PROFILE, "duration": "900日历天"}), self.project_id))
            with patch.object(self.db, "connect", side_effect=AssertionError("no nested connection")):
                result = self.service.refresh_project_evidence(self.project_id, conn=conn)
        self.assertEqual(result["analyzed_count"], 1)
        self.assertEqual(result["drafts"][0]["draft_id"], self.draft_id)
        self.assertTrue(result["drafts"][0]["unsupported_high"])
        self.assertEqual(self.db.row("SELECT content FROM project_drafts WHERE id=?", (self.draft_id,))["content"], self.body)
        self.assertFalse(result["source_status"]["stale"])
        self.assertTrue(result["profile_conflicts"])

    def test_analysis_run_from_another_project_is_rejected(self) -> None:
        with self.db.connect() as conn:
            other = int(conn.execute("INSERT INTO projects(name) VALUES ('其他项目')").lastrowid)
        run = self.service.create_generation_run(other, None, "input", "fixture", "1", "1", None, [])
        with self.assertRaisesRegex(ValueError, "不匹配"):
            self.service.analyze_draft(run, self.draft_id, self.body, [])
        self.assertEqual(self.service.list_claims(self.draft_id), [])

    def test_claim_resolution_requires_identity_current_body_source_and_actual_reason(self) -> None:
        self.analyze()
        claim = self.service.list_claims(self.draft_id)[0]
        args = self.review_args()
        for changed in ({"reviewer": ""}, {"target_hash": "old"}, {"project_source_hash": "old"}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.service.resolve_claim(claim["id"], "confirm", "依据招标原文第三页逐字核对", **{**args, **changed})
        with self.assertRaises(ValueError):
            self.service.resolve_claim(claim["id"], "confirm", "", **args)
        for action in ("weaken", "remove"):
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, "编辑草稿正文"):
                self.service.resolve_claim(claim["id"], action, "准备改写", **args)

    def test_confirm_reopen_invalidates_prior_signoff_and_keeps_append_only_review_history(self) -> None:
        self.analyze()
        claim = self.service.list_claims(self.draft_id)[0]
        with self.db.connect() as conn:
            conn.execute("INSERT INTO draft_review_decisions(draft_id,reviewer,target_hash,decision) VALUES (?,?,?,'approved')", (self.draft_id, "原章节审核人", content_hash(self.body)))
        args = self.review_args()
        confirmed = self.service.resolve_claim(claim["id"], "confirm", "依据招标原文第三页逐字核对", **args)
        self.assertEqual(confirmed["support_status"], "confirmed")
        self.assertEqual(self.db.row("SELECT decision FROM draft_review_decisions WHERE draft_id=?", (self.draft_id,))["decision"], "invalidated")
        self.service.resolve_claim(claim["id"], "reopen", "需要另一名专业人员再次核验", **args)
        self.assertEqual(self.service.metrics(self.project_id)["high_unsupported"], 1)
        self.service.refresh_project_evidence(self.project_id)
        events = self.db.rows("SELECT claim_id,claim_text,reviewer,action,target_hash,project_source_hash FROM claim_review_events ORDER BY id")
        self.assertEqual([event["action"] for event in events], ["confirm", "reopen"])
        self.assertTrue(all(event["claim_id"] is None and event["claim_text"] == claim["text"] for event in events))

    def test_historical_draft_claim_cannot_be_confirmed(self) -> None:
        self.analyze()
        claim = self.service.list_claims(self.draft_id)[0]
        with self.db.connect() as conn:
            conn.execute("INSERT INTO project_drafts(project_id,section_id,content,version_no) VALUES (?,?,?,2)", (self.project_id, self.section_id, self.body))
        with self.assertRaisesRegex(ValueError, "历史草稿"):
            self.service.resolve_claim(claim["id"], "confirm", "原文核验", **self.review_args())

    def test_legacy_resolved_and_invalidated_high_risk_claims_stay_blocking(self) -> None:
        self.analyze()
        for status in ("resolved", "invalidated"):
            with self.subTest(status=status), self.db.connect() as conn:
                conn.execute("UPDATE claims SET support_status=? WHERE draft_id=?", (status, self.draft_id))
                metrics = self.service.metrics(self.project_id, conn=conn)
                self.assertEqual(metrics["supported"], 0)
                self.assertEqual(metrics["high_unsupported"], 2)


if __name__ == "__main__":
    unittest.main()
