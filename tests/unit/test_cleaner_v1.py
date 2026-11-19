"""Cleaner v1 验证（方案 06 §3.2）。

黄金样本场景：22 位分组空格、显式分隔符、全角/BOM/零宽、MOD10 软校验、
各结果码与不可识别项不计费。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "worker" / "src"))

from worker.cleaner import Cleaner, CLEANER_VERSION  # noqa: E402
from worker.cleaner.cleaner import _mod10_usps22  # noqa: E402


class TestGroupedSpaces:
    """最关键：22 位单号按 4 位分组书写，行内空格绝不是分隔符。"""

    def test_grouped_22_digits_is_one_candidate(self):
        r = Cleaner().clean("9302 0106 2339 6181 8206 39")
        assert len(r.candidates) == 1
        c = r.candidates[0]
        assert c.normalized == "9302010623396181820639"
        assert c.result_code in ("valid", "checksum_warn")

    def test_spaces_removed_within_number(self):
        r = Cleaner().clean("9400 1502 0621 7997 9796 67")
        assert r.candidates[0].normalized == "9400150206217997979667"


class TestExplicitSeparators:
    def test_comma_semicolon_tab_split(self):
        a = "9302010623396181820639"
        b = "9400150206217997979667"
        r = Cleaner().clean(f"{a},{b};{a}\t{b}")
        assert len(r.candidates) == 4
        assert [c.normalized for c in r.candidates] == [a, b, a, b]

    def test_vertical_bar_split(self):
        a = "9302010623396181820639"
        b = "9400150206217997979667"
        r = Cleaner().clean(f"{a}|{b}")
        assert len(r.candidates) == 2


class TestNormalization:
    def test_fullwidth_and_bom_zerowidth(self):
        # 全角数字 + BOM + 零宽空格
        fullwidth = "９３０２０１０６２３３９６１８１８２０６３９"
        r = Cleaner().clean("\ufeff\u200b" + fullwidth + "\u200b")
        assert r.candidates[0].normalized == "9302010623396181820639"

    def test_known_prefix_removed(self):
        r = Cleaner().clean("Tracking Number: 9302010623396181820639")
        assert r.candidates[0].normalized == "9302010623396181820639"

    def test_version_and_raw_trace(self):
        raw = "9302010623396181820639"
        r = Cleaner().clean(raw)
        c = r.candidates[0]
        assert c.cleaner_version == CLEANER_VERSION
        assert c.raw_line == raw
        assert c.line_no == 1


class TestResultCodes:
    def test_invalid_length(self):
        r = Cleaner().clean("12345")
        assert r.candidates[0].result_code == "invalid_length"
        assert not r.candidates[0].billable

    def test_unsupported_shape_s10(self):
        r = Cleaner().clean("EA123456789US")
        assert r.candidates[0].result_code == "unsupported_shape"
        assert not r.candidates[0].billable

    def test_garbled(self):
        r = Cleaner().clean("9302\u0001010623396181820639")
        assert r.candidates[0].result_code == "garbled"

    def test_ambiguous_empty_token(self):
        r = Cleaner().clean("9302010623396181820639,,")
        # 尾随空项被过滤，只剩 1 个有效候选
        assert len(r.candidates) == 1

    def test_invalid_charset_whole_batch(self):
        r = Cleaner().clean("", strict_utf8_ok=False)
        assert len(r.candidates) == 1
        assert r.candidates[0].result_code == "invalid_charset"
        assert r.billable_count == 0


class TestMod10SoftCheck:
    def test_mod10_detects_bad_checksum(self):
        # 修改末位制造错误校验位
        good = "9302010623396181820639"
        bad = good[:-1] + str((int(good[-1]) + 1) % 10)
        assert _mod10_usps22(good) != _mod10_usps22(bad)

    def test_checksum_warn_still_billable(self):
        good = "9302010623396181820639"
        bad = good[:-1] + str((int(good[-1]) + 1) % 10)
        r = Cleaner().clean(bad)
        c = r.candidates[0]
        assert c.result_code in ("valid", "checksum_warn")
        # 无论软校验结果，格式合规的 22 位数字都可计费入队
        assert c.billable
        assert r.billable_count == 1


class TestLineHandling:
    def test_crlf_and_blank_lines(self):
        a = "9302010623396181820639"
        r = Cleaner().clean(f"{a}\r\n\r\n{a}\n")
        assert len(r.candidates) == 2
        assert [c.line_no for c in r.candidates] == [1, 3]

    def test_line_too_long_marked(self):
        long_line = "9" * 600
        r = Cleaner().clean(long_line)
        assert r.candidates[0].result_code == "invalid_length"
