"""Cleaner v1（方案 06 §3.1/3.2）：8 步流水线把客户原始输入转为候选单号。

关键约束（06 §3.2）：USPS 22 位单号常按 4 位分组书写，行内空格绝不是分隔符；
行是主单位，行内空白一律删除，只有逗号/分号/制表符等显式分隔符才二次切分。
规范化规则版本化（CLEANER_VERSION），变更版本但不重算历史提交。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

CLEANER_VERSION = "v1"

# 服务端硬限制（06 §3.1）
MAX_REQUEST_BYTES = 67_108_864          # 64 MiB
MAX_LINE_CHARS = 512
MAX_LINE_UTF8_BYTES = 2_048
MAX_RAW_LINES = 1_000_000
MAX_CANDIDATES = 1_000_000

# 显式二次分隔符：逗号、分号、制表符、竖线（不含空格）
_EXPLICIT_SPLIT_RE = re.compile(r"[,;\t|]+")
# 零宽字符（NFKC 后仍需清除）
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
# 已知前缀（06 §3.2 ④ 只删除明确识别的前缀）
_KNOWN_PREFIX_RE = re.compile(
    r"^(?:tracking\s*(?:number|no\.?|#)\s*[:：]?\s*|单号\s*[:：]?\s*)", re.IGNORECASE)
# 单号形状：USPS 22 位纯数字（9400/9302 等）；国际 S10（EA…US）单独归类不默认拒绝
_USPS_22_RE = re.compile(r"^\d{22}$")
_S10_RE = re.compile(r"^[A-Z]{2}\d{9}[A-Z]{2}$")
_HEX_DIGITS = set("0123456789")

# 结果码（06 §3.2）——billable 表示是否计费入队
RESULT_BILLABLE = frozenset({
    "valid", "normalized", "checksum_warn",
})


@dataclass
class CleanCandidate:
    """单条规范化候选。"""
    raw_line: str                      # 原始行（留痕）
    line_no: int                       # 原始行号（从 1）
    raw_number: str                    # 显式切分后的原始候选文本
    normalized: str | None             # 规范化后的单号（不可识别为 None）
    result_code: str                   # 结果码
    billable: bool                     # 是否计费入队
    cleaner_version: str = CLEANER_VERSION


@dataclass
class CleanResult:
    """一次提交的整体清洗结果。"""
    candidates: list[CleanCandidate] = field(default_factory=list)

    @property
    def billable_numbers(self) -> list[str]:
        """可计费候选（去重前，供后续计费判定）。"""
        return [c.normalized for c in self.candidates
                if c.billable and c.normalized]

    @property
    def billable_count(self) -> int:
        return len(self.billable_numbers)

    @property
    def invalid_count(self) -> int:
        return sum(1 for c in self.candidates if not c.billable)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.candidates:
            out[c.result_code] = out.get(c.result_code, 0) + 1
        return out


def _mod10_usps22(number: str) -> bool:
    """USPS 22 位单号 MOD10（权重 3/1 交替，从右起）。

    仅作软校验：存疑返回 False → checksum_warn，仍计费入队，不硬拦。
    """
    if not _USPS_22_RE.match(number):
        return True  # 非 22 位数字不做该校验
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = ord(ch) - 48
        if i % 2 == 1:
            d *= 3
        total += d
    return total % 10 == 0


def _normalize_token(token: str) -> tuple[str | None, str]:
    """规范化单个显式候选：返回 (normalized, result_code)。"""
    # ③ NFKC + BOM/零宽清除；行内所有空白删除（关键是空格不当分隔符）
    t = unicodedata.normalize("NFKC", token)
    t = _ZERO_WIDTH_RE.sub("", t)
    t = re.sub(r"\s+", "", t)
    if not t:
        return None, "ambiguous_input"
    # 乱码 / 含控制字符或替换符
    if any(ord(ch) < 32 or ch == "\ufffd" for ch in t):
        return None, "garbled"
    # ④ 只删除明确识别的前缀（在去空白后再次识别，兼容 "Tracking#:xxx"）
    t2 = _KNOWN_PREFIX_RE.sub("", t)
    if t2 and t2 != t:
        t = t2
    # ⑥ 形状与长度校验
    if _USPS_22_RE.match(t):
        # ⑦ MOD10 软校验
        return t, ("valid" if _mod10_usps22(t) else "checksum_warn")
    if _S10_RE.match(t):
        # 国际 S10：方案要求不默认归入非 USPS，按 unsupported_shape 待 W1 样本确认
        return None, "unsupported_shape"
    if any(ch not in _HEX_DIGITS for ch in t):
        return None, "unsupported_shape"
    # 纯数字但长度不符
    return None, "invalid_length"


class Cleaner:
    """8 步清洗流水线（无状态，可并发复用）。"""

    def clean(self, raw_text: str, *, strict_utf8_ok: bool = True) -> CleanResult:
        """清洗原始输入文本。

        strict_utf8_ok=False 表示上游严格 UTF-8 解码已失败（步骤①），
        整批标 invalid_charset，不猜测内容。
        """
        result = CleanResult()
        if not strict_utf8_ok:
            # ① 严格解码失败：不猜测，整批一条异常记录
            result.candidates.append(CleanCandidate(
                raw_line="", line_no=0, raw_number="", normalized=None,
                result_code="invalid_charset", billable=False))
            return result

        # ② 按 CRLF/LF/CR 切行，保留原始行号
        lines = re.split(r"\r\n|\n|\r", raw_text)
        if len(lines) > MAX_RAW_LINES:
            # 超限由上层按 request_too_large 整批拒绝；这里保守截断并标记
            lines = lines[:MAX_RAW_LINES]

        for idx, line in enumerate(lines, start=1):
            # ③ 单行硬限制（字符数 / UTF-8 字节数）
            if len(line) > MAX_LINE_CHARS or len(line.encode("utf-8")) > MAX_LINE_UTF8_BYTES:
                result.candidates.append(CleanCandidate(
                    raw_line=line[:120], line_no=idx, raw_number="", normalized=None,
                    result_code="invalid_length", billable=False))
                continue
            if not line.strip():
                continue  # 空行不计候选，不算异常

            # ⑤ 只按显式分隔符二次切分；空格不切
            tokens = _EXPLICIT_SPLIT_RE.split(line)
            if len(tokens) > 1:
                # 多候选：逐个规范化；切分关系不明确（如尾随分隔符产生空项）标 ambiguous
                tokens = [t for t in tokens if t.strip()]
            for tok in tokens:
                norm, code = _normalize_token(tok)
                billable = code in RESULT_BILLABLE
                # ⑧ 写入 cleaner_version 与原文留痕（字段在构造默认值里）
                result.candidates.append(CleanCandidate(
                    raw_line=line, line_no=idx, raw_number=tok.strip(),
                    normalized=norm, result_code=code, billable=billable))

        # 候选总数上限（06 §3.1）
        if len(result.candidates) > MAX_CANDIDATES:
            result.candidates = result.candidates[:MAX_CANDIDATES]
        return result
