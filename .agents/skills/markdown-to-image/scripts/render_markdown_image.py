#!/usr/bin/env python3
"""把受支持的 Markdown 原子渲染为分页 PNG 或单张长图。"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path
from typing import Sequence

from markdown_layout import (
    MarkdownLayoutError,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    render_long_svg,
    render_svgs,
)


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class RenderError(RuntimeError):
    """可直接展示给用户的渲染错误。"""


def read_markdown(input_value: str) -> str:
    if input_value == "-":
        text = sys.stdin.read()
        if not text.strip():
            raise RenderError("stdin 中没有可渲染的 Markdown 内容")
        return text
    path = Path(input_value).expanduser()
    if not path.is_file():
        raise RenderError(f"输入文件不存在或不是普通文件：{path}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise RenderError(f"输入文件不是有效 UTF-8：{path}") from exc
    except OSError as exc:
        raise RenderError(f"无法读取输入文件 {path}：{exc}") from exc
    if not text.strip():
        raise RenderError(f"输入文件为空：{path}")
    return text


def resolve_renderer(renderer: str | None) -> Path:
    candidate = renderer or "rsvg-convert"
    if os.sep in candidate or (os.altsep and os.altsep in candidate):
        path = Path(candidate).expanduser().resolve()
        if not path.is_file() or not os.access(path, os.X_OK):
            raise RenderError(f"渲染器不存在或不可执行：{path}")
        return path
    resolved = shutil.which(candidate)
    if resolved is None:
        raise RenderError(
            "找不到 rsvg-convert；请先安装 librsvg，或使用 --renderer 指定可执行文件"
        )
    return Path(resolved).resolve()


def _safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u3400-\u9fff-]+", "-", value).strip("-").lower()
    return cleaned[:64] or "markdown"


def choose_output_dir(
    input_value: str,
    explicit_output: str | None,
    *,
    cwd: Path | None = None,
) -> Path:
    base = (cwd or Path.cwd()).resolve()
    if explicit_output:
        output = Path(explicit_output).expanduser()
        output = output if output.is_absolute() else base / output
        output = output.resolve()
        if output.exists():
            raise RenderError(f"输出目录已存在，拒绝覆盖：{output}")
        return output

    stem = "markdown" if input_value == "-" else _safe_stem(Path(input_value).stem)
    parent = base / "reports" / "markdown-to-image"
    version = 1
    while True:
        output = parent / f"{stem}-v{version}"
        if not output.exists():
            return output
        version += 1


def validate_png(
    path: Path,
    *,
    expected_width: int = PAGE_WIDTH,
    expected_height: int = PAGE_HEIGHT,
) -> tuple[int, int]:
    """校验 PNG 数据块、CRC、边界及预期画布尺寸。"""

    try:
        data = path.read_bytes()
    except OSError as exc:
        raise RenderError(f"无法读取渲染结果 {path}：{exc}") from exc
    if not data.startswith(PNG_SIGNATURE):
        raise RenderError(f"渲染结果不是有效 PNG：{path}")

    offset = len(PNG_SIGNATURE)
    width = height = None
    seen_ihdr = seen_idat = seen_iend = False
    while offset < len(data):
        if offset + 12 > len(data):
            raise RenderError(f"PNG 数据块被截断：{path}")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if crc_end > len(data):
            raise RenderError(f"PNG 数据块越界：{path}")
        payload = data[data_start:data_end]
        expected_crc = struct.unpack(">I", data[data_end:crc_end])[0]
        actual_crc = zlib.crc32(kind)
        actual_crc = zlib.crc32(payload, actual_crc) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            raise RenderError(f"PNG 数据块 CRC 无效：{path}")
        if not seen_ihdr and kind != b"IHDR":
            raise RenderError(f"PNG 首个数据块不是 IHDR：{path}")
        if kind == b"IHDR":
            if seen_ihdr or length != 13:
                raise RenderError(f"PNG IHDR 无效：{path}")
            width, height = struct.unpack(">II", payload[:8])
            seen_ihdr = True
        elif kind == b"IDAT":
            seen_idat = True
        elif kind == b"IEND":
            if length != 0 or crc_end != len(data):
                raise RenderError(f"PNG IEND 或尾部数据无效：{path}")
            seen_iend = True
            offset = crc_end
            break
        offset = crc_end

    if not (seen_ihdr and seen_idat and seen_iend) or width is None or height is None:
        raise RenderError(f"PNG 缺少必需数据块：{path}")
    if (width, height) != (expected_width, expected_height):
        raise RenderError(
            f"PNG 尺寸必须为 {expected_width}×{expected_height}，"
            f"实际为 {width}×{height}：{path}"
        )
    return width, height


def _renderer_diagnostic(result: subprocess.CompletedProcess[str]) -> str:
    diagnostic = (result.stderr or result.stdout or "没有诊断信息").strip()
    if len(diagnostic) > 500:
        diagnostic = diagnostic[:497] + "…"
    return diagnostic


def render_markdown_to_png(
    markdown_text: str,
    output_dir: Path,
    renderer: Path,
    *,
    timeout_seconds: int = 60,
    paginate: bool = False,
) -> tuple[Path, ...]:
    """先在临时目录生成并校验 PNG，再原子安装输出目录。"""

    if output_dir.exists():
        raise RenderError(f"输出目录已存在，拒绝覆盖：{output_dir}")
    if paginate:
        svgs = render_svgs(markdown_text)
        render_jobs = tuple(
            (f"page-{index:03d}", svg, PAGE_HEIGHT)
            for index, svg in enumerate(svgs, 1)
        )
    else:
        long_svg, long_height = render_long_svg(markdown_text)
        render_jobs = (("long-image", long_svg, long_height),)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}-", dir=output_dir.parent)
    )
    try:
        for index, (name, svg, image_height) in enumerate(render_jobs, 1):
            item_label = f"第 {index} 页" if paginate else "长图"
            svg_path = staging / f"{name}.svg"
            png_path = staging / f"{name}.png"
            svg_path.write_text(svg, encoding="utf-8")
            command = [
                str(renderer),
                "-w",
                str(PAGE_WIDTH),
                "-h",
                str(image_height),
                "-o",
                str(png_path),
                str(svg_path),
            ]
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise RenderError(f"{item_label}渲染超时（{timeout_seconds} 秒）") from exc
            except OSError as exc:
                raise RenderError(f"无法执行渲染器 {renderer}：{exc}") from exc
            if result.returncode != 0:
                raise RenderError(
                    f"{item_label}渲染失败：{_renderer_diagnostic(result)}"
                )
            validate_png(
                png_path,
                expected_width=PAGE_WIDTH,
                expected_height=image_height,
            )
            svg_path.unlink()

        os.replace(staging, output_dir)
        return tuple(output_dir / f"{name}.png" for name, _, _ in render_jobs)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="默认将受支持的 Markdown 忠实排版为单张长图，可显式分页",
    )
    parser.add_argument("input", help="UTF-8 Markdown 文件；使用 - 从 stdin 读取")
    parser.add_argument("-o", "--output-dir", help="新输出目录；已存在时拒绝覆盖")
    parser.add_argument(
        "--renderer",
        help="rsvg-convert 可执行文件路径或命令名（默认从 PATH 查找）",
    )
    parser.add_argument(
        "--paginate",
        action="store_true",
        help="按 1080×1440 分页输出 page-001.png 等文件；默认输出单张长图",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        markdown_text = read_markdown(args.input)
        output_dir = choose_output_dir(args.input, args.output_dir)
        renderer = resolve_renderer(args.renderer)
        paths = render_markdown_to_png(
            markdown_text,
            output_dir,
            renderer,
            paginate=args.paginate,
        )
    except (MarkdownLayoutError, RenderError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1

    if args.paginate:
        print(f"已生成 {len(paths)} 张 PNG：")
    else:
        print("已生成单张长图 PNG：")
    for path in paths:
        print(path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
