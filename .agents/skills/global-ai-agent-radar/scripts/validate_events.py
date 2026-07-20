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


@dataclass(slots=True)
class EventResult:
    """保存单个事件的校验结果。"""

    index: int
    title: str
    total_score: int | None = None
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


def validate_scores(value: object, total_score: object, result: EventResult) -> None:
    """校验六项评分，并计算与核对总分。"""

    if not isinstance(value, dict):
        result.error("字段 scores 必须是对象")
        return

    calculated_total = 0
    scores_are_valid = True
    for field_name in SCORE_FIELDS:
        if field_name not in value:
            result.error(f"字段 scores 缺少评分维度 {field_name}")
            scores_are_valid = False
            continue
        score = value[field_name]
        if isinstance(score, bool) or not isinstance(score, int):
            result.error(f"评分 {field_name} 必须是整数")
            scores_are_valid = False
            continue
        if not 0 <= score <= 5:
            result.error(f"评分 {field_name} 必须在 0 至 5 之间")
            scores_are_valid = False
            continue
        calculated_total += score

    if scores_are_valid:
        result.total_score = calculated_total

    if total_score is None:
        return
    if isinstance(total_score, bool) or not isinstance(total_score, int):
        result.error("字段 total_score 必须是整数")
    elif scores_are_valid and total_score != calculated_total:
        result.error(
            f"字段 total_score 为 {total_score}，与六个评分维度之和 {calculated_total} 不一致"
        )


def validate_event(event: object, index: int) -> EventResult:
    """校验一个事件对象。"""

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

    if "source_url" in event:
        source_url = event["source_url"]
        if not is_non_empty_string(source_url) or not source_url.startswith(("http://", "https://")):
            result.error("字段 source_url 必须是以 http:// 或 https:// 开头的非空字符串")

    if "source_type" in event:
        source_type = event["source_type"]
        if not isinstance(source_type, str) or source_type not in SOURCE_TYPES:
            allowed = "、".join(sorted(SOURCE_TYPES))
            result.error(f"字段 source_type 必须是以下值之一：{allowed}")

    if "facts" in event:
        validate_string_list(event["facts"], "facts", result, allow_empty=False)

    if "inference" in event and not is_non_empty_string(event["inference"]):
        result.error("字段 inference 必须是非空字符串")

    if "scores" in event:
        validate_scores(event["scores"], event.get("total_score"), result)
    elif "total_score" in event:
        total_score = event["total_score"]
        if isinstance(total_score, bool) or not isinstance(total_score, int):
            result.error("字段 total_score 必须是整数")

    if "confidence" in event:
        confidence = event["confidence"]
        if not isinstance(confidence, str) or confidence not in CONFIDENCE_LEVELS:
            allowed = "、".join(sorted(CONFIDENCE_LEVELS))
            result.error(f"字段 confidence 必须是以下值之一：{allowed}")

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
        if not payload:
            raise ValueError("事件数组不得为空")
        return payload
    raise ValueError("JSON 顶层必须是单个事件对象或事件对象数组")


def build_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器。"""

    parser = argparse.ArgumentParser(
        description=(
            "校验 global-ai-agent-radar 研究事件 JSON。输入可为单个事件对象或事件对象数组；"
            "inference 必须使用非空字符串。"
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

    results = [validate_event(event, index) for index, event in enumerate(events, start=1)]
    errors = [message for result in results for message in result.errors]
    warnings = [message for result in results for message in result.warnings]

    for result in results:
        if result.total_score is not None:
            print(f"{result.context}：计算总分 {result.total_score}/30")

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

    print(f"校验通过：共 {len(events)} 个事件，0 个错误，{len(warnings)} 个警告。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
