#!/usr/bin/env python3
"""公众号文章受限 Markdown 的确定性解析与结构分析。"""

from __future__ import annotations

import re
from dataclasses import dataclass


IMAGE_PATH_RE = re.compile(r"images/body-(\d{2})\.png\Z")
HEADING_RE = re.compile(r"^(#{1,})[ \t]+(.+?)[ \t]*$")
IMAGE_RE = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)[ \t]*$")
ORDERED_RE = re.compile(r"^(\s*)(\d+)[.)][ \t]+(.+)$")
UNORDERED_RE = re.compile(r"^(\s*)[-+*][ \t]+(.+)$")
TABLE_DELIMITER_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)
HTML_RE = re.compile(r"<!--|<!DOCTYPE\b|</?[A-Za-z][^>]*>", re.IGNORECASE)
HORIZONTAL_RE = re.compile(r"^[ \t]{0,3}((?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$")


@dataclass(frozen=True)
class ValidationIssue:
    """稳定的 Markdown 诊断。"""

    code: str
    message: str
    line: int | None = None


class MarkdownValidationError(ValueError):
    """Markdown 语法或结构不符合受限子集。"""

    def __init__(self, issues: list[ValidationIssue] | tuple[ValidationIssue, ...]):
        self.issues = tuple(issues)
        message = "; ".join(issue.message for issue in self.issues)
        super().__init__(message)


@dataclass(frozen=True)
class InlineNode:
    kind: str
    text: str


@dataclass
class Block:
    kind: str
    line: int
    inlines: tuple[InlineNode, ...] = ()
    items: tuple[tuple[InlineNode, ...], ...] = ()
    image_alt: str | None = None
    image_path: str | None = None


@dataclass(frozen=True)
class Document:
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class ImagePlacement:
    file: str
    index: int
    purpose: str
    section: str
    insert_after_paragraph: int
    line: int


@dataclass(frozen=True)
class StructureAnalysis:
    document: Document
    title: str
    body_character_count: int


def _issue(message: str, line: int | None = None) -> MarkdownValidationError:
    return MarkdownValidationError([ValidationIssue("MARKDOWN_INVALID", message, line)])


def parse_inlines(text: str, line: int) -> tuple[InlineNode, ...]:
    """解析单行加粗；加粗不得跨行、嵌套、为空或未闭合。"""

    if "`" in text:
        raise _issue(f"第 {line} 行不支持行内代码", line)
    if HTML_RE.search(text):
        raise _issue(f"第 {line} 行不支持内嵌 HTML", line)
    nodes: list[InlineNode] = []
    position = 0
    while position < len(text):
        marker = text.find("**", position)
        if marker < 0:
            if position < len(text):
                nodes.append(InlineNode("text", text[position:]))
            break
        if marker > position:
            nodes.append(InlineNode("text", text[position:marker]))
        end = text.find("**", marker + 2)
        if end < 0:
            raise _issue(f"第 {line} 行的加粗标记未闭合", line)
        content = text[marker + 2 : end]
        if not content.strip():
            raise _issue(f"第 {line} 行的加粗内容不能为空", line)
        if content != content.strip():
            raise _issue(f"第 {line} 行的加粗边界不能包含空白或嵌套标记", line)
        nodes.append(InlineNode("strong", content))
        position = end + 2
    return tuple(nodes)


def _join_inline_lines(lines: list[tuple[str, int]]) -> tuple[InlineNode, ...]:
    nodes: list[InlineNode] = []
    for index, (text, line_number) in enumerate(lines):
        if index:
            nodes.append(InlineNode("text", " "))
        nodes.extend(parse_inlines(text, line_number))
    return tuple(nodes)


def _plain_text(inlines: tuple[InlineNode, ...]) -> str:
    return "".join(node.text for node in inlines)


def _detect_table(lines: list[str], index: int) -> bool:
    if TABLE_DELIMITER_RE.match(lines[index]):
        return True
    return (
        "|" in lines[index]
        and index + 1 < len(lines)
        and TABLE_DELIMITER_RE.match(lines[index + 1]) is not None
    )


def parse_article(text: str) -> Document:
    """解析受限 Markdown；不访问文件系统。"""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if normalized.startswith("\ufeff"):
        normalized = normalized[1:]
    if "\x00" in normalized:
        raise _issue("Markdown 包含 NUL 字符")
    lines = normalized.split("\n")
    blocks: list[Block] = []
    paragraph_lines: list[tuple[str, int]] = []

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        blocks.append(
            Block(
                kind="paragraph",
                line=paragraph_lines[0][1],
                inlines=_join_inline_lines(paragraph_lines),
            )
        )
        paragraph_lines.clear()

    index = 0
    while index < len(lines):
        raw = lines[index]
        line_number = index + 1
        if not raw.strip():
            flush_paragraph()
            index += 1
            continue
        if raw.startswith("\t") or raw.startswith("    "):
            raise _issue(f"第 {line_number} 行不支持缩进代码块或嵌套结构", line_number)
        if raw.lstrip().startswith(("```", "~~~")):
            raise _issue(f"第 {line_number} 行不支持代码块", line_number)
        if _detect_table(lines, index):
            raise _issue(f"第 {line_number} 行不支持表格", line_number)

        heading = HEADING_RE.match(raw)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            if level > 2:
                raise _issue(f"第 {line_number} 行不支持三级或更深标题", line_number)
            inlines = parse_inlines(heading.group(2), line_number)
            if not _plain_text(inlines).strip():
                raise _issue(f"第 {line_number} 行标题不能为空", line_number)
            blocks.append(Block(f"h{level}", line_number, inlines=inlines))
            index += 1
            continue

        image = IMAGE_RE.match(raw)
        if image:
            flush_paragraph()
            blocks.append(
                Block(
                    "image",
                    line_number,
                    image_alt=image.group(1),
                    image_path=image.group(2),
                )
            )
            index += 1
            continue
        if raw.lstrip().startswith("!["):
            raise _issue(f"第 {line_number} 行图片语法不受支持", line_number)

        if raw.startswith("图注："):
            flush_paragraph()
            if not blocks or blocks[-1].kind != "image":
                raise _issue(f"第 {line_number} 行图注必须紧跟图片", line_number)
            caption = raw.removeprefix("图注：")
            if not caption.strip():
                raise _issue(f"第 {line_number} 行图注不能为空", line_number)
            blocks.append(Block("caption", line_number, inlines=parse_inlines(caption, line_number)))
            index += 1
            continue

        if HORIZONTAL_RE.match(raw):
            flush_paragraph()
            blocks.append(Block("hr", line_number))
            index += 1
            continue

        ordered = ORDERED_RE.match(raw)
        unordered = UNORDERED_RE.match(raw)
        if ordered or unordered:
            flush_paragraph()
            match = ordered or unordered
            assert match is not None
            if match.group(1):
                raise _issue(f"第 {line_number} 行不支持嵌套列表", line_number)
            kind = "ol" if ordered else "ul"
            items: list[tuple[InlineNode, ...]] = []
            while index < len(lines):
                current = ORDERED_RE.match(lines[index]) if kind == "ol" else UNORDERED_RE.match(lines[index])
                if current is None:
                    break
                current_line = index + 1
                if current.group(1):
                    raise _issue(f"第 {current_line} 行不支持嵌套列表", current_line)
                item_text = current.group(3) if kind == "ol" else current.group(2)
                if not item_text.strip():
                    raise _issue(f"第 {current_line} 行列表项不能为空", current_line)
                items.append(parse_inlines(item_text, current_line))
                index += 1
            blocks.append(Block(kind, line_number, items=tuple(items)))
            continue

        if raw.startswith(">"):
            flush_paragraph()
            quote_lines: list[tuple[str, int]] = []
            while index < len(lines) and lines[index].startswith(">"):
                current = lines[index]
                current_line = index + 1
                if current.startswith(">>") or current.startswith("> >"):
                    raise _issue(f"第 {current_line} 行不支持嵌套引用", current_line)
                content = current[1:]
                if content.startswith(" "):
                    content = content[1:]
                if not content.strip():
                    raise _issue(f"第 {current_line} 行引用不能为空", current_line)
                quote_lines.append((content, current_line))
                index += 1
            blocks.append(Block("quote", line_number, inlines=_join_inline_lines(quote_lines)))
            continue

        if HTML_RE.search(raw):
            raise _issue(f"第 {line_number} 行不支持内嵌 HTML", line_number)
        paragraph_lines.append((raw, line_number))
        index += 1

    flush_paragraph()
    if not blocks:
        raise _issue("Markdown 没有有效内容")
    return Document(tuple(blocks))


def body_character_count(document: Document) -> int:
    """计算排除标题、图片、图注、控制符和空白后的 Unicode 字符数。"""

    pieces: list[str] = []
    for block in document.blocks:
        if block.kind in {"paragraph", "quote"}:
            pieces.append(_plain_text(block.inlines))
        elif block.kind in {"ol", "ul"}:
            pieces.extend(_plain_text(item) for item in block.items)
    return sum(1 for character in "".join(pieces) if not character.isspace())


def validate_structure(document: Document) -> StructureAnalysis:
    """校验文章源稿结构；正文插图由独立计划管理。"""

    issues: list[ValidationIssue] = []
    h1_blocks = [block for block in document.blocks if block.kind == "h1"]
    if len(h1_blocks) != 1:
        issues.append(ValidationIssue("MARKDOWN_INVALID", "文章必须且只能包含一个一级主标题"))
    elif document.blocks[0].kind != "h1":
        issues.append(ValidationIssue("MARKDOWN_INVALID", "一级主标题必须是第一个有效块", h1_blocks[0].line))
    if not any(block.kind == "h2" for block in document.blocks):
        issues.append(ValidationIssue("MARKDOWN_INVALID", "正文至少需要一个二级标题"))

    count = body_character_count(document)
    image_blocks = [block for block in document.blocks if block.kind == "image"]
    if image_blocks:
        issues.append(
            ValidationIssue(
                "IMAGE_REFERENCE_INVALID",
                "article.md 不得包含正文图片引用；请使用 illustration-plan.json 管理正文配图",
                image_blocks[0].line,
            )
        )

    if issues:
        raise MarkdownValidationError(issues)
    title = _plain_text(h1_blocks[0].inlines).strip()
    return StructureAnalysis(document, title, count)


def parse_and_validate(text: str) -> StructureAnalysis:
    return validate_structure(parse_article(text))
