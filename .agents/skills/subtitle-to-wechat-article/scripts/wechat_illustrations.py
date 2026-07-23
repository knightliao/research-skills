#!/usr/bin/env python3
"""解析并校验独立的公众号正文插图计划。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from wechat_markdown import ImagePlacement, StructureAnalysis


PLAN_SCHEMA_VERSION = 1
IMAGE_PATH_RE = re.compile(r"images/body-(\d{2})\.png\Z")


class IllustrationPlanError(ValueError):
    pass


@dataclass(frozen=True)
class IllustrationPlan:
    schema_version: int
    images: tuple[ImagePlacement, ...]


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IllustrationPlanError(f"illustration-plan.json 包含重复字段：{key}")
        result[key] = value
    return result


def _plain_text(block: Any) -> str:
    return "".join(node.text for node in block.inlines).strip()


def _section_paragraphs(analysis: StructureAnalysis) -> tuple[dict[str, int], dict[str, int]]:
    counts: dict[str, int] = {}
    order: dict[str, int] = {}
    current: str | None = None
    for block in analysis.document.blocks:
        if block.kind == "h2":
            current = _plain_text(block)
            if current in counts:
                raise IllustrationPlanError(f"二级标题重复，插图位置存在歧义：{current}")
            counts[current] = 0
            order[current] = len(order)
        elif block.kind == "paragraph" and current is not None:
            counts[current] += 1
    return counts, order


def parse_illustration_plan(
    text: str,
    analysis: StructureAnalysis,
    *,
    require_images: bool,
) -> IllustrationPlan:
    """解析 JSON 并相对于共享 Markdown AST 校验插图位置。"""

    try:
        data = json.loads(text, object_pairs_hook=_object_without_duplicates)
    except IllustrationPlanError:
        raise
    except json.JSONDecodeError as exc:
        raise IllustrationPlanError(f"illustration-plan.json 不是有效 JSON：{exc}") from exc
    if not isinstance(data, dict) or set(data) != {"schema_version", "images"}:
        raise IllustrationPlanError("illustration-plan.json 字段必须且只能包含 schema_version 和 images")
    if data["schema_version"] != PLAN_SCHEMA_VERSION:
        raise IllustrationPlanError("illustration-plan.json schema_version 不受支持")
    raw_images = data["images"]
    if not isinstance(raw_images, list):
        raise IllustrationPlanError("illustration-plan.json images 必须是数组")
    if require_images and not raw_images:
        raise IllustrationPlanError("body-images 模式至少需要一张正文图片")
    if len(raw_images) > 4:
        raise IllustrationPlanError("正文图片数量不得超过 4 张")
    if not raw_images:
        return IllustrationPlan(PLAN_SCHEMA_VERSION, ())

    section_counts, section_order = _section_paragraphs(analysis)
    placements: list[ImagePlacement] = []
    occupied: set[tuple[str, int]] = set()
    previous_position: tuple[int, int] | None = None
    for offset, item in enumerate(raw_images, 1):
        if not isinstance(item, dict) or set(item) != {
            "file",
            "purpose",
            "section",
            "insert_after_paragraph",
        }:
            raise IllustrationPlanError(f"第 {offset} 张正文图片字段不符合 schema")
        file = item["file"]
        purpose = item["purpose"]
        section = item["section"]
        paragraph = item["insert_after_paragraph"]
        if not isinstance(file, str):
            raise IllustrationPlanError(f"第 {offset} 张正文图片 file 必须是字符串")
        match = IMAGE_PATH_RE.fullmatch(file)
        if match is None or int(match.group(1)) != offset:
            raise IllustrationPlanError(
                f"正文图片必须从 images/body-01.png 开始连续编号，第 {offset} 项为 {file}"
            )
        if not isinstance(purpose, str) or not purpose.strip():
            raise IllustrationPlanError(f"第 {offset} 张正文图片 purpose 不能为空")
        if not isinstance(section, str) or not section.strip():
            raise IllustrationPlanError(f"第 {offset} 张正文图片 section 不能为空")
        section = section.strip()
        if section not in section_counts:
            raise IllustrationPlanError(f"第 {offset} 张正文图片引用不存在的二级标题：{section}")
        if isinstance(paragraph, bool) or not isinstance(paragraph, int) or paragraph < 1:
            raise IllustrationPlanError(
                f"第 {offset} 张正文图片 insert_after_paragraph 必须是正整数"
            )
        if paragraph > section_counts[section]:
            raise IllustrationPlanError(
                f"第 {offset} 张正文图片超出章节“{section}”的普通段落数量"
            )
        position = (section_order[section], paragraph)
        if previous_position is not None and position <= previous_position:
            raise IllustrationPlanError("正文图片必须按文章中的插入顺序排列")
        if (section, paragraph) in occupied:
            raise IllustrationPlanError("同一普通段落之后只能插入一张正文图片")
        previous_position = position
        occupied.add((section, paragraph))
        placements.append(
            ImagePlacement(
                file=file,
                index=offset,
                purpose=purpose.strip(),
                section=section,
                insert_after_paragraph=paragraph,
                line=0,
            )
        )
    return IllustrationPlan(PLAN_SCHEMA_VERSION, tuple(placements))
