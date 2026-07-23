#!/usr/bin/env python3
"""公众号文章本地资源和 PNG 的确定性校验。"""

from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

from wechat_markdown import ImagePlacement


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
VALID_BIT_DEPTHS = {
    0: {1, 2, 4, 8, 16},
    2: {8, 16},
    3: {1, 2, 4, 8},
    4: {8, 16},
    6: {8, 16},
}


@dataclass(frozen=True)
class PngInfo:
    width: int
    height: int
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class ResourceIssue:
    code: str
    message: str
    file: str | None = None


class PngValidationError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_png_bytes(data: bytes) -> tuple[int, int]:
    """校验完整 PNG 数据块、CRC、IHDR、IDAT 和 IEND。"""

    if not data.startswith(PNG_SIGNATURE):
        raise PngValidationError("PNG 签名无效")
    offset = len(PNG_SIGNATURE)
    chunk_index = 0
    ihdr_seen = False
    idat_seen = False
    iend_seen = False
    width = 0
    height = 0

    while offset < len(data):
        if len(data) - offset < 12:
            raise PngValidationError("PNG 数据块头或 CRC 被截断")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if data_end < data_start or crc_end > len(data):
            raise PngValidationError("PNG 数据块边界越界或被截断")
        chunk_data = data[data_start:data_end]
        recorded_crc = struct.unpack(">I", data[data_end:crc_end])[0]
        calculated_crc = zlib.crc32(chunk_type)
        calculated_crc = zlib.crc32(chunk_data, calculated_crc) & 0xFFFFFFFF
        if recorded_crc != calculated_crc:
            name = chunk_type.decode("ascii", errors="replace")
            raise PngValidationError(f"PNG 数据块 {name} 的 CRC 无效")

        if chunk_index == 0 and chunk_type != b"IHDR":
            raise PngValidationError("PNG 首个数据块必须是 IHDR")
        if chunk_type == b"IHDR":
            if ihdr_seen:
                raise PngValidationError("PNG 只能包含一个 IHDR")
            if length != 13:
                raise PngValidationError("PNG IHDR 长度必须为 13")
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", chunk_data
            )
            if width == 0 or height == 0 or width > 0x7FFFFFFF or height > 0x7FFFFFFF:
                raise PngValidationError("PNG 尺寸无效")
            if color_type not in VALID_BIT_DEPTHS or bit_depth not in VALID_BIT_DEPTHS[color_type]:
                raise PngValidationError("PNG IHDR 位深和颜色类型组合无效")
            if compression != 0 or filtering != 0 or interlace not in {0, 1}:
                raise PngValidationError("PNG IHDR 压缩、过滤或隔行字段无效")
            ihdr_seen = True
        elif chunk_type == b"IDAT":
            if not ihdr_seen:
                raise PngValidationError("PNG IDAT 不能位于 IHDR 之前")
            idat_seen = True
        elif chunk_type == b"IEND":
            if length != 0:
                raise PngValidationError("PNG IEND 长度必须为零")
            iend_seen = True
            offset = crc_end
            if offset != len(data):
                raise PngValidationError("PNG IEND 后不得包含额外字节")
            break

        offset = crc_end
        chunk_index += 1

    if not ihdr_seen:
        raise PngValidationError("PNG 缺少 IHDR")
    if not idat_seen:
        raise PngValidationError("PNG 缺少 IDAT")
    if not iend_seen:
        raise PngValidationError("PNG 缺少 IEND")
    return width, height


def validate_png_file(path: Path) -> PngInfo:
    if path.is_symlink():
        raise PngValidationError("图片不能是符号链接")
    try:
        stat_result = path.stat()
    except OSError as exc:
        raise PngValidationError(f"无法读取图片：{exc}") from exc
    if not path.is_file():
        raise PngValidationError("图片不是普通文件")
    if stat_result.st_size <= 0:
        raise PngValidationError("图片为空")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise PngValidationError(f"无法读取图片：{exc}") from exc
    width, height = validate_png_bytes(data)
    return PngInfo(width, height, len(data), hashlib.sha256(data).hexdigest())


def _is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def validate_article_resources(
    images: tuple[ImagePlacement, ...],
    base_directory: Path,
) -> tuple[dict[str, PngInfo], tuple[ResourceIssue, ...]]:
    """校验插画计划引用的正文图片；不重新解析 Markdown 或计划。"""

    base = base_directory.resolve()
    infos: dict[str, PngInfo] = {}
    issues: list[ResourceIssue] = []
    for image in images:
        candidate = base / image.file
        try:
            resolved_parent = candidate.parent.resolve(strict=True)
        except OSError:
            issues.append(ResourceIssue("IMAGE_MISSING", f"正文图片不存在：{image.file}", image.file))
            continue
        if not _is_within(resolved_parent, base):
            issues.append(ResourceIssue("IMAGE_INVALID", f"正文图片路径逃逸：{image.file}", image.file))
            continue
        if candidate.is_symlink() or not candidate.exists():
            code = "IMAGE_INVALID" if candidate.is_symlink() else "IMAGE_MISSING"
            issues.append(ResourceIssue(code, f"正文图片不可用：{image.file}", image.file))
            continue
        try:
            infos[image.file] = validate_png_file(candidate)
        except PngValidationError as exc:
            issues.append(ResourceIssue("IMAGE_INVALID", f"正文图片 {image.file} 无效：{exc}", image.file))
    return infos, tuple(issues)
