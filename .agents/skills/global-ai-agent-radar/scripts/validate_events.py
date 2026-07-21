#!/usr/bin/env python3
"""校验 global-ai-agent-radar 使用的研究事件 JSON 数据。"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Sequence
from urllib.parse import urlsplit, urlunsplit


SOURCE_TYPES = frozenset(
    {
        "official",
        "documentation",
        "github",
        "paper",
        "filing",
        "media",
        "community",
        "social",
    }
)
SOURCE_ROLES = frozenset({"primary", "independent", "timing", "background"})
SCORE_FIELDS = (
    "novelty",
    "product_impact",
    "engineering_impact",
    "commercialization_impact",
    "ecosystem_impact",
    "credibility",
)
CONFIDENCE_LEVELS = frozenset({"high", "medium", "low"})
REQUIRED_FIELDS = (
    "title",
    "event_date",
    "publication_date",
    "source_url",
    "source_type",
    "facts",
    "inference",
    "scores",
    "confidence",
    "follow_up_signals",
)

PRIORITY_EVENT = "重点事件"
GENERAL_EVENT = "一般重要事件"
FOLLOW_UP_SIGNAL = "待验证信号"


@dataclass(slots=True)
class EventResult:
    """保存单个事件的校验结果。"""

    index: int
    title: str
    total_score: int | None = None
    classification: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def context(self) -> str:
        display_title = self.title if self.title else "未命名事件"
        return f"事件 {self.index}（{display_title}）"

    def error(self, message: str) -> None:
        self.errors.append(f"{self.context}：{message}")

    def warning(self, message: str) -> None:
        self.warnings.append(f"{self.context}：{message}")


def is_non_empty_string(value: object) -> bool:
    """判断值是否为去除首尾空白后仍非空的字符串。"""

    return isinstance(value, str) and bool(value.strip())


def parse_iso_date(value: object) -> date | None:
    """严格解析 YYYY-MM-DD；格式或日历日期无效时返回 None。"""

    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def parse_http_url(value: object) -> str | None:
    """校验 HTTP(S) URL，并返回去除首尾空白后的原值。"""

    if not is_non_empty_string(value):
        return None
    url = value.strip()
    if any(character.isspace() for character in url):
        return None
    try:
        parts = urlsplit(url)
        hostname = parts.hostname
        _ = parts.port
    except ValueError:
        return None
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc or hostname is None:
        return None
    return url


def normalize_netloc(netloc: str) -> str:
    """只规范化 netloc 中大小写不敏感的 hostname 部分。"""

    userinfo, separator, host_port = netloc.rpartition("@")
    prefix = f"{userinfo}@" if separator else ""
    if host_port.startswith("["):
        closing_bracket = host_port.find("]")
        if closing_bracket != -1:
            host = host_port[: closing_bracket + 1].lower()
            return f"{prefix}{host}{host_port[closing_bracket + 1:]}"
    host, port_separator, port = host_port.rpartition(":")
    if port_separator:
        return f"{prefix}{host.lower()}:{port}"
    return f"{prefix}{host_port.lower()}"


def normalize_url_for_deduplication(url: str) -> str:
    """保守规范化 URL；保留 path、query、编码、端口和末尾斜杠。"""

    parts = urlsplit(url.strip())
    return urlunsplit(
        (
            parts.scheme.lower(),
            normalize_netloc(parts.netloc),
            parts.path,
            parts.query,
            "",
        )
    )


def validate_string_list(
    value: object,
    field_name: str,
    result: EventResult,
    *,
    allow_empty: bool,
) -> None:
    """校验由非空字符串组成的列表。"""

    if not isinstance(value, list):
        result.error(f"字段 {field_name} 必须是列表")
        return
    if not value and not allow_empty:
        result.error(f"字段 {field_name} 不得为空列表")
        return
    for item_index, item in enumerate(value, start=1):
        if not is_non_empty_string(item):
            result.error(f"字段 {field_name} 的第 {item_index} 项必须是非空字符串")


def validate_enum(
    value: object,
    field_name: str,
    allowed_values: frozenset[str],
    result: EventResult,
) -> str | None:
    """校验字符串枚举并返回合法值。"""

    if not isinstance(value, str) or value not in allowed_values:
        allowed = "、".join(sorted(allowed_values))
        result.error(f"字段 {field_name} 必须是以下值之一：{allowed}")
        return None
    return value


def validate_scores(
    value: object,
    *,
    total_score_is_present: bool,
    supplied_total_score: object,
    result: EventResult,
) -> dict[str, int] | None:
    """校验六项评分，重算总分，并核对可选的输入总分。"""

    if not isinstance(value, dict):
        result.error("字段 scores 必须是对象")
        return None

    validated_scores: dict[str, int] = {}
    for field_name in SCORE_FIELDS:
        if field_name not in value:
            result.error(f"字段 scores 缺少评分维度 {field_name}")
            continue
        score = value[field_name]
        if isinstance(score, bool) or not isinstance(score, int):
            result.error(f"评分 {field_name} 必须是整数")
            continue
        if not 0 <= score <= 5:
            result.error(f"评分 {field_name} 必须在 0 至 5 之间")
            continue
        validated_scores[field_name] = score

    scores_are_valid = len(validated_scores) == len(SCORE_FIELDS)
    if scores_are_valid:
        result.total_score = sum(validated_scores.values())

    if total_score_is_present:
        if isinstance(supplied_total_score, bool) or not isinstance(supplied_total_score, int):
            result.error("字段 total_score 必须是整数")
        elif scores_are_valid and supplied_total_score != result.total_score:
            result.error(
                f"字段 total_score 为 {supplied_total_score}，"
                f"与六个评分维度之和 {result.total_score} 不一致"
            )

    return validated_scores if scores_are_valid else None


def classify_event(total_score: int, credibility: int, confidence: str) -> str | None:
    """按固定优先级分类；None 表示条目必须排除。"""

    if credibility <= 1:
        return None
    if confidence == "low":
        return FOLLOW_UP_SIGNAL
    if credibility == 2:
        return FOLLOW_UP_SIGNAL
    if total_score >= 24:
        return PRIORITY_EVENT
    if total_score >= 18:
        return GENERAL_EVENT
    return FOLLOW_UP_SIGNAL


def validate_additional_sources(
    value: object,
    *,
    primary_url: str | None,
    result: EventResult,
) -> bool:
    """校验补充来源、统一去重，并返回是否声明 independent 来源。"""

    if not isinstance(value, list):
        result.error("字段 additional_sources 必须是列表")
        return False

    seen_urls: dict[str, str] = {}
    if primary_url is not None:
        seen_urls[normalize_url_for_deduplication(primary_url)] = "主要来源 source_url"

    has_independent_declaration = False
    for item_index, item in enumerate(value, start=1):
        item_context = f"additional_sources 的第 {item_index} 项"
        if not isinstance(item, dict):
            result.error(f"{item_context}必须是对象")
            continue

        for field_name in ("url", "type", "role"):
            if field_name not in item:
                result.error(f"{item_context}缺少字段 {field_name}")

        source_url = None
        if "url" in item:
            source_url = parse_http_url(item["url"])
            if source_url is None:
                result.error(f"{item_context}的 url 必须是有效的 HTTP 或 HTTPS URL")
            else:
                normalized_url = normalize_url_for_deduplication(source_url)
                previous_location = seen_urls.get(normalized_url)
                if previous_location is not None:
                    result.error(f"{item_context}的 url 与“{previous_location}”重复")
                else:
                    seen_urls[normalized_url] = item_context

        if "type" in item:
            validate_enum(item["type"], f"{item_context}.type", SOURCE_TYPES, result)

        role = None
        if "role" in item:
            role = validate_enum(item["role"], f"{item_context}.role", SOURCE_ROLES, result)
        if role == "independent":
            has_independent_declaration = True

        if "publication_date" in item and parse_iso_date(item["publication_date"]) is None:
            result.error(f"{item_context}的 publication_date 必须是有效的 YYYY-MM-DD 日期")

    return has_independent_declaration


def validate_event(event: object, index: int) -> EventResult:
    """校验一个最终事件或待验证信号对象。"""

    title = event.get("title", "") if isinstance(event, dict) else ""
    result = EventResult(index=index, title=title.strip() if isinstance(title, str) else "")
    if not isinstance(event, dict):
        result.error("事件必须是 JSON 对象")
        return result

    for field_name in REQUIRED_FIELDS:
        if field_name not in event:
            result.error(f"缺少必填字段 {field_name}")

    if "title" in event and not is_non_empty_string(event["title"]):
        result.error("字段 title 必须是非空字符串")

    event_date = None
    publication_date = None
    if "event_date" in event:
        event_date = parse_iso_date(event["event_date"])
        if event_date is None:
            result.error("字段 event_date 必须是有效的 YYYY-MM-DD 日期")
    if "publication_date" in event:
        publication_date = parse_iso_date(event["publication_date"])
        if publication_date is None:
            result.error("字段 publication_date 必须是有效的 YYYY-MM-DD 日期")
    if event_date is not None and publication_date is not None and event_date > publication_date:
        result.warning("event_date 晚于 publication_date，请复核事件发生时间与信息发布时间")

    primary_url = None
    if "source_url" in event:
        primary_url = parse_http_url(event["source_url"])
        if primary_url is None:
            result.error("字段 source_url 必须是有效的 HTTP 或 HTTPS URL")

    if "source_type" in event:
        validate_enum(event["source_type"], "source_type", SOURCE_TYPES, result)

    has_independent_declaration = False
    if "additional_sources" in event:
        has_independent_declaration = validate_additional_sources(
            event["additional_sources"],
            primary_url=primary_url,
            result=result,
        )

    if "facts" in event:
        validate_string_list(event["facts"], "facts", result, allow_empty=False)

    if "inference" in event and not is_non_empty_string(event["inference"]):
        result.error("字段 inference 必须是非空字符串")

    validated_scores = None
    if "scores" in event:
        validated_scores = validate_scores(
            event["scores"],
            total_score_is_present="total_score" in event,
            supplied_total_score=event.get("total_score"),
            result=result,
        )
    elif "total_score" in event:
        total_score = event["total_score"]
        if isinstance(total_score, bool) or not isinstance(total_score, int):
            result.error("字段 total_score 必须是整数")

    confidence = None
    if "confidence" in event:
        confidence = validate_enum(event["confidence"], "confidence", CONFIDENCE_LEVELS, result)

    if "follow_up_signals" in event:
        follow_up_signals = event["follow_up_signals"]
        validate_string_list(
            follow_up_signals,
            "follow_up_signals",
            result,
            allow_empty=True,
        )
        if isinstance(follow_up_signals, list) and not follow_up_signals:
            result.warning("follow_up_signals 为空，缺少后续可验证指标")

    if validated_scores is not None and confidence is not None and result.total_score is not None:
        credibility = validated_scores["credibility"]
        result.classification = classify_event(result.total_score, credibility, confidence)
        if result.classification is None:
            result.error("credibility 为 0–1，条目不得进入最终事件清单")
        elif result.classification in {PRIORITY_EVENT, GENERAL_EVENT}:
            if not has_independent_declaration:
                result.warning(
                    "未在 additional_sources 中声明 role=independent 的来源；"
                    "此检查只确认结构声明，不验证来源是否真正独立或支持事实"
                )

    return result


def load_events(path: Path) -> list[object]:
    """从单个对象或对象数组形式的 JSON 文件读取事件。"""

    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except OSError as exc:
        raise ValueError(f"无法读取输入文件：{exc}") from exc
    except UnicodeDecodeError as exc:
        raise ValueError("输入文件必须使用 UTF-8 编码") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"无法解析 JSON：第 {exc.lineno} 行、第 {exc.colno} 列附近格式错误"
        ) from exc

    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return payload
    raise ValueError("JSON 顶层必须是单个事件对象或事件对象数组")


def build_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器。"""

    parser = argparse.ArgumentParser(
        description=(
            "校验 global-ai-agent-radar 最终事件 JSON。输入可为单个事件对象或事件对象数组；"
            "空数组表示没有最终条目的空结果状态。"
        ),
        epilog=(
            "分类始终使用六项评分重算总分，并依次应用 credibility、confidence 和总分门槛。"
            "additional_sources.role=primary 只补充顶层主要来源；role=independent 只表示结构声明，"
            "脚本不验证事实或来源独立性。完整契约见 references/event-schema.md。"
        ),
        add_help=False,
    )
    parser._positionals.title = "位置参数"
    parser._optionals.title = "选项"
    parser.add_argument("-h", "--help", action="help", help="显示此帮助信息并退出")
    parser.add_argument("input_file", type=Path, help="待校验的 UTF-8 JSON 文件")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """运行命令行校验并返回进程退出码。"""

    args = build_parser().parse_args(argv)
    try:
        events = load_events(args.input_file)
    except ValueError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    if not events:
        print("校验通过：空结果状态，0 个最终条目，0 个错误，0 个警告。")
        return 0

    results = [validate_event(event, index) for index, event in enumerate(events, start=1)]
    errors = [message for result in results for message in result.errors]
    warnings = [message for result in results for message in result.warnings]

    for result in results:
        if result.total_score is not None:
            output = f"{result.context}：重算总分 {result.total_score}/30"
            if result.classification is not None:
                output = f"{output}；分类 {result.classification}"
            print(output)

    if warnings:
        print("警告：")
        for message in warnings:
            print(f"- {message}")
    if errors:
        print("错误：", file=sys.stderr)
        for message in errors:
            print(f"- {message}", file=sys.stderr)
        print(
            f"校验失败：共 {len(events)} 个事件，发现 {len(errors)} 个错误和 {len(warnings)} 个警告。",
            file=sys.stderr,
        )
        return 1

    if any(result.classification == PRIORITY_EVENT for result in results):
        print("报告模式：模式 A（有重点事件）。")
    else:
        print("报告模式：无重点事件模式（事件清单非空）。")
    print(f"校验通过：共 {len(events)} 个事件，0 个错误，{len(warnings)} 个警告。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
