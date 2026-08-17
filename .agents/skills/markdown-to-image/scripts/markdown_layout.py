#!/usr/bin/env python3
"""受限 Markdown 的确定性解析、分页和 SVG 渲染。"""

from __future__ import annotations

import html
import math
import re
import unicodedata
from dataclasses import dataclass, replace


PAGE_WIDTH = 1080
PAGE_HEIGHT = 1440
LONG_IMAGE_MAX_HEIGHT = 30000
LONG_IMAGE_BOTTOM_PADDING = 88
PAGE_MARGIN = 88
CONTENT_TOP = 88
CONTENT_BOTTOM = 1320
CONTENT_WIDTH = PAGE_WIDTH - PAGE_MARGIN * 2

BACKGROUND = "#F7F5F0"
TEXT = "#27313A"
MUTED = "#69747D"
ACCENT = "#39706D"
CODE_BACKGROUND = "#ECEFEB"
CODE_TEXT = "#35424B"
RULE = "#D9DED9"

SANS_FONT = (
    "-apple-system, BlinkMacSystemFont, &quot;Segoe UI&quot;, "
    "&quot;Noto Sans CJK SC&quot;, &quot;PingFang SC&quot;, "
    "&quot;Microsoft YaHei&quot;, sans-serif"
)
MONO_FONT = (
    "SFMono-Regular, Consolas, &quot;Liberation Mono&quot;, "
    "&quot;Noto Sans Mono CJK SC&quot;, monospace"
)

HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})([^`]*)$")
UL_RE = re.compile(r"^([-+*])[ \t]+(.+)$")
OL_RE = re.compile(r"^(\d+)[.)][ \t]+(.+)$")
NESTED_LIST_RE = re.compile(r"^[ \t]+(?:[-+*]|\d+[.)])[ \t]+")
TASK_RE = re.compile(r"^ {0,3}[-+*][ \t]+\[[ xX]\][ \t]+")
HTML_RE = re.compile(r"</?[A-Za-z][^>]*>|<!--[\s\S]*?-->|<![A-Z][^>]*>")
TABLE_DELIMITER_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)
TOKEN_RE = re.compile(
    r"\n|[ \t]+|[A-Za-z0-9]+(?:[-_./:@%+?&=#][A-Za-z0-9]+)*|.",
    re.DOTALL,
)


class MarkdownLayoutError(ValueError):
    """带稳定 code 和源行号的输入错误。"""

    def __init__(self, code: str, line: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.line = line
        self.message = message

    def __str__(self) -> str:
        return f"第 {self.line} 行：{self.message}（{self.code}）"


@dataclass(frozen=True, slots=True)
class Inline:
    text: str
    bold: bool = False
    italic: bool = False
    code: bool = False
    link: bool = False
    link_url: bool = False


@dataclass(frozen=True, slots=True)
class Block:
    kind: str
    line: int
    inlines: tuple[Inline, ...] = ()
    marker: str = ""
    language: str = ""
    code_lines: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TextRun:
    text: str
    width: float
    bold: bool = False
    italic: bool = False
    code: bool = False
    link: bool = False
    link_url: bool = False


@dataclass(frozen=True, slots=True)
class TextLine:
    runs: tuple[TextRun, ...]
    width: float

    @property
    def text(self) -> str:
        return "".join(run.text for run in self.runs)


@dataclass(frozen=True, slots=True)
class RenderBlock:
    kind: str
    source_line: int
    lines: tuple[TextLine, ...]
    x: float
    width: float
    font_size: float
    line_height: float
    margin_before: float
    margin_after: float
    padding_top: float = 0
    padding_bottom: float = 0
    marker: str = ""
    language: str = ""
    heading_level: int = 0

    @property
    def splittable(self) -> bool:
        return self.kind not in {"hr"}


@dataclass(frozen=True, slots=True)
class Fragment:
    block: RenderBlock
    lines: tuple[TextLine, ...]
    y: float
    height: float
    first: bool
    last: bool


@dataclass(frozen=True, slots=True)
class Page:
    number: int
    fragments: tuple[Fragment, ...]


@dataclass(frozen=True, slots=True)
class LongImage:
    height: int
    fragments: tuple[Fragment, ...]


def _merge_inlines(values: list[Inline]) -> tuple[Inline, ...]:
    merged: list[Inline] = []
    for value in values:
        if not value.text:
            continue
        if merged and replace(merged[-1], text="") == replace(value, text=""):
            merged[-1] = replace(merged[-1], text=merged[-1].text + value.text)
        else:
            merged.append(value)
    return tuple(merged)


def parse_inlines(
    text: str,
    line: int,
    *,
    bold: bool = False,
    italic: bool = False,
    link: bool = False,
) -> tuple[Inline, ...]:
    """解析非嵌套歧义下的常用行内 Markdown，并保留链接目标。"""

    values: list[Inline] = []
    plain: list[str] = []

    def flush() -> None:
        if plain:
            values.append(Inline("".join(plain), bold=bold, italic=italic, link=link))
            plain.clear()

    index = 0
    while index < len(text):
        if text[index] == "\\" and index + 1 < len(text):
            plain.append(text[index + 1])
            index += 2
            continue

        if text[index] == "`":
            closing = text.find("`", index + 1)
            if closing < 0:
                raise MarkdownLayoutError("INLINE_CODE_UNCLOSED", line, "行内代码缺少结束反引号")
            flush()
            values.append(
                Inline(
                    text[index + 1 : closing],
                    bold=bold,
                    italic=italic,
                    code=True,
                    link=link,
                )
            )
            index = closing + 1
            continue

        if text[index] == "[":
            label_end = text.find("]", index + 1)
            if label_end >= 0 and label_end + 1 < len(text) and text[label_end + 1] == "(":
                target_end = text.find(")", label_end + 2)
                if target_end < 0:
                    raise MarkdownLayoutError("LINK_UNCLOSED", line, "链接缺少结束右括号")
                label = text[index + 1 : label_end]
                target = text[label_end + 2 : target_end].strip()
                if not label or not target or "\n" in target:
                    raise MarkdownLayoutError("LINK_INVALID", line, "链接文本和目标均不能为空")
                flush()
                values.extend(parse_inlines(label, line, bold=bold, italic=italic, link=True))
                values.append(Inline(f"（{target}）", link_url=True))
                index = target_end + 1
                continue

        delimiter = ""
        next_bold = bold
        next_italic = italic
        if text.startswith("**", index) or text.startswith("__", index):
            delimiter = text[index : index + 2]
            next_bold = True
        elif text[index] in "*_":
            candidate = text[index]
            previous = text[index - 1] if index else ""
            following = text[index + 1] if index + 1 < len(text) else ""
            if candidate == "_" and previous.isalnum() and following.isalnum():
                plain.append(candidate)
                index += 1
                continue
            delimiter = candidate
            next_italic = True

        if delimiter:
            closing = text.find(delimiter, index + len(delimiter))
            if closing >= index + len(delimiter) + 1:
                flush()
                values.extend(
                    parse_inlines(
                        text[index + len(delimiter) : closing],
                        line,
                        bold=next_bold,
                        italic=next_italic,
                        link=link,
                    )
                )
                index = closing + len(delimiter)
                continue

        plain.append(text[index])
        index += 1

    flush()
    return _merge_inlines(values)


def _is_hr(line: str) -> bool:
    stripped = line.strip()
    if len(stripped) < 3:
        return False
    compact = stripped.replace(" ", "").replace("\t", "")
    return len(compact) >= 3 and len(set(compact)) == 1 and compact[0] in "*-_"


def _raise_unsupported(lines: list[str], index: int) -> None:
    line = lines[index]
    line_number = index + 1
    if "![" in line:
        raise MarkdownLayoutError("IMAGE_UNSUPPORTED", line_number, "第一版不支持 Markdown 图片")
    if TASK_RE.match(line):
        raise MarkdownLayoutError("TASK_LIST_UNSUPPORTED", line_number, "第一版不支持任务列表")
    if NESTED_LIST_RE.match(line):
        raise MarkdownLayoutError("NESTED_LIST_UNSUPPORTED", line_number, "第一版只支持单层列表")
    if line.startswith("    ") or line.startswith("\t"):
        raise MarkdownLayoutError(
            "INDENTED_CODE_UNSUPPORTED",
            line_number,
            "第一版只支持使用反引号或波浪线围栏的代码块",
        )
    if HTML_RE.search(line):
        raise MarkdownLayoutError("RAW_HTML_UNSUPPORTED", line_number, "第一版不支持原始 HTML")
    if TABLE_DELIMITER_RE.match(line):
        raise MarkdownLayoutError("TABLE_UNSUPPORTED", line_number, "第一版不支持表格")
    if index + 1 < len(lines) and "|" in line and TABLE_DELIMITER_RE.match(lines[index + 1]):
        raise MarkdownLayoutError("TABLE_UNSUPPORTED", line_number, "第一版不支持表格")


def _starts_block(lines: list[str], index: int) -> bool:
    line = lines[index]
    return bool(
        not line.strip()
        or HEADING_RE.match(line)
        or FENCE_RE.match(line)
        or line.startswith(">")
        or UL_RE.match(line)
        or OL_RE.match(line)
        or _is_hr(line)
        or TASK_RE.match(line)
        or NESTED_LIST_RE.match(line)
        or TABLE_DELIMITER_RE.match(line)
        or line.startswith("    ")
        or line.startswith("\t")
    )


def _join_soft_lines(lines: list[str]) -> str:
    result = ""
    previous_hard_break = False
    for raw in lines:
        hard_break = raw.endswith("  ") or raw.endswith("\\")
        value = raw[:-1] if raw.endswith("\\") else raw.rstrip()
        if result:
            result += "\n" if previous_hard_break else " "
        result += value.strip()
        previous_hard_break = hard_break
    return result


def parse_markdown(text: str) -> tuple[Block, ...]:
    """把 UTF-8 Markdown 文本解析为受支持的块结构。"""

    if "\x00" in text:
        raise MarkdownLayoutError("NUL_INVALID", 1, "Markdown 不得包含 NUL 字符")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[Block] = []
    index = 0
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue

        _raise_unsupported(lines, index)
        line = lines[index]
        line_number = index + 1

        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            language = fence.group(2).strip()
            code: list[str] = []
            index += 1
            while index < len(lines):
                candidate = lines[index]
                stripped = candidate.strip()
                if stripped and set(stripped) == {marker[0]} and len(stripped) >= len(marker):
                    break
                code.append(candidate)
                index += 1
            if index >= len(lines):
                raise MarkdownLayoutError("CODE_FENCE_UNCLOSED", line_number, "代码块缺少结束围栏")
            blocks.append(
                Block("code", line_number, language=language, code_lines=tuple(code or [""]))
            )
            index += 1
            continue

        heading = HEADING_RE.match(line)
        if heading:
            content = re.sub(r"\s+#+\s*$", "", heading.group(2)).strip()
            if not content:
                raise MarkdownLayoutError("HEADING_EMPTY", line_number, "标题不能为空")
            blocks.append(
                Block(
                    f"h{len(heading.group(1))}",
                    line_number,
                    inlines=parse_inlines(content, line_number),
                )
            )
            index += 1
            continue

        if _is_hr(line):
            blocks.append(Block("hr", line_number))
            index += 1
            continue

        if line.startswith(">"):
            quote_lines: list[str] = []
            while index < len(lines) and lines[index].startswith(">"):
                current = lines[index]
                if current.startswith(">>") or current.startswith("> >"):
                    raise MarkdownLayoutError(
                        "NESTED_QUOTE_UNSUPPORTED", index + 1, "第一版只支持单层引用"
                    )
                quote_lines.append(current[1:].lstrip())
                index += 1
            content = _join_soft_lines(quote_lines)
            if content:
                blocks.append(
                    Block("quote", line_number, inlines=parse_inlines(content, line_number))
                )
            continue

        list_match = UL_RE.match(line) or OL_RE.match(line)
        if list_match:
            is_ordered = bool(OL_RE.match(line))
            marker = f"{list_match.group(1)}." if is_ordered else "•"
            content_parts = [list_match.group(2)]
            index += 1
            while index < len(lines) and lines[index].strip():
                continuation = lines[index]
                if NESTED_LIST_RE.match(continuation):
                    raise MarkdownLayoutError(
                        "NESTED_LIST_UNSUPPORTED", index + 1, "第一版只支持单层列表"
                    )
                if continuation.startswith(("  ", "\t")):
                    content_parts.append(continuation.strip())
                    index += 1
                    continue
                break
            content = _join_soft_lines(content_parts)
            blocks.append(
                Block(
                    "ol_item" if is_ordered else "ul_item",
                    line_number,
                    inlines=parse_inlines(content, line_number),
                    marker=marker,
                )
            )
            continue

        paragraph_lines = [line]
        index += 1
        while index < len(lines) and not _starts_block(lines, index):
            _raise_unsupported(lines, index)
            paragraph_lines.append(lines[index])
            index += 1
        content = _join_soft_lines(paragraph_lines)
        blocks.append(Block("paragraph", line_number, inlines=parse_inlines(content, line_number)))

    if not blocks:
        raise MarkdownLayoutError("MARKDOWN_EMPTY", 1, "Markdown 内容为空")
    return tuple(blocks)


def _effective_font_size(inline: Inline | TextRun, font_size: float) -> float:
    return font_size * 0.72 if inline.link_url else font_size


def _char_width(character: str, font_size: float, *, code: bool = False) -> float:
    if character == "\t":
        return font_size * (2.48 if code else 1.28)
    if character.isspace():
        return font_size * (0.62 if code else 0.32)
    if unicodedata.combining(character):
        return 0
    east_asian = unicodedata.east_asian_width(character)
    if east_asian in {"W", "F"} or unicodedata.category(character) == "So":
        return font_size
    if code:
        return font_size * 0.62
    if character.isupper():
        return font_size * 0.62
    if character.islower():
        return font_size * 0.54
    if character.isdigit():
        return font_size * 0.56
    return font_size * 0.46


def _text_width(text: str, inline: Inline, font_size: float) -> float:
    effective = _effective_font_size(inline, font_size)
    return sum(_char_width(char, effective, code=inline.code) for char in text)


def _append_run(runs: list[TextRun], text: str, inline: Inline, font_size: float) -> None:
    if not text:
        return
    width = _text_width(text, inline, font_size)
    candidate = TextRun(
        text,
        width,
        bold=inline.bold,
        italic=inline.italic,
        code=inline.code,
        link=inline.link,
        link_url=inline.link_url,
    )
    if runs and replace(runs[-1], text="", width=0) == replace(candidate, text="", width=0):
        previous = runs[-1]
        runs[-1] = replace(previous, text=previous.text + text, width=previous.width + width)
    else:
        runs.append(candidate)


def wrap_inlines(
    inlines: tuple[Inline, ...],
    max_width: float,
    font_size: float,
) -> tuple[TextLine, ...]:
    """按保守字宽模型换行，避免不同系统字体造成右侧裁切。"""

    lines: list[TextLine] = []
    runs: list[TextRun] = []
    width = 0.0

    def flush(*, keep_empty: bool = False) -> None:
        nonlocal runs, width
        while runs and runs[-1].text.isspace():
            width -= runs[-1].width
            runs.pop()
        if runs or keep_empty:
            lines.append(TextLine(tuple(runs), max(width, 0)))
        runs = []
        width = 0.0

    for inline in inlines:
        for token in TOKEN_RE.findall(inline.text):
            if token == "\n":
                flush(keep_empty=True)
                continue
            if token.isspace() and not inline.code:
                token = " "
                if not runs:
                    continue
            token_width = _text_width(token, inline, font_size)
            if runs and width + token_width > max_width:
                flush()
                if token.isspace() and not inline.code:
                    continue
            if token_width <= max_width:
                _append_run(runs, token, inline, font_size)
                width += token_width
                continue
            piece = ""
            piece_width = 0.0
            for character in token:
                char_width = _text_width(character, inline, font_size)
                if piece and piece_width + char_width > max_width:
                    _append_run(runs, piece, inline, font_size)
                    width += piece_width
                    flush()
                    piece = ""
                    piece_width = 0.0
                piece += character
                piece_width += char_width
            if piece:
                _append_run(runs, piece, inline, font_size)
                width += piece_width
    flush()
    return tuple(lines or [TextLine((), 0)])


def _heading_style(level: int) -> tuple[float, float, float, float]:
    styles = {
        1: (58, 76, 12, 38),
        2: (48, 66, 34, 26),
        3: (42, 60, 30, 22),
        4: (38, 56, 26, 18),
        5: (35, 52, 24, 16),
        6: (33, 50, 22, 14),
    }
    return styles[level]


def build_render_blocks(blocks: tuple[Block, ...]) -> tuple[RenderBlock, ...]:
    rendered: list[RenderBlock] = []
    for block in blocks:
        if re.fullmatch(r"h[1-6]", block.kind):
            level = int(block.kind[1])
            size, height, before, after = _heading_style(level)
            rendered.append(
                RenderBlock(
                    block.kind,
                    block.line,
                    wrap_inlines(block.inlines, CONTENT_WIDTH, size),
                    PAGE_MARGIN,
                    CONTENT_WIDTH,
                    size,
                    height,
                    before,
                    after,
                    heading_level=level,
                )
            )
        elif block.kind == "paragraph":
            rendered.append(
                RenderBlock(
                    block.kind,
                    block.line,
                    wrap_inlines(block.inlines, CONTENT_WIDTH, 38),
                    PAGE_MARGIN,
                    CONTENT_WIDTH,
                    38,
                    60,
                    0,
                    28,
                )
            )
        elif block.kind == "quote":
            x = PAGE_MARGIN + 40
            width = CONTENT_WIDTH - 40
            rendered.append(
                RenderBlock(
                    block.kind,
                    block.line,
                    wrap_inlines(block.inlines, width - 18, 34),
                    x,
                    width - 18,
                    34,
                    56,
                    10,
                    28,
                    padding_top=12,
                    padding_bottom=12,
                )
            )
        elif block.kind in {"ul_item", "ol_item"}:
            x = PAGE_MARGIN + 52
            width = CONTENT_WIDTH - 52
            rendered.append(
                RenderBlock(
                    block.kind,
                    block.line,
                    wrap_inlines(block.inlines, width, 36),
                    x,
                    width,
                    36,
                    56,
                    4,
                    12,
                    marker=block.marker,
                )
            )
        elif block.kind == "code":
            x = PAGE_MARGIN + 28
            width = CONTENT_WIDTH - 56
            code_lines: list[TextLine] = []
            for source_line in block.code_lines:
                inline = Inline(source_line, code=True)
                code_lines.extend(wrap_inlines((inline,), width, 29))
            rendered.append(
                RenderBlock(
                    block.kind,
                    block.line,
                    tuple(code_lines),
                    x,
                    width,
                    29,
                    46,
                    12,
                    30,
                    padding_top=54 if block.language else 28,
                    padding_bottom=28,
                    language=block.language,
                )
            )
        elif block.kind == "hr":
            rendered.append(
                RenderBlock(
                    block.kind,
                    block.line,
                    (),
                    PAGE_MARGIN,
                    CONTENT_WIDTH,
                    0,
                    0,
                    18,
                    24,
                    padding_top=24,
                    padding_bottom=24,
                )
            )
        else:
            raise AssertionError(f"未知块类型：{block.kind}")
    return tuple(rendered)


def _fragment_height(block: RenderBlock, line_count: int) -> float:
    if block.kind == "hr":
        return block.padding_top + block.padding_bottom
    return block.padding_top + block.padding_bottom + line_count * block.line_height


def _minimum_following_height(block: RenderBlock) -> float:
    if block.kind == "hr":
        return _fragment_height(block, 0)
    return block.padding_top + min(2, len(block.lines)) * block.line_height + block.padding_bottom


def paginate(blocks: tuple[RenderBlock, ...]) -> tuple[Page, ...]:
    """按块边界分页，并在必须拆分时避免段落单行孤行。"""

    pages: list[list[Fragment]] = [[]]
    cursor = float(CONTENT_TOP)

    def new_page() -> None:
        nonlocal cursor
        if pages[-1]:
            pages.append([])
        cursor = float(CONTENT_TOP)

    for block_index, block in enumerate(blocks):
        remaining_lines = list(block.lines)
        first = True

        if block.heading_level and block_index + 1 < len(blocks) and pages[-1]:
            following = blocks[block_index + 1]
            needed = (
                block.margin_before
                + _fragment_height(block, len(block.lines))
                + block.margin_after
                + following.margin_before
                + _minimum_following_height(following)
            )
            if CONTENT_BOTTOM - cursor < needed:
                new_page()

        if block.kind == "hr":
            margin = 0 if not pages[-1] else block.margin_before
            height = _fragment_height(block, 0)
            if cursor + margin + height > CONTENT_BOTTOM and pages[-1]:
                new_page()
                margin = 0
            cursor += margin
            pages[-1].append(Fragment(block, (), cursor, height, True, True))
            cursor += height + block.margin_after
            continue

        while remaining_lines:
            margin = block.margin_before if first and pages[-1] else 0
            fixed = block.padding_top + block.padding_bottom
            available = CONTENT_BOTTOM - cursor - margin
            capacity = int((available - fixed) // block.line_height)
            if capacity <= 0:
                new_page()
                continue

            take = min(capacity, len(remaining_lines))
            if len(remaining_lines) > take:
                if take == 1 and len(remaining_lines) > 2:
                    new_page()
                    continue
                if len(remaining_lines) - take == 1 and take > 2:
                    take -= 1
            fragment_lines = tuple(remaining_lines[:take])
            del remaining_lines[:take]
            last = not remaining_lines
            height = _fragment_height(block, len(fragment_lines))
            cursor += margin
            pages[-1].append(Fragment(block, fragment_lines, cursor, height, first, last))
            cursor += height
            if last:
                cursor = min(float(CONTENT_BOTTOM), cursor + block.margin_after)
            else:
                new_page()
            first = False

    return tuple(Page(index + 1, tuple(fragments)) for index, fragments in enumerate(pages) if fragments)


def layout_markdown(text: str) -> tuple[Page, ...]:
    return paginate(build_render_blocks(parse_markdown(text)))


def layout_long_image(text: str) -> LongImage:
    """把全部内容连续排入单张定宽长图，不做分页拆分。"""

    blocks = build_render_blocks(parse_markdown(text))
    fragments: list[Fragment] = []
    cursor = float(CONTENT_TOP)

    for block in blocks:
        margin = block.margin_before if fragments else 0
        cursor += margin
        height = _fragment_height(block, len(block.lines))
        fragments.append(
            Fragment(block, block.lines, cursor, height, True, True)
        )
        cursor += height + block.margin_after

    image_height = max(PAGE_HEIGHT, math.ceil(cursor + LONG_IMAGE_BOTTOM_PADDING))
    if image_height > LONG_IMAGE_MAX_HEIGHT:
        raise MarkdownLayoutError(
            "LONG_IMAGE_TOO_TALL",
            blocks[-1].source_line,
            (
                f"单张长图高度预计为 {image_height}px，超过 "
                f"{LONG_IMAGE_MAX_HEIGHT}px 上限；请显式改用分页模式"
            ),
        )
    return LongImage(image_height, tuple(fragments))


def _render_run(run: TextRun, block: RenderBlock, x: float, baseline: float) -> tuple[str, float]:
    size = _effective_font_size(run, block.font_size)
    fill = MUTED if run.link_url else ACCENT if run.link else CODE_TEXT if run.code else TEXT
    family = MONO_FONT if run.code or block.kind == "code" else SANS_FONT
    weight = "700" if run.bold or block.heading_level else "400"
    style = "italic" if run.italic else "normal"
    escaped = html.escape(run.text, quote=True)
    parts: list[str] = []
    if run.code and block.kind != "code" and run.text.strip():
        parts.append(
            f'<rect x="{x - 4:.1f}" y="{baseline - size * 0.86:.1f}" '
            f'width="{run.width + 8:.1f}" height="{size * 1.16:.1f}" rx="7" '
            f'fill="{CODE_BACKGROUND}"/>'
        )
    decoration = ' text-decoration="underline"' if run.link else ""
    parts.append(
        f'<text x="{x:.1f}" y="{baseline:.1f}" font-family="{family}" '
        f'font-size="{size:.1f}" font-weight="{weight}" font-style="{style}" '
        f'fill="{fill}"{decoration}>{escaped}</text>'
    )
    return "".join(parts), x + run.width


def _render_fragment(fragment: Fragment) -> str:
    block = fragment.block
    parts: list[str] = []
    if block.kind == "hr":
        y = fragment.y + fragment.height / 2
        return (
            f'<line x1="{PAGE_MARGIN}" y1="{y:.1f}" x2="{PAGE_WIDTH - PAGE_MARGIN}" '
            f'y2="{y:.1f}" stroke="{RULE}" stroke-width="2"/>'
        )
    if block.kind == "code":
        parts.append(
            f'<rect x="{PAGE_MARGIN}" y="{fragment.y:.1f}" width="{CONTENT_WIDTH}" '
            f'height="{fragment.height:.1f}" rx="20" fill="{CODE_BACKGROUND}"/>'
        )
        label = block.language if fragment.first and block.language else "代码（续）" if not fragment.first else ""
        if label:
            parts.append(
                f'<text x="{block.x:.1f}" y="{fragment.y + 30:.1f}" '
                f'font-family="{MONO_FONT}" font-size="21" font-weight="700" '
                f'fill="{MUTED}">{html.escape(label, quote=True)}</text>'
            )
    elif block.kind == "quote":
        parts.append(
            f'<rect x="{PAGE_MARGIN}" y="{fragment.y:.1f}" width="7" '
            f'height="{fragment.height:.1f}" rx="3.5" fill="{ACCENT}" opacity="0.9"/>'
        )

    baseline = fragment.y + block.padding_top + block.font_size
    for line_index, line in enumerate(fragment.lines):
        if block.kind in {"ul_item", "ol_item"} and fragment.first and line_index == 0:
            parts.append(
                f'<text x="{PAGE_MARGIN + 8}" y="{baseline:.1f}" '
                f'font-family="{SANS_FONT}" font-size="{block.font_size:.1f}" '
                f'font-weight="600" fill="{ACCENT}">{html.escape(block.marker)}</text>'
            )
        x = block.x
        for run in line.runs:
            rendered, x = _render_run(run, block, x, baseline)
            parts.append(rendered)
        baseline += block.line_height
    return "".join(parts)


def render_svg(page: Page, page_count: int) -> str:
    """把单页布局渲染成没有外部资源的 SVG。"""

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" xml:space="preserve" width="{PAGE_WIDTH}" '
        f'height="{PAGE_HEIGHT}" viewBox="0 0 {PAGE_WIDTH} {PAGE_HEIGHT}">',
        f'<rect width="{PAGE_WIDTH}" height="{PAGE_HEIGHT}" fill="{BACKGROUND}"/>',
        f'<rect x="{PAGE_MARGIN}" y="48" width="72" height="8" rx="4" fill="{ACCENT}"/>',
    ]
    parts.extend(_render_fragment(fragment) for fragment in page.fragments)
    if page_count > 1:
        parts.append(
            f'<text x="{PAGE_WIDTH / 2:.1f}" y="1385" text-anchor="middle" '
            f'font-family="{SANS_FONT}" font-size="24" fill="{MUTED}">'
            f'{page.number} / {page_count}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def render_svgs(text: str) -> tuple[str, ...]:
    pages = layout_markdown(text)
    return tuple(render_svg(page, len(pages)) for page in pages)


def render_long_svg(text: str) -> tuple[str, int]:
    """把 Markdown 渲染为单张定宽、按内容增高的 SVG。"""

    image = layout_long_image(text)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" xml:space="preserve" width="{PAGE_WIDTH}" '
        f'height="{image.height}" viewBox="0 0 {PAGE_WIDTH} {image.height}">',
        f'<rect width="{PAGE_WIDTH}" height="{image.height}" fill="{BACKGROUND}"/>',
        f'<rect x="{PAGE_MARGIN}" y="48" width="72" height="8" rx="4" fill="{ACCENT}"/>',
    ]
    parts.extend(_render_fragment(fragment) for fragment in image.fragments)
    parts.append("</svg>")
    return "".join(parts), image.height


__all__ = [
    "BACKGROUND",
    "Block",
    "CONTENT_BOTTOM",
    "CONTENT_TOP",
    "Fragment",
    "Inline",
    "LONG_IMAGE_MAX_HEIGHT",
    "LongImage",
    "MarkdownLayoutError",
    "PAGE_HEIGHT",
    "PAGE_WIDTH",
    "Page",
    "RenderBlock",
    "TextLine",
    "TextRun",
    "build_render_blocks",
    "layout_markdown",
    "layout_long_image",
    "paginate",
    "parse_inlines",
    "parse_markdown",
    "render_svg",
    "render_svgs",
    "render_long_svg",
    "wrap_inlines",
]
