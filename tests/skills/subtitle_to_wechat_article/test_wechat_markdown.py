"""公众号源稿、插图计划、资源和 HTML 渲染测试。"""

from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / ".agents" / "skills" / "subtitle-to-wechat-article" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import render_wechat_html as renderer
import wechat_illustrations as illustrations
import wechat_markdown as markdown
import wechat_resources as resources


def png_chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind)
    crc = zlib.crc32(data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def valid_png(width: int = 235, height: int = 100) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + (b"\x00\x00\x00" * width) for _ in range(height))
    return (
        resources.PNG_SIGNATURE
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", zlib.compress(raw))
        + png_chunk(b"IEND", b"")
    )


def article_without_images(count: int = 20) -> str:
    return f"# 主标题\n\n## 第一节\n\n{'文' * count}\n\n第二段。\n\n## 第二节\n\n结语。\n"


def plan_text(*entries: tuple[str, int, str]) -> str:
    images = [
        {
            "file": f"images/body-{index:02d}.png",
            "purpose": purpose,
            "section": section,
            "insert_after_paragraph": paragraph,
        }
        for index, (section, paragraph, purpose) in enumerate(entries, 1)
    ]
    return json.dumps({"schema_version": 1, "images": images}, ensure_ascii=False)


class MarkdownStructureTests(unittest.TestCase):
    def test_supported_blocks_and_paragraph_merging(self) -> None:
        text = """# 主标题

## 第一节

第一行有 **重点**
第二行仍属同一段

1. 第一项
2. 第二项

- 甲
- 乙

> 引用内容

---
"""
        analysis = markdown.parse_and_validate(text)
        self.assertEqual(
            ["h1", "h2", "paragraph", "ol", "ul", "quote", "hr"],
            [block.kind for block in analysis.document.blocks],
        )
        paragraph = analysis.document.blocks[2]
        self.assertEqual("第一行有 重点 第二行仍属同一段", "".join(node.text for node in paragraph.inlines))

    def test_source_article_rejects_every_image_reference(self) -> None:
        text = "# 标题\n\n## 小节\n\n正文\n\n![用途](images/body-01.png)\n"
        with self.assertRaises(markdown.MarkdownValidationError) as context:
            markdown.parse_and_validate(text)
        self.assertEqual("IMAGE_REFERENCE_INVALID", context.exception.issues[0].code)

    def test_inline_bold_constraints(self) -> None:
        for value in ("**", "前****后", "**未闭合", "**跨行\n内容**", "**外层 **内层** 结束**"):
            with self.subTest(value=value), self.assertRaises(markdown.MarkdownValidationError):
                markdown.parse_article(f"# 标题\n\n## 小节\n\n{value}\n")

    def test_rejects_unsupported_constructs(self) -> None:
        invalid_blocks = {
            "table": "| A | B |\n| --- | --- |",
            "fenced code": "```python\nprint(1)\n```",
            "indented code": "    print(1)",
            "inline code": "包含 `code`",
            "html": "<span>文本</span>",
            "remote image": "![图](https://example.com/a.png)",
            "h3": "### 三级",
            "nested list": "- 一级\n  - 二级",
        }
        for name, block in invalid_blocks.items():
            with self.subTest(name=name), self.assertRaises(markdown.MarkdownValidationError):
                markdown.parse_and_validate(f"# 标题\n\n## 小节\n\n正文\n\n{block}\n")

    def test_character_count_boundaries_remain_deterministic(self) -> None:
        for count in (1500, 1501, 3000, 3001, 5000, 5001):
            with self.subTest(count=count):
                analysis = markdown.parse_and_validate(
                    f"# 主标题\n\n## 第一节\n\n{'文' * count}\n"
                )
                self.assertEqual(count, analysis.body_character_count)


class IllustrationPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analysis = markdown.parse_and_validate(article_without_images())

    def test_plan_positions_use_section_local_paragraphs(self) -> None:
        plan = illustrations.parse_illustration_plan(
            plan_text(("第一节", 2, "结构图"), ("第二节", 1, "结语图")),
            self.analysis,
            require_images=True,
        )
        self.assertEqual([2, 1], [item.insert_after_paragraph for item in plan.images])
        self.assertEqual(["第一节", "第二节"], [item.section for item in plan.images])

    def test_plan_rejects_missing_images_numbering_positions_and_ambiguity(self) -> None:
        invalid = (
            ({"schema_version": 1, "images": []}, True),
            ({"schema_version": 1, "images": [{"file": "images/body-02.png", "purpose": "图", "section": "第一节", "insert_after_paragraph": 1}]}, True),
            ({"schema_version": 1, "images": [{"file": "images/body-01.png", "purpose": "", "section": "第一节", "insert_after_paragraph": 1}]}, True),
            ({"schema_version": 1, "images": [{"file": "images/body-01.png", "purpose": "图", "section": "不存在", "insert_after_paragraph": 1}]}, True),
            ({"schema_version": 1, "images": [{"file": "images/body-01.png", "purpose": "图", "section": "第一节", "insert_after_paragraph": 3}]}, True),
        )
        for value, required in invalid:
            with self.subTest(value=value), self.assertRaises(illustrations.IllustrationPlanError):
                illustrations.parse_illustration_plan(
                    json.dumps(value, ensure_ascii=False), self.analysis, require_images=required
                )


class HtmlRenderingTests(unittest.TestCase):
    def test_escapes_user_text_and_inserts_planned_image(self) -> None:
        special = "& < > \" '"
        analysis = markdown.parse_and_validate(
            f"# 标题 {special}\n\n## 小节 {special}\n\n正文 {special} **强调 {special}**\n"
        )
        plan = illustrations.parse_illustration_plan(
            plan_text((f"小节 {special}", 1, f"用途 {special}")), analysis, require_images=True
        )
        output = renderer.render_html(analysis, plan.images)
        self.assertIn("&amp; &lt; &gt; &quot; &#x27;", output)
        self.assertNotIn(special, output)
        self.assertIn('src="images/body-01.png"', output)
        self.assertIn("font-size: 22px", output)
        self.assertIn("<strong>", output)

    def test_independent_renderer_validates_plan_resources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            article = root / "article.md"
            plan = root / "illustration-plan.json"
            article.write_text(article_without_images(), encoding="utf-8")
            plan.write_text(plan_text(("第一节", 1, "结构图")), encoding="utf-8")
            with mock.patch("sys.stdout"), mock.patch("sys.stderr"):
                self.assertEqual(1, renderer.main([str(article), "--illustration-plan", str(plan)]))
            (root / "images").mkdir()
            (root / "images" / "body-01.png").write_bytes(valid_png())
            self.assertEqual(
                0,
                renderer.main(
                    [str(article), "-o", str(root / "out.html"), "--illustration-plan", str(plan)]
                ),
            )
            self.assertTrue((root / "out.html").is_file())

    def test_renderer_without_plan_needs_no_body_resources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            article = root / "article.md"
            article.write_text(article_without_images(), encoding="utf-8")
            self.assertEqual(0, renderer.main([str(article), "-o", str(root / "out.html")]))


class PngValidationTests(unittest.TestCase):
    def test_valid_png_reports_dimensions(self) -> None:
        self.assertEqual((235, 100), resources.validate_png_bytes(valid_png()))

    def test_rejects_crc_truncation_missing_chunks_and_trailing_data(self) -> None:
        valid = valid_png()
        variants = {
            "bad signature": b"bad" + valid[3:],
            "bad crc": valid[:-1] + bytes([valid[-1] ^ 1]),
            "truncated": valid[:-3],
            "missing idat": resources.PNG_SIGNATURE
            + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 10, 10, 8, 2, 0, 0, 0))
            + png_chunk(b"IEND", b""),
            "missing iend": valid[:-12],
            "trailing": valid + b"extra",
        }
        for name, data in variants.items():
            with self.subTest(name=name), self.assertRaises(resources.PngValidationError):
                resources.validate_png_bytes(data)


if __name__ == "__main__":
    unittest.main()
