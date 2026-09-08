from __future__ import annotations

import unittest

from bid_writer_v2.production.response_text import copies_requirement


class ResponseTextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.first = "水性漆施工方案必须明确应用工艺并提供相应质量检查措施。"
        self.second = "投标人还应提供材料来源和检验安排。"
        self.source = self.first + self.second
        self.requirement = {"content": self.source, "requirement_key": "REQ-0001"}

    def test_complete_tender_sentence_excerpt_is_not_a_response(self):
        for quote in (self.first, self.second, "响应措施：" + self.first, "REQ-0001：" + self.second):
            with self.subTest(quote=quote):
                self.assertTrue(copies_requirement(quote, self.requirement))

    def test_repeating_whole_requirement_or_excerpt_does_not_add_a_response(self):
        for quote in (self.source * 2, self.first * 3, self.source + self.first, self.source + self.source + "按要求落实。"):
            with self.subTest(quote=quote):
                self.assertTrue(copies_requirement(quote, self.requirement))

    def test_common_long_introductions_and_closing_assurances_are_not_substance(self):
        for quote in (
            "针对本项目要求现作如下详细说明并逐项响应：" + self.source,
            "响应措施：" + self.source + "按要求落实。",
            "根据招标文件要求，具体如下：" + self.source + "我方严格响应招标要求。",
            "REQ-0001：" + self.source,
        ):
            with self.subTest(quote=quote):
                self.assertTrue(copies_requirement(quote, self.requirement))

    def test_real_construction_additions_remain_valid_even_when_short(self):
        for quote in (
            self.source + "采用刷涂施工。",
            self.source + "由质检员抽检。",
            self.source + "先清理基层，再分层涂刷。",
            "水性漆材料进场核验合格证，基层处理后分层涂刷并留存检查记录。",
            "采用刷涂施工。",
            "响应措施：" + self.source + "完成后逐面检查涂膜外观。",
        ):
            with self.subTest(quote=quote):
                self.assertFalse(copies_requirement(quote, self.requirement))

    def test_common_short_words_do_not_trigger_partial_quote_rejection(self):
        for quote in ("材料来源", "检验安排", "质量检查措施"):
            with self.subTest(quote=quote):
                self.assertFalse(copies_requirement(quote, self.requirement))

    def test_empty_or_missing_source_does_not_claim_a_copy(self):
        self.assertFalse(copies_requirement("", self.requirement))
        self.assertFalse(copies_requirement("现场采用刷涂施工。", {}))
        self.assertFalse(copies_requirement("REQ-0001：", self.requirement))

    def test_copy_detection_ignores_only_formatting(self):
        quote = "“水性漆施工方案必须明确应用工艺并提供相应质量检查措施。”\n【投标人还应提供材料来源和检验安排。】"
        self.assertTrue(copies_requirement(quote, self.requirement))
        changed = self.first.replace("必须明确", "已经确定")
        self.assertFalse(copies_requirement(changed, self.requirement))


if __name__ == "__main__":
    unittest.main()
