"""Markdown、frontmatter 与本地引用的通用校验。"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import codes
from .models import Issue, ValidationResult


MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*([^\s)]+)(?:\s+[^)]*)?\)")


def relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def read_text(path: Path, root: Path) -> tuple[str | None, ValidationResult]:
    """读取 UTF-8 文本并把读取失败转换为结果。"""

    try:
        return path.read_text(encoding="utf-8"), ValidationResult()
    except (OSError, UnicodeDecodeError) as exc:
        return None, ValidationResult(
            errors=(
                Issue(
                    codes.SKILL_TEXT_UNREADABLE,
                    relative_path(path, root),
                    f"无法读取 UTF-8 文本：{exc}",
                ),
            )
        )


def parse_frontmatter(text: str) -> tuple[dict[str, str], str | None]:
    """解析当前仓库支持的扁平 ``key: scalar`` YAML 子集。"""

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, "文件开头缺少 YAML frontmatter"
    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if closing_index is None:
        return {}, "YAML frontmatter 缺少结束分隔符 ---"

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(lines[1:closing_index], start=2):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in raw_line:
            return {}, f"YAML frontmatter 第 {line_number} 行不是受支持的 key: value 格式"
        key, raw_value = raw_line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if not key:
            return {}, f"YAML frontmatter 第 {line_number} 行的字段名为空"
        if key in values:
            return {}, f"YAML frontmatter 字段 {key} 重复"
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values, None


def validate_frontmatter(skill_file: Path, skill_name: str, text: str, root: Path) -> ValidationResult:
    """校验入口文件的必填 frontmatter 字段。"""

    display_path = relative_path(skill_file, root)
    values, parse_error = parse_frontmatter(text)
    if parse_error:
        code = codes.FRONTMATTER_MISSING if "缺少 YAML" in parse_error else codes.FRONTMATTER_INVALID
        return ValidationResult(errors=(Issue(code, display_path, parse_error),))

    errors: list[Issue] = []
    for field_name in ("name", "description"):
        if not values.get(field_name, "").strip():
            errors.append(
                Issue(
                    codes.FRONTMATTER_MISSING_FIELD,
                    display_path,
                    f"YAML frontmatter 缺少非空字段 {field_name}",
                )
            )
    declared_name = values.get("name", "").strip()
    if declared_name and declared_name != skill_name:
        errors.append(
            Issue(
                codes.FRONTMATTER_NAME_MISMATCH,
                display_path,
                f"YAML frontmatter 的 name 为 {declared_name}，与目录名 {skill_name} 不一致",
            )
        )
    return ValidationResult(errors=tuple(errors))


def link_target_to_path(target: str, source_file: Path) -> Path | None:
    """把 Markdown 目标转换为本地路径；远程链接和锚点返回 ``None``。"""

    cleaned = target.strip().strip("<>")
    if cleaned.lower().startswith(("http://", "https://", "mailto:")) or cleaned.startswith("#"):
        return None
    parsed = urlsplit(cleaned)
    if parsed.scheme or parsed.netloc:
        return Path(cleaned)
    return source_file.parent / unquote(parsed.path)


def validate_markdown_links(
    markdown_file: Path,
    text: str,
    skill_dir: Path,
    root: Path,
) -> ValidationResult:
    """校验显式 Markdown 本地链接的存在性和 Skill 边界。"""

    display_path = relative_path(markdown_file, root)
    resolved_skill_dir = skill_dir.resolve()
    errors: list[Issue] = []
    for match in MARKDOWN_LINK_RE.finditer(text):
        target = match.group(1)
        local_path = link_target_to_path(target, markdown_file)
        if local_path is None:
            continue
        cleaned = target.strip().strip("<>")
        if Path(cleaned).is_absolute() or urlsplit(cleaned).scheme:
            errors.append(
                Issue(
                    codes.MARKDOWN_REFERENCE_ABSOLUTE,
                    display_path,
                    f"本地引用不得使用绝对路径或非受支持 URI：{target}",
                )
            )
            continue
        resolved_target = local_path.resolve()
        try:
            resolved_target.relative_to(resolved_skill_dir)
        except ValueError:
            errors.append(
                Issue(
                    codes.MARKDOWN_REFERENCE_ESCAPE,
                    display_path,
                    f"本地引用逃逸 Skill 目录：{target}",
                )
            )
            continue
        if not resolved_target.exists():
            errors.append(
                Issue(
                    codes.MARKDOWN_REFERENCE_MISSING,
                    display_path,
                    f"本地引用不存在：{target}",
                )
            )
    return ValidationResult(errors=tuple(errors))
