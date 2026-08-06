from __future__ import annotations

import unittest

from bid_writer_v2.knowledge.service import decode_archive_member_name


class ArchiveNameEncodingTest(unittest.TestCase):
    def test_repairs_gb18030_name_decoded_as_cp437(self) -> None:
        expected = "\u901a\u4fe1\u65bd-101\u53f7\u751f\u4ea7\u5382\u623f.pdf"
        garbled = expected.encode("gb18030").decode("cp437")
        self.assertEqual(decode_archive_member_name(garbled), expected)

    def test_preserves_utf8_and_ascii_names(self) -> None:
        self.assertEqual(decode_archive_member_name("normal-file.pdf"), "normal-file.pdf")
        expected = "\u4e2d\u6587\u6587\u4ef6.pdf"
        self.assertEqual(decode_archive_member_name(expected, 0x800), expected)


if __name__ == "__main__":
    unittest.main()
