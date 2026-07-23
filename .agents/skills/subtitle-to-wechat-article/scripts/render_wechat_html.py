#!/usr/bin/env python3
"""将受限 Markdown 渲染为适合复制到公众号编辑器的 HTML。"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import uuid
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wechat_markdown import (  # noqa: E402
    ImagePlacement,
    InlineNode,
    MarkdownValidationError,
    StructureAnalysis,
    parse_and_validate,
)
from wechat_illustrations import (  # noqa: E402
    IllustrationPlanError,
    parse_illustration_plan,
)
from wechat_resources import validate_article_resources  # noqa: E402


class RenderError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def render_inlines(inlines: tuple[InlineNode, ...]) -> str:
    parts: list[str] = []
    for node in inlines:
        escaped = html.escape(node.text, quote=True)
        if node.kind == "strong":
            parts.append(f"<strong>{escaped}</strong>")
        else:
            parts.append(escaped)
    return "".join(parts)


def _render_image(image: ImagePlacement) -> str:
    source = html.escape(image.file, quote=True)
    alt = html.escape(image.purpose, quote=True)
    return (
        '<p style="margin: 24px 0 20px; text-align: center;">'
        f'<img src="{source}" alt="{alt}" style="display: block; width: 100%; height: auto; '
        'margin: 0 auto;"></p>'
    )


def render_html(
    analysis: StructureAnalysis,
    illustrations: tuple[ImagePlacement, ...] = (),
) -> str:
    """只消费共享 AST，不重新解析 Markdown。"""

    body: list[str] = []
    illustration_map = {
        (image.section, image.insert_after_paragraph): image
        for image in illustrations
    }
    current_section: str | None = None
    paragraph_index = 0
    for block in analysis.document.blocks:
        if block.kind == "h1":
            continue
        if block.kind == "h2":
            current_section = "".join(node.text for node in block.inlines).strip()
            paragraph_index = 0
            body.append(
                '<h2 style="margin: 34px 0 16px; font-size: 22px; line-height: 1.45; '
                f'font-weight: 700; color: #1f2329;">{render_inlines(block.inlines)}</h2>'
            )
        elif block.kind == "paragraph":
            paragraph_index += 1
            body.append(
                '<p style="margin: 0 0 20px; font-size: 17px; line-height: 1.8; '
                f'color: #2b2f36; text-align: justify;">{render_inlines(block.inlines)}</p>'
            )
            image = illustration_map.get((current_section, paragraph_index))
            if image is not None:
                body.append(_render_image(image))
        elif block.kind in {"ol", "ul"}:
            tag = block.kind
            items = "".join(
                '<li style="margin: 6px 0;">' + render_inlines(item) + "</li>"
                for item in block.items
            )
            body.append(
                f'<{tag} style="margin: 0 0 20px; padding-left: 1.6em; font-size: 17px; '
                f'line-height: 1.8; color: #2b2f36;">{items}</{tag}>'
            )
        elif block.kind == "quote":
            body.append(
                '<blockquote style="margin: 20px 0; padding: 12px 16px; border-left: 4px solid #9aa4b2; '
                'background: #f6f8fa; color: #4b5563; font-size: 17px; line-height: 1.8;">'
                f'{render_inlines(block.inlines)}</blockquote>'
            )
        elif block.kind == "hr":
            body.append('<hr style="margin: 32px 0; border: 0; border-top: 1px solid #d8dee4;">')

    escaped_title = html.escape(analysis.title, quote=True)
    body_html = "\n".join(body)
    return (
        "<!doctype html>\n"
        '<html lang="zh-CN">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        f"  <title>{escaped_title}</title>\n"
        "</head>\n"
        '<body style="margin: 0; padding: 0; background: #ffffff;">\n'
        '<section style="box-sizing: border-box; max-width: 760px; margin: 0 auto; padding: 24px 20px; '
        'font-family: -apple-system, BlinkMacSystemFont, &quot;Segoe UI&quot;, sans-serif;">\n'
        f"{body_html}\n"
        "</section>\n"
        "</body>\n"
        "</html>\n"
    )


def _complete_package_for_output(output_path: Path) -> Path | None:
    resolved = output_path.resolve(strict=False)
    for directory in (resolved.parent, *resolved.parents):
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if data.get("status") == "complete":
            return directory
    return None


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.wechat-tmp-{uuid.uuid4().hex}"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="受限 Markdown 文章")
    parser.add_argument("-o", "--output", type=Path, help="输出 HTML；默认写入 stdout")
    parser.add_argument(
        "--illustration-plan",
        type=Path,
        help="可选 illustration-plan.json；正文图片由该计划插入",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        try:
            text = args.input.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise RenderError("PACKAGE_INVALID", f"无法读取 Markdown：{exc}") from exc
        try:
            analysis = parse_and_validate(text)
        except MarkdownValidationError as exc:
            raise RenderError("MARKDOWN_INVALID", str(exc)) from exc
        illustrations: tuple[ImagePlacement, ...] = ()
        if args.illustration_plan is not None:
            try:
                plan_text = args.illustration_plan.read_text(encoding="utf-8")
                illustrations = parse_illustration_plan(
                    plan_text,
                    analysis,
                    require_images=False,
                ).images
            except (OSError, UnicodeError, IllustrationPlanError) as exc:
                raise RenderError("ILLUSTRATION_PLAN_INVALID", str(exc)) from exc
        _, resource_issues = validate_article_resources(illustrations, args.input.parent)
        if resource_issues:
            first = resource_issues[0]
            raise RenderError(first.code, first.message)
        output = render_html(analysis, illustrations)
        if args.output is None:
            sys.stdout.write(output)
        else:
            complete_package = _complete_package_for_output(args.output)
            if complete_package is not None:
                raise RenderError("PACKAGE_COMPLETE", f"complete 文章包不可修改：{complete_package}")
            _atomic_write(args.output, output)
        return 0
    except RenderError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
