"""字幕规范化脚本的格式、编码、去重和 CLI 契约测试。"""

from __future__ import annotations

import codecs
import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from skill_framework.markdown import parse_frontmatter


ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = ROOT / ".agents" / "skills" / "subtitle-to-wechat-article"
SKILL_PATH = SKILL_DIR / "SKILL.md"
SCRIPT_PATH = (
    SKILL_DIR / "scripts" / "normalize_subtitle.py"
)


def load_normalizer_module():
    spec = importlib.util.spec_from_file_location("normalize_subtitle_under_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 normalize_subtitle.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


normalizer = load_normalizer_module()


class SubtitleSkillContractTests(unittest.TestCase):
    def test_frontmatter_contains_exactly_name_and_single_line_description(self) -> None:
        skill_text = SKILL_PATH.read_text(encoding="utf-8")
        values, error = parse_frontmatter(skill_text)
        self.assertIsNone(error)
        self.assertEqual({"name", "description"}, set(values))
        self.assertEqual("subtitle-to-wechat-article", values["name"])
        self.assertTrue(values["description"].strip())
        self.assertNotIn("\n", values["description"])

    def test_all_declared_runtime_resources_exist(self) -> None:
        expected_paths = (
            "assets/article-template.md",
            "examples/bad-example.md",
            "examples/chinese-example.md",
            "examples/english-example.md",
            "references/article-writing-guide.md",
            "references/quality-checklist.md",
            "references/subtitle-processing.md",
            "references/translation-policy.md",
            "scripts/normalize_subtitle.py",
        )
        skill_text = SKILL_PATH.read_text(encoding="utf-8")
        for relative_path in expected_paths:
            self.assertTrue((SKILL_DIR / relative_path).is_file(), relative_path)
            self.assertIn(f"]({relative_path})", skill_text)


class NormalizeSubtitleFormatTests(unittest.TestCase):
    def normalize(self, text: str, suffix: str, **kwargs):
        return normalizer.normalize_subtitle(
            text.encode("utf-8"),
            Path(f"sample{suffix}"),
            **kwargs,
        )

    def test_srt_removes_sequence_timestamps_tags_and_exact_duplicates(self) -> None:
        result = self.normalize(
            """1
00:00:01,000 --> 00:00:02,000
<i>第一行</i>
第二行

2
00:00:02,100 --> 00:00:03,000
第一行 第二行

3
00:00:03,100 --> 00:00:04,000
新的内容
""",
            ".srt",
        )
        self.assertEqual("第一行 第二行\n新的内容\n", result.text)
        self.assertEqual("srt", result.format_name)

    def test_srt_merges_only_exact_rolling_overlap(self) -> None:
        result = self.normalize(
            """1
00:00:01,000 --> 00:00:02,000
甲部分 共同片段

2
00:00:02,100 --> 00:00:03,000
共同片段 乙部分
""",
            ".srt",
        )
        self.assertEqual("甲部分 共同片段 乙部分\n", result.text)

    def test_srt_keeps_near_but_not_exact_overlap(self) -> None:
        result = self.normalize(
            """1
00:00:01,000 --> 00:00:02,000
这个方案可能有效

2
00:00:02,100 --> 00:00:03,000
这个方案很可能有效
""",
            ".srt",
        )
        self.assertEqual("这个方案可能有效\n这个方案很可能有效\n", result.text)

    def test_srt_does_not_deduplicate_different_speakers(self) -> None:
        cues = [
            normalizer.Cue("同一句", "甲"),
            normalizer.Cue("同一句", "乙"),
        ]
        self.assertEqual("甲：同一句\n乙：同一句", normalizer.render_cues(cues))

    def test_vtt_skips_control_blocks_and_preserves_voice(self) -> None:
        result = self.normalize(
            """WEBVTT

STYLE
::cue { color: lime; }

NOTE this is ignored
internal note

cue-1
00:00:01.000 --> 00:00:03.000 align:start
<v Maya><b>Hello</b> world</v>
""",
            ".vtt",
        )
        self.assertEqual("Maya：Hello world\n", result.text)

    def test_ass_uses_format_order_and_keeps_commas(self) -> None:
        result = self.normalize(
            """[Script Info]
Title: fictional

[Events]
Format: Start, End, Name, Style, Text
Dialogue: 0:00:01.00,0:00:03.00,Lin,Default,{\\i1}第一句,带逗号\\N第二行
Comment: 0:00:03.00,0:00:04.00,Lin,Default,不要保留
""",
            ".ass",
        )
        self.assertEqual("Lin：第一句,带逗号 第二行\n", result.text)

    def test_ass_without_text_format_fails(self) -> None:
        with self.assertRaisesRegex(normalizer.SubtitleError, "Text 字段"):
            self.normalize(
                """[Events]
Format: Start, End, Name
Dialogue: 0:00:01.00,0:00:03.00,Lin
""",
                ".ass",
            )

    def test_lrc_removes_metadata_multiple_timestamps_and_inline_times(self) -> None:
        result = self.normalize(
            """[ar:虚构歌手]
[00:01.00][00:05.00]第一句
[00:06.00]第一句
[00:07.00]<00:07.10>第二句
未同步补充
""",
            ".lrc",
        )
        self.assertEqual("第一句\n第二句\n未同步补充\n", result.text)

    def test_markdown_preserves_headings_lists_and_paragraphs(self) -> None:
        result = self.normalize(
            """# 标题

1
00:00:01.000 --> 00:00:02.000
- 第一项
- 第一项
- 第二项

讲者：结论
""",
            ".md",
            format_override="md",
        )
        self.assertEqual("# 标题\n\n- 第一项\n- 第二项\n\n讲者：结论\n", result.text)

    def test_plain_text_does_not_infer_rolling_overlap(self) -> None:
        result = self.normalize("共同片段 后半\n后半 新内容\n", ".txt")
        self.assertEqual("共同片段 后半\n后半 新内容\n", result.text)

    def test_content_signature_wins_over_extension_with_warning(self) -> None:
        result = self.normalize(
            """1
00:00:01,000 --> 00:00:02,000
正文
""",
            ".txt",
        )
        self.assertEqual("srt", result.format_name)
        self.assertTrue(result.warnings)
        self.assertIn("已采用内容特征", result.warnings[0])

    def test_format_override_is_authoritative(self) -> None:
        result = self.normalize("00:01 普通正文\n", ".unknown", format_override="txt")
        self.assertEqual("txt", result.format_name)
        self.assertEqual("00:01 普通正文\n", result.text)

    def test_unknown_plain_format_requires_override(self) -> None:
        with self.assertRaisesRegex(normalizer.SubtitleError, "--format"):
            self.normalize("普通正文\n", ".unknown")

    def test_timestamps_without_body_fail(self) -> None:
        with self.assertRaisesRegex(normalizer.SubtitleError, "没有可用"):
            self.normalize("1\n00:00:01,000 --> 00:00:02,000\n", ".srt")


class NormalizeSubtitleEncodingTests(unittest.TestCase):
    def test_utf8_bom_is_recognized(self) -> None:
        raw = codecs.BOM_UTF8 + "正文".encode("utf-8")
        result = normalizer.normalize_subtitle(raw, Path("sample.txt"))
        self.assertEqual("utf-8-sig", result.encoding)
        self.assertEqual("正文\n", result.text)

    def test_utf16_bom_is_recognized(self) -> None:
        raw = "正文".encode("utf-16")
        result = normalizer.normalize_subtitle(raw, Path("sample.txt"))
        self.assertEqual("utf-16", result.encoding)
        self.assertEqual("正文\n", result.text)

    def test_explicit_legacy_encoding_is_strict(self) -> None:
        raw = "中文正文".encode("gb18030")
        result = normalizer.normalize_subtitle(
            raw,
            Path("sample.txt"),
            encoding_override="gb18030",
        )
        self.assertEqual("gb18030", result.encoding)
        self.assertEqual("中文正文\n", result.text)

    def test_single_plausible_legacy_candidate_is_accepted(self) -> None:
        raw = "中文正文".encode("gb18030")
        with mock.patch.object(normalizer, "LEGACY_ENCODINGS", ("gb18030",)):
            text, encoding = normalizer.decode_subtitle(raw)
        self.assertEqual("gb18030", encoding)
        self.assertEqual("中文正文", text)

    def test_cp1252_can_be_the_only_plausible_legacy_candidate(self) -> None:
        raw = "Café déjà vu".encode("cp1252")
        text, encoding = normalizer.decode_subtitle(raw)
        self.assertEqual("cp1252", encoding)
        self.assertEqual("Café déjà vu", text)

    def test_real_ambiguous_cjk_bytes_require_encoding_override(self) -> None:
        raw = "中文正文".encode("gb18030")
        with self.assertRaisesRegex(normalizer.SubtitleError, "存在歧义.*--encoding"):
            normalizer.decode_subtitle(raw)

    def test_ambiguous_legacy_candidates_require_encoding_override(self) -> None:
        raw = b"\xe9 text"
        with (
            mock.patch.object(normalizer, "LEGACY_ENCODINGS", ("latin-1", "cp1252")),
            mock.patch.object(normalizer, "is_legacy_candidate_plausible", return_value=True),
        ):
            with self.assertRaisesRegex(normalizer.SubtitleError, "存在歧义.*--encoding"):
                normalizer.decode_subtitle(raw)

    def test_unknown_explicit_encoding_fails(self) -> None:
        with self.assertRaisesRegex(normalizer.SubtitleError, "未知编码"):
            normalizer.decode_subtitle(b"text", "not-a-real-codec")

    def test_binary_input_fails(self) -> None:
        with self.assertRaises(normalizer.SubtitleError):
            normalizer.normalize_subtitle(b"\x00\x01\x02\xff", Path("sample.txt"))

    def test_empty_input_fails(self) -> None:
        with self.assertRaisesRegex(normalizer.SubtitleError, "为空"):
            normalizer.normalize_subtitle(b"", Path("sample.txt"))


class NormalizeSubtitleCliTests(unittest.TestCase):
    def run_main(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = normalizer.main(argv)
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_default_writes_text_to_stdout_and_diagnostics_to_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "sample.txt"
            input_path.write_text("正文\n", encoding="utf-8")
            exit_code, stdout, stderr = self.run_main([str(input_path)])
        self.assertEqual(0, exit_code, stderr)
        self.assertEqual("正文\n", stdout)
        self.assertIn("检测格式：txt；编码：utf-8", stderr)

    def test_output_option_writes_utf8_file_without_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "sample.txt"
            output_path = Path(temporary_directory) / "normalized.txt"
            input_path.write_text("正文\n", encoding="utf-8")
            exit_code, stdout, stderr = self.run_main(
                [str(input_path), "-o", str(output_path)]
            )
            output_text = output_path.read_text(encoding="utf-8")
        self.assertEqual(0, exit_code, stderr)
        self.assertEqual("", stdout)
        self.assertEqual("正文\n", output_text)

    def test_failure_has_nonzero_exit_and_no_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "empty.srt"
            input_path.write_bytes(b"")
            exit_code, stdout, stderr = self.run_main([str(input_path)])
        self.assertNotEqual(0, exit_code)
        self.assertEqual("", stdout)
        self.assertIn("错误：", stderr)

    def test_output_cannot_overwrite_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "sample.txt"
            input_path.write_text("正文\n", encoding="utf-8")
            exit_code, stdout, stderr = self.run_main(
                [str(input_path), "-o", str(input_path)]
            )
        self.assertNotEqual(0, exit_code)
        self.assertEqual("", stdout)
        self.assertIn("不能与输入文件相同", stderr)


if __name__ == "__main__":
    unittest.main()
