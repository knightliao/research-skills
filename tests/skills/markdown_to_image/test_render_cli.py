"""PNG CLI、原子安装和失败清理测试。"""

from __future__ import annotations

import io
import os
import struct
import sys
import tempfile
import unittest
import zlib
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = ROOT / ".agents" / "skills" / "markdown-to-image"
SCRIPTS = SKILL_DIR / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import render_markdown_image as renderer


def png_chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind)
    crc = zlib.crc32(data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def valid_png(width: int = 1080, height: int = 1440) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + (b"\x00\x00\x00" * width) for _ in range(height))
    return (
        renderer.PNG_SIGNATURE
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", zlib.compress(raw))
        + png_chunk(b"IEND", b"")
    )


def make_fake_renderer(root: Path, *, mode: str = "valid") -> Path:
    path = root / f"fake-rsvg-{mode}"
    if mode == "fail":
        body = "import sys\nprint('fake renderer failed', file=sys.stderr)\nraise SystemExit(7)\n"
    elif mode == "valid":
        body = (
            "import pathlib, struct, sys, zlib\n"
            "def chunk(kind, data):\n"
            "    crc = zlib.crc32(data, zlib.crc32(kind)) & 0xFFFFFFFF\n"
            "    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', crc)\n"
            "width = int(sys.argv[sys.argv.index('-w') + 1])\n"
            "height = int(sys.argv[sys.argv.index('-h') + 1])\n"
            "ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)\n"
            "raw = b''.join(b'\\x00' + (b'\\x00\\x00\\x00' * width) for _ in range(height))\n"
            "png = b'\\x89PNG\\r\\n\\x1a\\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')\n"
            "output = pathlib.Path(sys.argv[sys.argv.index('-o') + 1])\n"
            "output.write_bytes(png)\n"
        )
    else:
        body = (
            "import pathlib, sys\n"
            "output = pathlib.Path(sys.argv[sys.argv.index('-o') + 1])\n"
            "output.write_bytes(b'not a png')\n"
        )
    path.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


class OutputPathTests(unittest.TestCase):
    def test_default_output_uses_incrementing_versions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            first = renderer.choose_output_dir("文章.md", None, cwd=root)
            self.assertEqual(root / "reports" / "markdown-to-image" / "文章-v1", first)
            first.mkdir(parents=True)
            second = renderer.choose_output_dir("文章.md", None, cwd=root)
            self.assertEqual(root / "reports" / "markdown-to-image" / "文章-v2", second)

    def test_explicit_existing_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(renderer.RenderError, "拒绝覆盖"):
                renderer.choose_output_dir("input.md", str(root), cwd=root)

    def test_missing_renderer_has_actionable_error(self) -> None:
        with self.assertRaisesRegex(renderer.RenderError, "找不到 rsvg-convert"):
            renderer.resolve_renderer("definitely-not-an-installed-renderer-123")


class AtomicRenderingTests(unittest.TestCase):
    def test_explicit_pagination_creates_only_valid_numbered_pngs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = make_fake_renderer(root)
            output = root / "result"
            source = "# 标题\n\n" + "\n\n".join(["正文。" * 100] * 8)
            paths = renderer.render_markdown_to_png(
                source,
                output,
                fake,
                paginate=True,
            )
            self.assertGreater(len(paths), 1)
            self.assertEqual(
                [f"page-{index:03d}.png" for index in range(1, len(paths) + 1)],
                [path.name for path in paths],
            )
            self.assertEqual(set(paths), set(output.iterdir()))
            for path in paths:
                self.assertEqual((1080, 1440), renderer.validate_png(path))

    def test_default_output_is_one_long_image_with_dynamic_height(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = make_fake_renderer(root)
            output = root / "result"
            source = "# 长文\n\n" + "\n\n".join(["这是连续长图内容。" * 60] * 8)
            expected_height = renderer.render_long_svg(source)[1]
            paths = renderer.render_markdown_to_png(
                source,
                output,
                fake,
            )
            self.assertEqual((output / "long-image.png",), paths)
            self.assertGreater(expected_height, 1440)
            self.assertEqual(
                (1080, expected_height),
                renderer.validate_png(
                    paths[0],
                    expected_width=1080,
                    expected_height=expected_height,
                ),
            )

    def test_renderer_failure_leaves_no_output_or_staging_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = make_fake_renderer(root, mode="fail")
            output = root / "result"
            with self.assertRaisesRegex(renderer.RenderError, "fake renderer failed"):
                renderer.render_markdown_to_png("# 标题\n", output, fake)
            self.assertFalse(output.exists())
            self.assertFalse(any(path.name.startswith(".result-") for path in root.iterdir()))

    def test_invalid_png_leaves_no_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = make_fake_renderer(root, mode="invalid")
            output = root / "result"
            with self.assertRaisesRegex(renderer.RenderError, "不是有效 PNG"):
                renderer.render_markdown_to_png("# 标题\n", output, fake)
            self.assertFalse(output.exists())

    def test_existing_output_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = make_fake_renderer(root)
            output = root / "result"
            output.mkdir()
            sentinel = output / "keep.txt"
            sentinel.write_text("保留", encoding="utf-8")
            with self.assertRaisesRegex(renderer.RenderError, "拒绝覆盖"):
                renderer.render_markdown_to_png("# 标题\n", output, fake)
            self.assertEqual("保留", sentinel.read_text(encoding="utf-8"))


class CliTests(unittest.TestCase):
    def test_default_stdin_cli_reports_one_long_image(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = make_fake_renderer(root)
            output = root / "result"
            stdout = io.StringIO()
            stderr = io.StringIO()
            original_stdin = sys.stdin
            try:
                sys.stdin = io.StringIO("# 标题\n\n正文。\n")
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = renderer.main(
                        ["-", "-o", str(output), "--renderer", str(fake)]
                    )
            finally:
                sys.stdin = original_stdin
            self.assertEqual(0, code, stderr.getvalue())
            self.assertEqual(["long-image.png"], [path.name for path in output.iterdir()])
            self.assertIn("已生成单张长图 PNG", stdout.getvalue())
            self.assertIn(str((output / "long-image.png").resolve()), stdout.getvalue())
            self.assertEqual("", stderr.getvalue())

    def test_paginate_cli_reports_numbered_pages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = make_fake_renderer(root)
            output = root / "result"
            stdout = io.StringIO()
            stderr = io.StringIO()
            original_stdin = sys.stdin
            try:
                sys.stdin = io.StringIO("# 标题\n\n" + "长图正文。" * 300)
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = renderer.main(
                        [
                            "-",
                            "-o",
                            str(output),
                            "--renderer",
                            str(fake),
                            "--paginate",
                        ]
                    )
            finally:
                sys.stdin = original_stdin
            self.assertEqual(0, code, stderr.getvalue())
            names = sorted(path.name for path in output.iterdir())
            self.assertGreater(len(names), 1)
            self.assertEqual(
                [f"page-{index:03d}.png" for index in range(1, len(names) + 1)],
                names,
            )
            self.assertIn(f"已生成 {len(names)} 张 PNG", stdout.getvalue())
            self.assertIn(str((output / "page-001.png").resolve()), stdout.getvalue())

    def test_unsupported_markdown_returns_nonzero_and_line_number(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = make_fake_renderer(root)
            output = root / "result"
            stderr = io.StringIO()
            source = root / "input.md"
            source.write_text("正文\n\n![图](a.png)\n", encoding="utf-8")
            with redirect_stderr(stderr):
                code = renderer.main(
                    [str(source), "-o", str(output), "--renderer", str(fake)]
                )
            self.assertEqual(1, code)
            self.assertIn("第 3 行", stderr.getvalue())
            self.assertIn("IMAGE_UNSUPPORTED", stderr.getvalue())
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
