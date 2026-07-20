#!/usr/bin/env python3
"""校验仓库内全部 Agent Skill 的结构、引用和静态数据。"""

from __future__ import annotations

import argparse
import ast
import csv
import fnmatch
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import unquote, urlsplit


WATCHLIST_HEADER = (
    "entity_id",
    "entity_name",
    "entity_type",
    "category",
    "region",
    "primary_focus",
    "official_url",
    "source_priority",
    "tracking_priority",
    "status",
    "last_reviewed",
    "notes",
)
ENTITY_TYPES = frozenset({"company", "product", "project", "protocol", "framework", "platform"})
SOURCE_PRIORITIES = frozenset({"primary", "secondary"})
TRACKING_PRIORITIES = frozenset({"high", "medium", "low"})
STATUSES = frozenset({"active", "watch", "paused", "removed"})
CATEGORIES = frozenset(
    {
        "基础模型与平台",
        "通用 Agent 产品",
        "编程与软件工程 Agent",
        "浏览器与计算机操作 Agent",
        "企业工作流 Agent",
        "垂直行业 Agent",
        "Agent 开发框架",
        "工具协议和连接器生态",
        "记忆、上下文、评估、安全和可观测性",
        "开源新项目",
        "商业化与企业应用案例",
    }
)

OPTIONAL_SKILL_DIRECTORIES = ("references", "examples", "assets", "scripts")
REQUIRED_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("目标", ("目标",)),
    ("适用场景", ("适用场景",)),
    ("不适用场景", ("不适用场景",)),
    ("输入与默认值", ("输入与默认值",)),
    ("参考文件", ("参考文件",)),
    ("执行工作流", ("执行工作流",)),
    ("输出要求", ("输出要求",)),
    ("工作规范", ("工作规范",)),
    ("质量检查", ("质量检查",)),
)

MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*([^\s)]+)(?:\s+[^)]*)?\)")
HEADING_RE = re.compile(r"^##\s+(.+?)\s*#*\s*$", re.MULTILINE)
IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".idea",
        ".vscode",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
        "node_modules",
    }
)
SENSITIVE_SCAN_IGNORED_DIRECTORIES = IGNORED_DIRECTORY_NAMES | frozenset({"__pycache__"})
TEXT_SUFFIXES = frozenset(
    {
        ".cfg",
        ".conf",
        ".csv",
        ".env",
        ".ini",
        ".json",
        ".jsonl",
        ".md",
        ".py",
        ".sh",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
    }
)
TEXT_FILENAMES = frozenset({"AGENTS.md", "README.md", ".gitignore"})
PLACEHOLDER_MARKERS = ("EXAMPLE", "FAKE", "DUMMY", "REDACTED", "PLACEHOLDER")


@dataclass(frozen=True, slots=True)
class Issue:
    """一条可定位的错误或警告。"""

    path: str
    message: str
    line: int | None = None
    snippet: str | None = None

    def render(self) -> str:
        location = f"{self.path}:{self.line}" if self.line is not None else self.path
        suffix = f"；片段：{self.snippet}" if self.snippet else ""
        return f"{location}：{self.message}{suffix}"


@dataclass(slots=True)
class ValidationReport:
    """仓库级校验汇总。"""

    skill_count: int = 0
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def error(
        self,
        path: str,
        message: str,
        *,
        line: int | None = None,
        snippet: str | None = None,
    ) -> None:
        self.errors.append(Issue(path, message, line, snippet))

    def warning(
        self,
        path: str,
        message: str,
        *,
        line: int | None = None,
        snippet: str | None = None,
    ) -> None:
        self.warnings.append(Issue(path, message, line, snippet))


@dataclass(frozen=True, slots=True)
class IgnoreRule:
    """当前校验器需要的最小 .gitignore 规则表示。"""

    pattern: str
    negated: bool
    directory_only: bool
    anchored: bool


def relative_path(path: Path, root: Path) -> str:
    """返回适合终端展示的仓库相对路径。"""

    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def is_strict_iso_date(value: str) -> bool:
    """判断字符串是否为有效且规范的 YYYY-MM-DD。"""

    if len(value) != 10:
        return False
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return False
    return parsed.isoformat() == value


def load_gitignore_rules(root: Path) -> list[IgnoreRule]:
    """读取常见的 .gitignore glob 规则。

    这里不是完整 Git ignore 解析器，只处理本工具判断生成物所需的普通 glob、
    根路径锚定、目录后缀和 ``!`` 否定规则。
    """

    gitignore = root / ".gitignore"
    try:
        lines = gitignore.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []

    rules: list[IgnoreRule] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        if negated:
            line = line[1:]
        if not line:
            continue
        anchored = line.startswith("/")
        if anchored:
            line = line[1:]
        directory_only = line.endswith("/")
        if directory_only:
            line = line[:-1]
        if line:
            rules.append(IgnoreRule(line, negated, directory_only, anchored))
    return rules


def gitignore_rule_matches(rule: IgnoreRule, relative_path: Path, *, is_directory: bool) -> bool:
    """判断一个最小 ignore 规则是否匹配仓库相对路径。"""

    if rule.directory_only and not is_directory:
        return False
    path_text = relative_path.as_posix()
    if rule.anchored:
        return fnmatch.fnmatchcase(path_text, rule.pattern)
    if "/" in rule.pattern:
        return fnmatch.fnmatchcase(path_text, rule.pattern)
    return any(fnmatch.fnmatchcase(part, rule.pattern) for part in relative_path.parts)


def is_gitignored_generated_path(path: Path, root: Path, rules: Sequence[IgnoreRule]) -> bool:
    """判断已存在的生成物是否被仓库根 .gitignore 明确排除。"""

    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    ignored = False
    for rule in rules:
        if gitignore_rule_matches(rule, relative, is_directory=path.is_dir()):
            ignored = not rule.negated
    return ignored


def read_text(path: Path, root: Path, report: ValidationReport) -> str | None:
    """读取 UTF-8 文本并将读取失败记录为错误。"""

    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        report.error(relative_path(path, root), f"无法读取 UTF-8 文本：{exc}")
        return None


def parse_frontmatter(text: str) -> tuple[dict[str, str], str | None]:
    """解析当前仓库使用的扁平 YAML frontmatter。

    仅支持由 ``key: scalar value`` 组成的顶层字符串字段；不实现嵌套对象、
    列表、折叠块或其他完整 YAML 语法，从而避免引入第三方解析器。
    """

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, "文件开头缺少 YAML frontmatter"

    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
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


def validate_frontmatter_and_sections(
    skill_file: Path,
    skill_name: str,
    text: str,
    root: Path,
    report: ValidationReport,
) -> None:
    """校验 SKILL.md 的 frontmatter 与语义章节。"""

    display_path = relative_path(skill_file, root)
    frontmatter, parse_error = parse_frontmatter(text)
    if parse_error:
        report.error(display_path, parse_error)
    else:
        for field_name in ("name", "description"):
            if not frontmatter.get(field_name, "").strip():
                report.error(display_path, f"YAML frontmatter 缺少非空字段 {field_name}")
        declared_name = frontmatter.get("name", "").strip()
        if declared_name and declared_name != skill_name:
            report.error(
                display_path,
                f"YAML frontmatter 的 name 为 {declared_name}，与目录名 {skill_name} 不一致",
            )

    headings = [heading.strip() for heading in HEADING_RE.findall(text)]
    for label, keywords in REQUIRED_SECTIONS:
        if not any(all(keyword in heading for keyword in keywords) for heading in headings):
            report.error(display_path, f"缺少必需语义章节：{label}")


def link_target_to_path(target: str, source_file: Path) -> Path | None:
    """把 Markdown 链接目标转换为本地路径；远程链接和锚点返回 None。"""

    cleaned = target.strip().strip("<>")
    lower = cleaned.lower()
    if lower.startswith(("http://", "https://", "mailto:")) or cleaned.startswith("#"):
        return None

    parsed = urlsplit(cleaned)
    if parsed.scheme or parsed.netloc:
        return Path(cleaned)
    decoded_path = unquote(parsed.path)
    return source_file.parent / decoded_path


def validate_markdown_links(
    markdown_file: Path,
    text: str,
    skill_dir: Path,
    root: Path,
    report: ValidationReport,
) -> None:
    """校验 Markdown 显式链接中的本地路径边界和存在性。"""

    display_path = relative_path(markdown_file, root)
    resolved_skill_dir = skill_dir.resolve()
    for match in MARKDOWN_LINK_RE.finditer(text):
        target = match.group(1)
        local_path = link_target_to_path(target, markdown_file)
        if local_path is None:
            continue
        if Path(target.strip().strip("<>")).is_absolute() or urlsplit(target).scheme:
            report.error(display_path, f"本地引用不得使用绝对路径或非受支持 URI：{target}")
            continue
        resolved_target = local_path.resolve()
        try:
            resolved_target.relative_to(resolved_skill_dir)
        except ValueError:
            report.error(display_path, f"本地引用逃逸 Skill 目录：{target}")
            continue
        if not resolved_target.exists():
            report.error(display_path, f"本地引用不存在：{target}")


def validate_watchlist(
    watchlist_path: Path,
    root: Path,
    report: ValidationReport,
) -> None:
    """校验结构化观察池的表头、字段、枚举和唯一性。"""

    display_path = relative_path(watchlist_path, root)
    try:
        with watchlist_path.open("r", encoding="utf-8", newline="") as file:
            rows = list(csv.reader(file, strict=True))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        report.error(display_path, f"CSV 无法解析：{exc}")
        return

    if not rows:
        report.error(display_path, "CSV 不得为空")
        return
    header = tuple(rows[0])
    if header != WATCHLIST_HEADER:
        report.error(display_path, "CSV 表头与规定字段或顺序不一致", line=1)
        return

    seen_ids: set[str] = set()
    seen_entities: set[tuple[str, str]] = set()
    for line_number, row in enumerate(rows[1:], start=2):
        if len(row) != len(WATCHLIST_HEADER):
            report.error(
                display_path,
                f"该行有 {len(row)} 列，应为 {len(WATCHLIST_HEADER)} 列",
                line=line_number,
            )
            continue
        record = dict(zip(WATCHLIST_HEADER, (value.strip() for value in row), strict=True))
        entity_id = record["entity_id"]
        entity_name = record["entity_name"]
        entity_type = record["entity_type"]

        if not entity_id:
            report.error(display_path, "entity_id 不得为空", line=line_number)
        elif entity_id in seen_ids:
            report.error(display_path, f"entity_id 重复：{entity_id}", line=line_number)
        else:
            seen_ids.add(entity_id)
        if not entity_name:
            report.error(display_path, "entity_name 不得为空", line=line_number)
        if not record["category"]:
            report.error(display_path, "category 不得为空", line=line_number)
        elif record["category"] not in CATEGORIES:
            report.error(
                display_path,
                f"category 不在观察池分类框架中：{record['category']}",
                line=line_number,
            )

        if entity_type not in ENTITY_TYPES:
            report.error(display_path, f"entity_type 枚举值无效：{entity_type}", line=line_number)
        if record["source_priority"] not in SOURCE_PRIORITIES:
            report.error(
                display_path,
                f"source_priority 枚举值无效：{record['source_priority']}",
                line=line_number,
            )
        if record["tracking_priority"] not in TRACKING_PRIORITIES:
            report.error(
                display_path,
                f"tracking_priority 枚举值无效：{record['tracking_priority']}",
                line=line_number,
            )
        if record["status"] not in STATUSES:
            report.error(display_path, f"status 枚举值无效：{record['status']}", line=line_number)

        official_url = record["official_url"]
        if official_url and not official_url.startswith(("http://", "https://")):
            report.error(
                display_path,
                "official_url 非空时必须以 http:// 或 https:// 开头",
                line=line_number,
            )
        last_reviewed = record["last_reviewed"]
        if last_reviewed and not is_strict_iso_date(last_reviewed):
            report.error(display_path, "last_reviewed 必须是有效的 YYYY-MM-DD", line=line_number)

        entity_key = (entity_name.casefold(), entity_type)
        if entity_name and entity_type and entity_key in seen_entities:
            report.error(
                display_path,
                "entity_name 与 entity_type 的组合完全重复",
                line=line_number,
            )
        elif entity_name and entity_type:
            seen_entities.add(entity_key)

        if record["status"] == "removed" and not record["notes"]:
            report.warning(display_path, "removed 状态条目的 notes 建议说明移除原因", line=line_number)


def validate_python_scripts(skill_dir: Path, root: Path, report: ValidationReport) -> None:
    """检查脚本语法、相对导入边界和显式第三方 Python 依赖。"""

    scripts_dir = skill_dir / "scripts"
    if not scripts_dir.is_dir():
        return
    standard_library = sys.stdlib_module_names | {"__future__"}
    local_module_names = {path.stem for path in skill_dir.rglob("*.py")}
    local_module_names.update(path.name for path in skill_dir.rglob("*") if path.is_dir())
    resolved_skill_dir = skill_dir.resolve()

    for script_path in sorted(scripts_dir.rglob("*.py")):
        text = read_text(script_path, root, report)
        if text is None:
            continue
        display_path = relative_path(script_path, root)
        try:
            tree = ast.parse(text, filename=display_path)
        except SyntaxError as exc:
            report.error(display_path, f"Python 语法错误：{exc.msg}", line=exc.lineno)
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                module_names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    import_base = script_path.parent
                    for _ in range(node.level - 1):
                        import_base = import_base.parent
                    try:
                        import_base.resolve().relative_to(resolved_skill_dir)
                    except ValueError:
                        report.error(
                            display_path,
                            "Python 相对导入逃逸 Skill 目录",
                            line=node.lineno,
                        )
                    continue
                module_names = [node.module] if node.module else []
            else:
                continue

            for module_name in module_names:
                if module_name is None:
                    continue
                top_level_name = module_name.split(".", 1)[0]
                if top_level_name in standard_library or top_level_name in local_module_names:
                    continue
                report.error(
                    display_path,
                    f"脚本存在非标准库或 Skill 外部 Python 依赖：{module_name}",
                    line=node.lineno,
                )


def validate_skill(skill_dir: Path, root: Path, report: ValidationReport) -> None:
    """校验单个 Skill。"""

    skill_name = skill_dir.name
    display_dir = relative_path(skill_dir, root)
    resolved_skill_dir = skill_dir.resolve()
    for path in skill_dir.rglob("*"):
        if not path.is_symlink():
            continue
        try:
            path.resolve(strict=True).relative_to(resolved_skill_dir)
        except (OSError, ValueError):
            report.error(
                relative_path(path, root),
                "Skill 内的符号链接不得指向 Skill 目录外或不存在的目标",
            )

    skill_files = sorted(skill_dir.rglob("SKILL.md"))
    entry_file = skill_dir / "SKILL.md"
    if not entry_file.is_file():
        report.error(display_dir, "缺少入口文件 SKILL.md")
    if len(skill_files) > 1:
        report.error(display_dir, "一个 Skill 只能包含一个作为入口的 SKILL.md")

    for directory_name in OPTIONAL_SKILL_DIRECTORIES:
        candidate = skill_dir / directory_name
        if candidate.exists() and not candidate.is_dir():
            report.error(relative_path(candidate, root), f"{directory_name} 存在时必须是目录")

    markdown_files = sorted(skill_dir.rglob("*.md"))
    for markdown_file in markdown_files:
        text = read_text(markdown_file, root, report)
        if text is None:
            continue
        if not text.strip():
            report.error(relative_path(markdown_file, root), "Markdown 文件不得为空")
            continue
        validate_markdown_links(markdown_file, text, skill_dir, root, report)
        if markdown_file == entry_file:
            validate_frontmatter_and_sections(
                markdown_file,
                skill_name,
                text,
                root,
                report,
            )

    watchlist_path = skill_dir / "assets" / "watchlist.csv"
    if watchlist_path.is_file():
        validate_watchlist(watchlist_path, root, report)
    validate_python_scripts(skill_dir, root, report)


def walk_repository(root: Path, *, ignored_dirs: frozenset[str]) -> Iterable[Path]:
    """遍历仓库文件，并原地剪枝明确忽略的目录。"""

    for current_root, directory_names, file_names in os.walk(root):
        directory_names[:] = [name for name in directory_names if name not in ignored_dirs]
        current_path = Path(current_root)
        for file_name in file_names:
            path = current_path / file_name
            if not path.is_symlink():
                yield path


def validate_forbidden_paths(root: Path, report: ValidationReport) -> None:
    """发现不应进入仓库的系统、缓存和临时编辑器文件。"""

    ignore_rules = load_gitignore_rules(root)
    for current_root, directory_names, file_names in os.walk(root):
        directory_names[:] = [name for name in directory_names if name not in IGNORED_DIRECTORY_NAMES]
        current_path = Path(current_root)
        if "__pycache__" in directory_names:
            cache_path = current_path / "__pycache__"
            if not is_gitignored_generated_path(cache_path, root, ignore_rules):
                report.error(
                    relative_path(cache_path, root),
                    "不允许存在未被 .gitignore 排除的 __pycache__ 目录",
                )
            directory_names.remove("__pycache__")

        for file_name in file_names:
            path = current_path / file_name
            if file_name == ".DS_Store":
                report.error(relative_path(path, root), "不允许存在 .DS_Store")
            elif file_name.endswith(".pyc") and not is_gitignored_generated_path(
                path,
                root,
                ignore_rules,
            ):
                report.error(
                    relative_path(path, root),
                    "不允许存在未被 .gitignore 排除的 .pyc 文件",
                )
            elif (
                file_name.endswith(("~", ".swp", ".swo", ".tmp"))
                or file_name.startswith(".#")
            ):
                report.error(relative_path(path, root), "不允许存在临时编辑器文件")


def is_text_candidate(path: Path) -> bool:
    """用保守的文件名规则筛选需要进行凭据扫描的文本文件。"""

    return path.name in TEXT_FILENAMES or path.suffix.lower() in TEXT_SUFFIXES


def is_placeholder_secret(value: str) -> bool:
    """识别明确标记为占位符的测试或文档值。"""

    upper_value = value.upper()
    return any(marker in upper_value for marker in PLACEHOLDER_MARKERS)


def redact_secret(value: str) -> str:
    """对疑似密钥脱敏，避免校验输出造成二次泄露。"""

    compact = value.strip().strip("\"'")
    if len(compact) <= 6:
        return "[已脱敏]"
    return f"{compact[:4]}…{compact[-2:]}"


SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "私钥头",
        re.compile(r"(?P<secret>-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"),
    ),
    ("sk- 密钥", re.compile(r"\b(?P<secret>sk-[A-Za-z0-9_-]{20,})\b")),
    ("AWS access key", re.compile(r"\b(?P<secret>(?:AKIA|ASIA)[A-Z0-9]{16})\b")),
    (
        "Authorization bearer token",
        re.compile(
            r"Authorization\s*:\s*Bearer\s+(?P<secret>[A-Za-z0-9._~+/=-]{20,})",
            re.IGNORECASE,
        ),
    ),
    (
        "凭据赋值",
        re.compile(
            r"\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|cookie|"
            r"client[_-]?secret|secret[_-]?key|aws_secret_access_key)\b\s*[:=]\s*[\"']?"
            r"(?P<secret>[A-Za-z0-9+/_.=-]{20,})",
            re.IGNORECASE,
        ),
    ),
)


def scan_sensitive_information(root: Path, report: ValidationReport) -> None:
    """扫描高可信凭据模式，并只输出脱敏后的匹配值。"""

    for path in walk_repository(root, ignored_dirs=SENSITIVE_SCAN_IGNORED_DIRECTORIES):
        if not is_text_candidate(path):
            continue
        try:
            if path.stat().st_size > 2_000_000:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern_name, pattern in SENSITIVE_PATTERNS:
                for match in pattern.finditer(line):
                    secret = match.group("secret")
                    if is_placeholder_secret(secret):
                        continue
                    report.error(
                        relative_path(path, root),
                        f"发现高可信疑似敏感信息（{pattern_name}）",
                        line=line_number,
                        snippet=redact_secret(secret),
                    )


def validate_repository(root: Path) -> ValidationReport:
    """校验给定仓库目录并返回可供 CLI 和测试共用的结构化报告。"""

    report = ValidationReport()
    root = root.expanduser().resolve()
    if not root.is_dir():
        report.error(str(root), "仓库目录不存在或不是目录")
        return report

    skills_root = root / ".agents" / "skills"
    if not skills_root.is_dir():
        report.error(".agents/skills", "缺少 Skill 根目录")
    else:
        skill_dirs = sorted(path for path in skills_root.iterdir() if path.is_dir())
        report.skill_count = len(skill_dirs)
        if not skill_dirs:
            report.error(".agents/skills", "未发现任何 Skill 目录")
        for skill_dir in skill_dirs:
            validate_skill(skill_dir, root, report)

    validate_forbidden_paths(root, report)
    scan_sensitive_information(root, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    """创建仓库级校验命令行参数解析器。"""

    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description=(
            "扫描 .agents/skills/*，校验 Skill 结构、SKILL.md、Markdown 本地引用、"
            "watchlist.csv、敏感信息和仓库路径规范。frontmatter 仅支持扁平 key: value 字段。"
        ),
        add_help=False,
    )
    parser._positionals.title = "位置参数"
    parser._optionals.title = "选项"
    parser.add_argument("-h", "--help", action="help", help="显示此帮助信息并退出")
    parser.add_argument(
        "repository",
        nargs="?",
        type=Path,
        default=default_root,
        help="仓库目录；默认使用脚本所在仓库",
    )
    return parser


def print_report(report: ValidationReport) -> None:
    """以中文打印错误、警告和摘要。"""

    if report.errors:
        print("错误：", file=sys.stderr)
        for issue in report.errors:
            print(f"- {issue.render()}", file=sys.stderr)
    if report.warnings:
        print("警告：")
        for issue in report.warnings:
            print(f"- {issue.render()}")

    status = "通过" if report.is_valid else "失败"
    summary = (
        f"校验{status}：已校验 {report.skill_count} 个 Skill，"
        f"发现 {len(report.errors)} 个错误和 {len(report.warnings)} 个警告。"
    )
    print(summary, file=sys.stdout if report.is_valid else sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    """运行仓库级校验并返回进程退出码。"""

    args = build_parser().parse_args(argv)
    report = validate_repository(args.repository)
    print_report(report)
    return 0 if report.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
