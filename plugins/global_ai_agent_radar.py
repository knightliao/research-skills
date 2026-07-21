"""global-ai-agent-radar 的专属静态校验。"""

from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path

from skill_framework.markdown import relative_path
from skill_framework.models import Issue, SkillContext, ValidationResult


PLUGIN_API_VERSION = 1
SKILL_NAME = "global-ai-agent-radar"

WATCHLIST_HEADER = (
    "entity_id", "entity_name", "entity_type", "category", "region", "primary_focus",
    "official_url", "source_priority", "tracking_priority", "status", "last_reviewed", "notes",
)
ENTITY_TYPES = frozenset({"company", "product", "project", "protocol", "framework", "platform"})
SOURCE_PRIORITIES = frozenset({"primary", "secondary"})
TRACKING_PRIORITIES = frozenset({"high", "medium", "low"})
STATUSES = frozenset({"active", "watch", "paused", "removed"})
CATEGORIES = frozenset(
    {
        "基础模型与平台", "通用 Agent 产品", "编程与软件工程 Agent", "浏览器与计算机操作 Agent",
        "企业工作流 Agent", "垂直行业 Agent", "Agent 开发框架", "工具协议和连接器生态",
        "记忆、上下文、评估、安全和可观测性", "开源新项目", "商业化与企业应用案例",
    }
)
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
HEADING_RE = re.compile(r"^##\s+(.+?)\s*#*\s*$", re.MULTILINE)

RADAR_INVALID_SECTION = "radar.skill.missing_section"
RADAR_WATCHLIST_PARSE_FAILED = "radar.watchlist.parse_failed"
RADAR_WATCHLIST_INVALID_HEADER = "radar.watchlist.invalid_header"
RADAR_WATCHLIST_INVALID_ROW = "radar.watchlist.invalid_row"
RADAR_WATCHLIST_DUPLICATE_ID = "radar.watchlist.duplicate_id"
RADAR_WATCHLIST_DUPLICATE_ENTITY = "radar.watchlist.duplicate_entity"
RADAR_WATCHLIST_INVALID_FIELD = "radar.watchlist.invalid_field"
RADAR_WATCHLIST_REMOVED_WITHOUT_NOTES = "radar.watchlist.removed_without_notes"
RADAR_WORKFLOW_ROUTE_MISSING = "radar.workflow.route_missing"
RADAR_WORKFLOW_SEMANTIC_MISSING = "radar.workflow.semantic_missing"

RESOURCE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "references/source-policy.md": ("搜索、核验和引用候选事件前",),
    "references/scoring-rubric.md": ("评分和决定是否收录前",),
    "references/deduplication-policy.md": ("处理重复报道",),
    "references/company-watchlist.md": ("维护观察池时",),
    "references/event-schema.md": ("准备临时 JSON 前",),
    "assets/watchlist.csv": ("研究模式只读", "维护模式", "开放发现"),
    "assets/report-template.md": ("模式 A", "无重点事件模式", "空结果状态"),
    "examples/good-report.md": ("模式 A", "写作前读取"),
    "examples/no-major-change-report.md": ("无重点事件模式", "写作前读取"),
    "examples/bad-report.md": ("质量校准", "不复制错误正文"),
    "scripts/validate_events.py": ("最终准备写入报告", "不校验所有搜索候选", "空数组"),
}


def _strict_iso_date(value: str) -> bool:
    if len(value) != 10:
        return False
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return False
    return parsed.isoformat() == value


def validate_watchlist(path: Path, root: Path) -> ValidationResult:
    """校验 radar 观察池的专属字段、枚举与唯一性。"""

    display_path = relative_path(path, root)
    try:
        with path.open("r", encoding="utf-8", newline="") as file:
            rows = list(csv.reader(file, strict=True))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        return ValidationResult(
            errors=(Issue(RADAR_WATCHLIST_PARSE_FAILED, display_path, f"CSV 无法解析：{exc}"),)
        )
    if not rows:
        return ValidationResult(
            errors=(Issue(RADAR_WATCHLIST_PARSE_FAILED, display_path, "CSV 不得为空"),)
        )
    if tuple(rows[0]) != WATCHLIST_HEADER:
        return ValidationResult(
            errors=(
                Issue(RADAR_WATCHLIST_INVALID_HEADER, display_path, "CSV 表头与规定字段或顺序不一致", 1),
            )
        )

    errors: list[Issue] = []
    warnings: list[Issue] = []
    seen_ids: set[str] = set()
    seen_entities: set[tuple[str, str]] = set()
    for line_number, row in enumerate(rows[1:], start=2):
        if len(row) != len(WATCHLIST_HEADER):
            errors.append(
                Issue(
                    RADAR_WATCHLIST_INVALID_ROW,
                    display_path,
                    f"该行有 {len(row)} 列，应为 {len(WATCHLIST_HEADER)} 列",
                    line_number,
                )
            )
            continue
        record = dict(zip(WATCHLIST_HEADER, (value.strip() for value in row), strict=True))
        entity_id = record["entity_id"]
        entity_name = record["entity_name"]
        entity_type = record["entity_type"]

        if not entity_id:
            errors.append(Issue(RADAR_WATCHLIST_INVALID_FIELD, display_path, "entity_id 不得为空", line_number))
        elif entity_id in seen_ids:
            errors.append(
                Issue(RADAR_WATCHLIST_DUPLICATE_ID, display_path, f"entity_id 重复：{entity_id}", line_number)
            )
        else:
            seen_ids.add(entity_id)
        if not entity_name:
            errors.append(Issue(RADAR_WATCHLIST_INVALID_FIELD, display_path, "entity_name 不得为空", line_number))
        category = record["category"]
        if not category:
            errors.append(Issue(RADAR_WATCHLIST_INVALID_FIELD, display_path, "category 不得为空", line_number))
        elif category not in CATEGORIES:
            errors.append(
                Issue(RADAR_WATCHLIST_INVALID_FIELD, display_path, f"category 不在观察池分类框架中：{category}", line_number)
            )
        enum_checks = (
            ("entity_type", ENTITY_TYPES),
            ("source_priority", SOURCE_PRIORITIES),
            ("tracking_priority", TRACKING_PRIORITIES),
            ("status", STATUSES),
        )
        for field_name, allowed in enum_checks:
            if record[field_name] not in allowed:
                errors.append(
                    Issue(
                        RADAR_WATCHLIST_INVALID_FIELD,
                        display_path,
                        f"{field_name} 枚举值无效：{record[field_name]}",
                        line_number,
                    )
                )
        official_url = record["official_url"]
        if official_url and not official_url.startswith(("http://", "https://")):
            errors.append(
                Issue(
                    RADAR_WATCHLIST_INVALID_FIELD,
                    display_path,
                    "official_url 非空时必须以 http:// 或 https:// 开头",
                    line_number,
                )
            )
        reviewed = record["last_reviewed"]
        if reviewed and not _strict_iso_date(reviewed):
            errors.append(
                Issue(RADAR_WATCHLIST_INVALID_FIELD, display_path, "last_reviewed 必须是有效的 YYYY-MM-DD", line_number)
            )
        entity_key = (entity_name.casefold(), entity_type)
        if entity_name and entity_type and entity_key in seen_entities:
            errors.append(
                Issue(RADAR_WATCHLIST_DUPLICATE_ENTITY, display_path, "entity_name 与 entity_type 的组合完全重复", line_number)
            )
        elif entity_name and entity_type:
            seen_entities.add(entity_key)
        if record["status"] == "removed" and not record["notes"]:
            warnings.append(
                Issue(
                    RADAR_WATCHLIST_REMOVED_WITHOUT_NOTES,
                    display_path,
                    "removed 状态条目的 notes 建议说明移除原因",
                    line_number,
                )
            )
    return ValidationResult(tuple(errors), tuple(warnings))


def validate_skill_semantics(context: SkillContext) -> ValidationResult:
    """校验 radar 主工作流的章节、资源路由和关键模式语义。"""

    skill_path = context.skill_dir / "SKILL.md"
    try:
        text = skill_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ValidationResult()
    display_path = relative_path(skill_path, context.repository_root)
    headings = [heading.strip() for heading in HEADING_RE.findall(text)]
    errors: list[Issue] = []
    for label, keywords in REQUIRED_SECTIONS:
        if not any(all(keyword in heading for keyword in keywords) for heading in headings):
            errors.append(
                Issue(RADAR_INVALID_SECTION, display_path, f"缺少必需语义章节：{label}")
            )
    for resource_path, fragments in RESOURCE_REQUIREMENTS.items():
        if f"]({resource_path})" not in text:
            errors.append(
                Issue(RADAR_WORKFLOW_ROUTE_MISSING, display_path, f"缺少资源路由：{resource_path}")
            )
            continue
        for fragment in fragments:
            if fragment not in text:
                errors.append(
                    Issue(
                        RADAR_WORKFLOW_SEMANTIC_MISSING,
                        display_path,
                        f"资源 {resource_path} 缺少路由语义：{fragment}",
                    )
                )
    mode_fragments = (
        "模式 A：有重点事件",
        "模式 B：无重点事件模式",
        "空结果状态",
        "`confidence=low`",
        "`credibility` 为 0–1 分",
        "重算总分 24–30 分",
        "重算总分 18–23 分",
        "研究模式（默认）",
        "维护模式",
    )
    for fragment in mode_fragments:
        if fragment not in text:
            errors.append(
                Issue(RADAR_WORKFLOW_SEMANTIC_MISSING, display_path, f"缺少 radar 工作流语义：{fragment}")
            )
    return ValidationResult(errors=tuple(errors))


def validate(context: SkillContext) -> ValidationResult:
    """返回独立结果，不接收或修改仓库级报告。"""

    results = [validate_skill_semantics(context)]
    watchlist = context.skill_dir / "assets" / "watchlist.csv"
    if watchlist.is_file():
        results.append(validate_watchlist(watchlist, context.repository_root))
    return ValidationResult.merge(*results)
