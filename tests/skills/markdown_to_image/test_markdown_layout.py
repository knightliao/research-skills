"""Markdown 解析、换行、分页与 SVG 输出测试。"""

from __future__ import annotations

import sys
import unittest
import xml.etree.ElementTree as element_tree
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / ".agents" / "skills" / "markdown-to-image" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import markdown_layout as layout


class MarkdownParsingTests(unittest.TestCase):
    def test_supported_blocks_and_inlines(self) -> None:
        source = """# 主标题

正文有 **粗体**、*斜体*、`code` 和 [链接](https://example.com/a?x=1&y=2)。

- 无序项
1. 有序项

> 引用内容

---

```python
print("hello")
```
"""
        blocks = layout.parse_markdown(source)
        self.assertEqual(
            ["h1", "paragraph", "ul_item", "ol_item", "quote", "hr", "code"],
            [block.kind for block in blocks],
        )
        paragraph = blocks[1]
        self.assertTrue(any(inline.bold and inline.text == "粗体" for inline in paragraph.inlines))
        self.assertTrue(any(inline.italic and inline.text == "斜体" for inline in paragraph.inlines))
        self.assertTrue(any(inline.code and inline.text == "code" for inline in paragraph.inlines))
        self.assertTrue(any(inline.link and inline.text == "链接" for inline in paragraph.inlines))
        self.assertTrue(
            any(inline.link_url and "https://example.com" in inline.text for inline in paragraph.inlines)
        )
        self.assertEqual("python", blocks[-1].language)

    def test_soft_and_hard_line_breaks(self) -> None:
        blocks = layout.parse_markdown("第一行\n第二行  \n第三行\\\n第四行\n")
        text = "".join(inline.text for inline in blocks[0].inlines)
        self.assertEqual("第一行 第二行\n第三行\n第四行", text)

    def test_unsupported_constructs_report_line_and_stable_code(self) -> None:
        cases = {
            "# 标题\n\n| A | B |\n| --- | --- |\n": (3, "TABLE_UNSUPPORTED"),
            "正文\n\n- [ ] 待办\n": (3, "TASK_LIST_UNSUPPORTED"),
            "正文\n\n![图](a.png)\n": (3, "IMAGE_UNSUPPORTED"),
            "正文\n\n<div>内容</div>\n": (3, "RAW_HTML_UNSUPPORTED"),
            "- 一级\n  - 二级\n": (2, "NESTED_LIST_UNSUPPORTED"),
            "> 一级\n>> 二级\n": (2, "NESTED_QUOTE_UNSUPPORTED"),
            "    print('x')\n": (1, "INDENTED_CODE_UNSUPPORTED"),
        }
        for source, expected in cases.items():
            with self.subTest(source=source), self.assertRaises(layout.MarkdownLayoutError) as error:
                layout.parse_markdown(source)
            self.assertEqual(expected, (error.exception.line, error.exception.code))

    def test_empty_and_unclosed_code_fail(self) -> None:
        with self.assertRaisesRegex(layout.MarkdownLayoutError, "内容为空"):
            layout.parse_markdown(" \n")
        with self.assertRaises(layout.MarkdownLayoutError) as error:
            layout.parse_markdown("```python\nprint(1)\n")
        self.assertEqual("CODE_FENCE_UNCLOSED", error.exception.code)


class LayoutTests(unittest.TestCase):
    def test_mixed_text_and_long_tokens_never_exceed_declared_width(self) -> None:
        source = (
            "# 中英混排与 emoji 🚀\n\n"
            "中文 English123 https://example.com/"
            + "very-long-token-" * 30
            + " 结束。\n"
        )
        blocks = layout.build_render_blocks(layout.parse_markdown(source))
        for block in blocks:
            for line in block.lines:
                self.assertLessEqual(line.width, block.width + 0.01)

    def test_inline_code_counts_cjk_as_full_width(self) -> None:
        block = layout.build_render_blocks(layout.parse_markdown("对 `关键术语` 做强调。\n"))[0]
        code_run = next(run for line in block.lines for run in line.runs if run.code)
        self.assertGreaterEqual(code_run.width, block.font_size * 4)

    def test_short_content_is_one_page_and_long_content_is_paginated(self) -> None:
        self.assertEqual(1, len(layout.layout_markdown("# 标题\n\n短内容。\n")))
        long_source = "# 长文\n\n" + "\n\n".join(
            f"第 {index} 段：" + "这是用于验证连续分页的中文内容。" * 8
            for index in range(1, 25)
        )
        pages = layout.layout_markdown(long_source)
        self.assertGreater(len(pages), 2)
        self.assertEqual(list(range(1, len(pages) + 1)), [page.number for page in pages])

    def test_long_image_keeps_all_content_in_one_dynamic_canvas(self) -> None:
        source = "# 单张长图\n\n" + "\n\n".join(
            f"第 {index} 段：" + "连续阅读内容。" * 45 for index in range(12)
        )
        render_blocks = layout.build_render_blocks(layout.parse_markdown(source))
        image = layout.layout_long_image(source)
        self.assertGreater(image.height, layout.PAGE_HEIGHT)
        self.assertLessEqual(image.height, layout.LONG_IMAGE_MAX_HEIGHT)
        self.assertEqual(len(render_blocks), len(image.fragments))
        for block, fragment in zip(render_blocks, image.fragments, strict=True):
            self.assertEqual(block.lines, fragment.lines)
            self.assertTrue(fragment.first)
            self.assertTrue(fragment.last)

    def test_oversized_long_image_fails_with_stable_code(self) -> None:
        source = "# 过长内容\n\n" + "\n\n".join(["正文。" * 120] * 100)
        with self.assertRaises(layout.MarkdownLayoutError) as error:
            layout.layout_long_image(source)
        self.assertEqual("LONG_IMAGE_TOO_TALL", error.exception.code)

    def test_horizontal_rule_renders_without_being_treated_as_heading(self) -> None:
        svg = layout.render_svgs("# 标题\n\n正文。\n\n---\n\n结语。\n")[0]
        self.assertIn("<line", svg)
        self.assertIn(layout.RULE, svg)

    def test_paginated_lines_are_neither_lost_nor_duplicated(self) -> None:
        source = "# 长内容\n\n" + "\n\n".join(
            f"段落 {index}：" + "甲乙丙丁戊己庚辛壬癸" * 16 for index in range(18)
        )
        render_blocks = layout.build_render_blocks(layout.parse_markdown(source))
        pages = layout.paginate(render_blocks)
        for block in render_blocks:
            expected = "".join(line.text for line in block.lines)
            actual = "".join(
                line.text
                for page in pages
                for fragment in page.fragments
                if fragment.block is block
                for line in fragment.lines
            )
            self.assertEqual(expected, actual, f"源行 {block.source_line}")

    def test_heading_stays_with_following_content(self) -> None:
        source = "\n\n".join(
            ["前文。" * 110, "## 不应孤立的标题", "标题后的正文。" * 30, "结尾。" * 80]
        )
        pages = layout.layout_markdown(source)
        heading_page = next(
            page
            for page in pages
            if any(fragment.block.heading_level == 2 for fragment in page.fragments)
        )
        heading_index = next(
            index
            for index, fragment in enumerate(heading_page.fragments)
            if fragment.block.heading_level == 2
        )
        self.assertLess(heading_index, len(heading_page.fragments) - 1)
        self.assertGreaterEqual(len(heading_page.fragments[heading_index + 1].lines), 2)

    def test_long_code_continues_with_background_and_label(self) -> None:
        source = "```python\n" + "\n".join(f"print({index})" for index in range(40)) + "\n```\n"
        pages = layout.layout_markdown(source)
        self.assertGreater(len(pages), 1)
        self.assertTrue(any(not fragment.first for page in pages for fragment in page.fragments))
        second_svg = layout.render_svg(pages[1], len(pages))
        self.assertIn("代码（续）", second_svg)
        self.assertIn(layout.CODE_BACKGROUND, second_svg)


class SvgTests(unittest.TestCase):
    def test_svg_is_well_formed_and_escapes_user_text(self) -> None:
        source = '# 标题 & < >\n\n正文有 [链接](https://example.com/?a=1&b=2) 和 `x < y`。\n'
        svg = layout.render_svgs(source)[0]
        element_tree.fromstring(svg)
        self.assertIn("&amp;", svg)
        self.assertIn("&lt;", svg)
        self.assertIn("https://example.com/?a=1&amp;b=2", svg)
        self.assertNotIn("< y", svg)

    def test_svg_preserves_code_indentation(self) -> None:
        svg = layout.render_svgs("```python\nif ready:\n    run()\n```\n")[0]
        self.assertIn('xml:space="preserve"', svg)
        self.assertIn(">    run()</text>", svg)

    def test_page_number_only_appears_for_multiple_pages(self) -> None:
        single = layout.render_svgs("# 标题\n\n短文。\n")[0]
        self.assertNotIn("1 / 1", single)
        multiple = layout.render_svgs("\n\n".join(["正文。" * 100] * 10))
        self.assertIn(f"1 / {len(multiple)}", multiple[0])

    def test_long_svg_uses_dynamic_height_without_page_number(self) -> None:
        source = "# 长图\n\n" + "\n\n".join(["连续内容。" * 80] * 6)
        svg, height = layout.render_long_svg(source)
        root = element_tree.fromstring(svg)
        self.assertEqual(str(layout.PAGE_WIDTH), root.attrib["width"])
        self.assertEqual(str(height), root.attrib["height"])
        self.assertGreater(height, layout.PAGE_HEIGHT)
        self.assertNotIn("1 / 1", svg)


if __name__ == "__main__":
    unittest.main()
