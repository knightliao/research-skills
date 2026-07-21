#!/usr/bin/env python3
"""确定性识别、解析并规范化常见字幕文件。"""

from __future__ import annotations

import argparse
import codecs
import html
import os
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


SUPPORTED_FORMATS = ("srt", "vtt", "ass", "ssa", "lrc", "txt", "md")
EXTENSION_FORMATS = {
    ".srt": "srt",
    ".vtt": "vtt",
    ".ass": "ass",
    ".ssa": "ssa",
    ".lrc": "lrc",
    ".txt": "txt",
    ".md": "md",
    ".markdown": "md",
}
LEGACY_ENCODINGS = ("gb18030", "big5", "shift_jis", "euc_kr", "cp1252")

SRT_TIMESTAMP_RE = re.compile(
    r"^\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*"
    r"\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}(?:\s+.*)?$",
    re.MULTILINE,
)
VTT_TIMESTAMP_RE = re.compile(
    r"^\s*(?:\d{1,2}:)?\d{2}:\d{2}\.\d{1,3}\s*-->\s*"
    r"(?:\d{1,2}:)?\d{2}:\d{2}\.\d{1,3}(?:\s+.*)?$",
    re.MULTILINE,
)
GENERIC_TIMESTAMP_RE = re.compile(
    r"^\s*(?:(?:\d{1,2}:)?\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*"
    r"(?:(?:\d{1,2}:)?\d{2}:\d{2}[,.]\d{1,3})(?:\s+.*)?$"
)
LRC_TIME_PREFIX_RE = re.compile(
    r"^\s*(?:\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\])+\s*",
    re.MULTILINE,
)
LRC_INLINE_TIME_RE = re.compile(r"<\d{1,3}:\d{2}(?:[.:]\d{1,3})?>")
LRC_METADATA_RE = re.compile(r"^\s*\[[A-Za-z][A-Za-z0-9_-]*\s*:.*\]\s*$")
ASS_OVERRIDE_RE = re.compile(r"\{[^{}]*\}")
HTML_STYLE_RE = re.compile(
    r"</?(?:b|i|u|s|font|c|ruby|rt|lang)(?:\.[^\s>/]+)*(?:\s+[^>]*)?/?>",
    re.IGNORECASE,
)
VTT_VOICE_OPEN_RE = re.compile(r"^\s*<v(?:\.[^\s>]+)*(?:\s+([^>]+))?>", re.IGNORECASE)
VTT_VOICE_CLOSE_RE = re.compile(r"</v\s*>", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"[\t\f\v ]+")
PUNCTUATION_BOUNDARY = set("，。！？；：、,.!?;:)]}）】》\"'”’—-…")


class SubtitleError(ValueError):
    """表示可向命令行用户说明的输入或解析错误。"""


@dataclass(frozen=True, slots=True)
class Cue:
    """一条已经清理但尚未执行确定性去重的字幕。"""

    text: str
    speaker: str | None = None
    timed: bool = True


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    """规范化结果及可供调用方检查的检测信息。"""

    text: str
    format_name: str
    encoding: str
    warnings: tuple[str, ...] = ()


def normalize_newlines(text: str) -> str:
    """统一换行并移除可能残留的 Unicode BOM。"""

    return text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")


def is_basic_text_plausible(text: str) -> bool:
    """拒绝空文本、NUL 和控制字符密集的二进制误解码结果。"""

    if not text or "\x00" in text:
        return False
    controls = sum(
        1
        for character in text
        if unicodedata.category(character) == "Cc" and character not in "\n\r\t"
    )
    if controls / max(len(text), 1) > 0.01:
        return False
    visible = sum(character.isprintable() or character in "\n\r\t" for character in text)
    return visible / len(text) >= 0.95


def _count_in_ranges(text: str, ranges: tuple[tuple[int, int], ...]) -> int:
    return sum(any(start <= ord(character) <= end for start, end in ranges) for character in text)


def is_legacy_candidate_plausible(text: str, encoding: str) -> bool:
    """用保守的文字系统检查排除明显不合理的传统编码候选。"""

    if not is_basic_text_plausible(text):
        return False
    non_ascii = [character for character in text if ord(character) > 127]
    if not non_ascii:
        return False

    cjk_count = _count_in_ranges(text, ((0x3400, 0x4DBF), (0x4E00, 0x9FFF)))
    kana_count = _count_in_ranges(text, ((0x3040, 0x30FF),))
    hangul_count = _count_in_ranges(text, ((0xAC00, 0xD7AF), (0x1100, 0x11FF)))

    if encoding in {"gb18030", "big5"}:
        return cjk_count > 0 and cjk_count / len(non_ascii) >= 0.5
    if encoding == "shift_jis":
        return kana_count > 0 or (cjk_count > 0 and cjk_count / len(non_ascii) >= 0.5)
    if encoding == "euc_kr":
        return hangul_count > 0 or (cjk_count > 0 and cjk_count / len(non_ascii) >= 0.5)
    if encoding == "cp1252":
        non_ascii_ratio = len(non_ascii) / len(text)
        latin_count = _count_in_ranges(text, ((0x00C0, 0x024F),))
        return non_ascii_ratio <= 0.4 and latin_count > 0
    return False


def decode_subtitle(raw: bytes, encoding_override: str | None = None) -> tuple[str, str]:
    """严格解码字节；传统编码有多个合理候选时拒绝猜测。"""

    if not raw:
        raise SubtitleError("输入文件为空")

    if encoding_override:
        try:
            canonical_name = codecs.lookup(encoding_override).name
        except LookupError as exc:
            raise SubtitleError(f"未知编码 {encoding_override!r}，请使用 Python 支持的编码名称") from exc
        try:
            decoded = raw.decode(encoding_override, errors="strict")
        except UnicodeDecodeError as exc:
            raise SubtitleError(f"无法使用指定编码 {encoding_override!r} 严格解码输入：{exc}") from exc
        if not is_basic_text_plausible(decoded):
            raise SubtitleError(f"使用指定编码 {encoding_override!r} 解码后不像有效文本")
        return normalize_newlines(decoded), canonical_name

    bom_encodings = (
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
    )
    for bom, encoding in bom_encodings:
        if raw.startswith(bom):
            try:
                decoded = raw.decode(encoding, errors="strict")
            except UnicodeDecodeError as exc:
                raise SubtitleError(f"文件带有 {encoding} BOM，但内容无法严格解码：{exc}") from exc
            if not is_basic_text_plausible(decoded):
                raise SubtitleError(f"文件带有 {encoding} BOM，但解码后不像有效文本")
            return normalize_newlines(decoded), encoding

    try:
        decoded_utf8 = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        decoded_utf8 = None
    if decoded_utf8 is not None and is_basic_text_plausible(decoded_utf8):
        return normalize_newlines(decoded_utf8), "utf-8"

    candidates: list[tuple[str, str]] = []
    for encoding in LEGACY_ENCODINGS:
        try:
            decoded = raw.decode(encoding, errors="strict")
        except UnicodeDecodeError:
            continue
        if is_legacy_candidate_plausible(decoded, encoding):
            candidates.append((encoding, decoded))

    if not candidates:
        raise SubtitleError("无法可靠识别字幕编码；请使用 --encoding 明确指定编码")
    if len(candidates) > 1:
        names = "、".join(encoding for encoding, _decoded in candidates)
        raise SubtitleError(f"字幕编码存在歧义（候选：{names}）；请使用 --encoding 明确指定编码")
    encoding, decoded = candidates[0]
    return normalize_newlines(decoded), encoding


def _formats_are_compatible(first: str, second: str) -> bool:
    return first == second or {first, second} <= {"ass", "ssa"}


def detect_subtitle_format(
    text: str,
    path: Path,
    format_override: str | None = None,
) -> tuple[str, tuple[str, ...]]:
    """按显式覆盖、内容特征、扩展名的优先级确定字幕格式。"""

    if format_override:
        if format_override not in SUPPORTED_FORMATS:
            raise SubtitleError(f"不支持的格式 {format_override!r}")
        return format_override, ()

    stripped = text.lstrip()
    content_format: str | None = None
    if stripped.startswith("WEBVTT"):
        content_format = "vtt"
    elif re.search(r"^\s*\[Events\]\s*$", text, re.MULTILINE | re.IGNORECASE) and re.search(
        r"^\s*Dialogue\s*:", text, re.MULTILINE | re.IGNORECASE
    ):
        content_format = "ass"
    elif SRT_TIMESTAMP_RE.search(text):
        content_format = "srt"
    elif VTT_TIMESTAMP_RE.search(text):
        content_format = "vtt"
    elif LRC_TIME_PREFIX_RE.search(text):
        content_format = "lrc"

    extension_format = EXTENSION_FORMATS.get(path.suffix.lower())
    warnings: list[str] = []
    if content_format:
        if extension_format and not _formats_are_compatible(content_format, extension_format):
            warnings.append(
                f"文件扩展名表示 {extension_format}，但内容特征表示 {content_format}；已采用内容特征"
            )
        if content_format == "ass" and extension_format == "ssa":
            return "ssa", tuple(warnings)
        return content_format, tuple(warnings)
    if extension_format:
        return extension_format, ()
    raise SubtitleError("无法可靠识别字幕格式；请使用 --format 明确指定格式")


def clean_text_fragment(value: str) -> str:
    """移除受支持样式并保守规范化单段字幕文本。"""

    value = ASS_OVERRIDE_RE.sub("", value)
    value = HTML_STYLE_RE.sub("", value)
    value = html.unescape(value)
    value = unicodedata.normalize("NFC", value)
    value = WHITESPACE_RE.sub(" ", value)
    return value.strip()


def _join_clean_lines(lines: Sequence[str]) -> str:
    return " ".join(cleaned for line in lines if (cleaned := clean_text_fragment(line)))


def parse_srt(text: str) -> list[Cue]:
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        timestamp_index = next(
            (index for index, line in enumerate(lines) if SRT_TIMESTAMP_RE.fullmatch(line)),
            None,
        )
        if timestamp_index is None:
            continue
        cue_text = _join_clean_lines(lines[timestamp_index + 1 :])
        if cue_text:
            cues.append(Cue(cue_text))
    return cues


def _split_vtt_blocks(text: str) -> list[list[str]]:
    lines = text.splitlines()
    if lines and lines[0].lstrip("\ufeff").startswith("WEBVTT"):
        lines = lines[1:]
    return [block.splitlines() for block in re.split(r"\n\s*\n", "\n".join(lines))]


def parse_vtt(text: str) -> list[Cue]:
    cues: list[Cue] = []
    for lines in _split_vtt_blocks(text):
        stripped_lines = [line.strip() for line in lines if line.strip()]
        if not stripped_lines:
            continue
        if stripped_lines[0].upper().startswith(("NOTE", "STYLE", "REGION")):
            continue
        timestamp_index = next(
            (index for index, line in enumerate(stripped_lines) if VTT_TIMESTAMP_RE.fullmatch(line)),
            None,
        )
        if timestamp_index is None:
            continue
        body_lines = stripped_lines[timestamp_index + 1 :]
        if not body_lines:
            continue
        speaker: str | None = None
        voice_match = VTT_VOICE_OPEN_RE.match(body_lines[0])
        if voice_match:
            raw_speaker = voice_match.group(1)
            if raw_speaker:
                speaker = clean_text_fragment(raw_speaker)
            body_lines[0] = VTT_VOICE_OPEN_RE.sub("", body_lines[0], count=1)
        body_lines = [VTT_VOICE_CLOSE_RE.sub("", line) for line in body_lines]
        cue_text = _join_clean_lines(body_lines)
        if cue_text:
            cues.append(Cue(cue_text, speaker or None))
    return cues


def parse_ass(text: str) -> list[Cue]:
    cues: list[Cue] = []
    in_events = False
    fields: list[str] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            in_events = line.casefold() == "[events]"
            continue
        if not in_events:
            continue
        key, separator, value = line.partition(":")
        if not separator:
            continue
        key = key.strip().casefold()
        if key == "format":
            fields = [field.strip().casefold() for field in value.split(",")]
            continue
        if key != "dialogue":
            continue
        if not fields or "text" not in fields:
            raise SubtitleError("ASS/SSA 的 [Events] 缺少包含 Text 字段的 Format 行")
        values = [item.strip() for item in value.split(",", maxsplit=len(fields) - 1)]
        if len(values) != len(fields):
            raise SubtitleError("ASS/SSA Dialogue 字段数与 Format 定义不一致")
        record = dict(zip(fields, values, strict=True))
        raw_text = record["text"].replace(r"\N", " ").replace(r"\n", " ").replace(r"\h", " ")
        cue_text = clean_text_fragment(raw_text)
        speaker = clean_text_fragment(record.get("name") or record.get("actor") or "") or None
        if cue_text:
            cues.append(Cue(cue_text, speaker))
    return cues


def parse_lrc(text: str) -> list[Cue]:
    cues: list[Cue] = []
    for raw_line in text.splitlines():
        if LRC_METADATA_RE.fullmatch(raw_line):
            continue
        match = LRC_TIME_PREFIX_RE.match(raw_line)
        if match:
            value = raw_line[match.end() :]
            value = LRC_INLINE_TIME_RE.sub("", value)
            cleaned = clean_text_fragment(value)
            if cleaned:
                cues.append(Cue(cleaned))
            continue
        cleaned = clean_text_fragment(LRC_INLINE_TIME_RE.sub("", raw_line))
        if cleaned:
            cues.append(Cue(cleaned, timed=False))
    return cues


def _boundary_before(value: str, index: int) -> bool:
    return index == 0 or value[index - 1].isspace() or value[index - 1] in PUNCTUATION_BOUNDARY


def _boundary_after(value: str, index: int) -> bool:
    return index == len(value) or value[index].isspace() or value[index] in PUNCTUATION_BOUNDARY


def exact_suffix_prefix_overlap(previous: str, current: str) -> int:
    """返回严格相等且位于文本边界的最长后缀—前缀长度。"""

    maximum = min(len(previous), len(current))
    for length in range(maximum, 0, -1):
        if previous[-length:] != current[:length]:
            continue
        if length in {len(previous), len(current)}:
            return length
        if _boundary_before(previous, len(previous) - length) and _boundary_after(current, length):
            return length
    return 0


def deduplicate_timed_cues(cues: Sequence[Cue]) -> list[Cue]:
    """只合并同讲者的精确重复和精确滚动重叠。"""

    output: list[Cue] = []
    for cue in cues:
        if not output or output[-1].speaker != cue.speaker:
            output.append(cue)
            continue
        previous = output[-1]
        if previous.text == cue.text:
            continue
        if not previous.timed or not cue.timed:
            output.append(cue)
            continue
        overlap = exact_suffix_prefix_overlap(previous.text, cue.text)
        if not overlap:
            output.append(cue)
            continue
        if overlap == len(cue.text):
            continue
        merged = previous.text + cue.text[overlap:]
        output[-1] = Cue(merged.strip(), previous.speaker, timed=True)
    return output


def render_cues(cues: Sequence[Cue]) -> str:
    lines: list[str] = []
    for cue in deduplicate_timed_cues(cues):
        if cue.speaker:
            lines.append(f"{cue.speaker}：{cue.text}")
        else:
            lines.append(cue.text)
    return "\n".join(lines)


def normalize_plain_lines(lines: Sequence[str]) -> str:
    """保留段落结构，仅删除直接相邻的完全相同行。"""

    output: list[str] = []
    previous_nonblank: str | None = None
    separated = False
    for raw_line in lines:
        cleaned = clean_text_fragment(raw_line)
        if not cleaned:
            if output and output[-1] != "":
                output.append("")
            separated = True
            continue
        if cleaned == previous_nonblank and not separated:
            continue
        output.append(cleaned)
        previous_nonblank = cleaned
        separated = False
    while output and output[-1] == "":
        output.pop()
    return "\n".join(output)


def parse_text_transcript(text: str) -> str:
    lines = text.splitlines()
    retained: list[str] = []
    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        next_line = lines[index + 1].strip() if index + 1 < len(lines) else ""
        if stripped.isdigit() and GENERIC_TIMESTAMP_RE.fullmatch(next_line):
            continue
        if GENERIC_TIMESTAMP_RE.fullmatch(stripped):
            continue
        retained.append(raw_line)
    return normalize_plain_lines(retained)


def normalize_subtitle(
    raw: bytes,
    input_path: Path,
    *,
    encoding_override: str | None = None,
    format_override: str | None = None,
) -> NormalizationResult:
    """规范化一个字幕字节串，不执行翻译或总结。"""

    text, encoding = decode_subtitle(raw, encoding_override)
    format_name, warnings = detect_subtitle_format(text, input_path, format_override)

    if format_name == "srt":
        normalized = render_cues(parse_srt(text))
    elif format_name == "vtt":
        normalized = render_cues(parse_vtt(text))
    elif format_name in {"ass", "ssa"}:
        normalized = render_cues(parse_ass(text))
    elif format_name == "lrc":
        normalized = render_cues(parse_lrc(text))
    else:
        normalized = parse_text_transcript(text)

    normalized = normalized.strip()
    if not normalized:
        raise SubtitleError("清洗后没有可用的字幕正文")
    return NormalizationResult(normalized + "\n", format_name, encoding, warnings)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="识别、解析并规范化字幕文件。")
    parser.add_argument("input", type=Path, help="输入字幕文件")
    parser.add_argument("-o", "--output", type=Path, help="输出 UTF-8 文本文件；默认写入 stdout")
    parser.add_argument("--encoding", help="显式指定输入编码，例如 utf-8、gb18030 或 cp1252")
    parser.add_argument("--format", choices=SUPPORTED_FORMATS, dest="format_name", help="显式指定字幕格式")
    return parser


def _write_output_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(text)
            temporary_path = Path(handle.name)
        os.replace(temporary_path, path)
    except OSError:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except OSError:
                pass
        raise


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        raw = args.input.read_bytes()
        result = normalize_subtitle(
            raw,
            args.input,
            encoding_override=args.encoding,
            format_override=args.format_name,
        )
        if args.output:
            if args.output.resolve() == args.input.resolve():
                raise SubtitleError("输出路径不能与输入文件相同")
            _write_output_atomic(args.output, result.text)
        else:
            sys.stdout.write(result.text)
        print(f"检测格式：{result.format_name}；编码：{result.encoding}", file=sys.stderr)
        for warning in result.warnings:
            print(f"警告：{warning}", file=sys.stderr)
        return 0
    except (OSError, SubtitleError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
