#!/usr/bin/env python3
"""创建、填充并完成不可覆盖的公众号文章包。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from render_wechat_html import render_html  # noqa: E402
from wechat_illustrations import (  # noqa: E402
    IllustrationPlanError,
    parse_illustration_plan,
)
from wechat_markdown import (  # noqa: E402
    ImagePlacement,
    MarkdownValidationError,
    StructureAnalysis,
    parse_and_validate,
)
from wechat_resources import (  # noqa: E402
    PngInfo,
    PngValidationError,
    sha256_file,
    validate_article_resources,
    validate_png_file,
)


SCHEMA_VERSION = 2
ILLUSTRATION_PLAN_FILE = "illustration-plan.json"
PACKAGE_MODES = {"cover-only", "body-images"}
PACKAGE_STATUSES = {"incomplete", "complete"}
PROMPT_STATUSES = {"missing", "ready", "invalid"}
IMAGE_STATUSES = {"missing", "ready", "invalid"}
INTERNAL_RE = re.compile(r"^\..+\.wechat-(?:tmp|reserve)-[0-9a-f]{32}$")
PROMPT_HEADING_RE = re.compile(r"^## (cover|body-(\d{2}))$")
ERROR_ORDER = {
    "article": 0,
    "markdown": 1,
    "illustrations": 2,
    "prompts": 3,
    "images": 4,
    "package": 5,
    "render": 6,
    "image_generation": 7,
}


@dataclass(frozen=True)
class CurrentState:
    analysis: StructureAnalysis | None
    illustrations: tuple[ImagePlacement, ...]
    errors: list[dict[str, str]]


class PackageError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def error(stage: str, code: str, message: str) -> dict[str, str]:
    return {"stage": stage, "code": code, "message": message}


def sort_errors(errors: list[dict[str, str]]) -> list[dict[str, str]]:
    unique: dict[tuple[str, str, str], dict[str, str]] = {}
    for item in errors:
        key = (item["stage"], item["code"], item["message"])
        unique[key] = item
    return sorted(
        unique.values(),
        key=lambda item: (ERROR_ORDER.get(item["stage"], 99), item["code"], item["message"]),
    )


def sanitize_stem(value: str) -> str:
    normalized = unicodedata.normalize("NFC", Path(value).name)
    if "." in normalized and normalized not in {".", ".."}:
        normalized = Path(normalized).stem
    characters: list[str] = []
    unsafe = set('<>:"/\\|?*')
    for character in normalized:
        category = unicodedata.category(character)
        if category in {"Cc", "Cf"}:
            continue
        if character in unsafe or character.isspace():
            characters.append("-")
        elif category.startswith(("L", "N", "M")) or character in {"-", "_", "."}:
            characters.append(character)
        else:
            characters.append("-")
    candidate = re.sub(r"-+", "-", "".join(characters)).strip(" .-")
    if not candidate:
        candidate = "subtitle"
    limited: list[str] = []
    byte_count = 0
    for character in candidate:
        encoded_length = len(character.encode("utf-8"))
        if len(limited) >= 80 or byte_count + encoded_length > 180:
            break
        limited.append(character)
        byte_count += encoded_length
    result = "".join(limited).strip(" .-")
    return result or "subtitle"


def _temporary_path(target: Path, kind: str) -> Path:
    return target.parent / f".{target.name}.wechat-{kind}-{uuid.uuid4().hex}"


def _fsync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_path(path, "tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def _same_inode(first: Path, second: Path) -> bool:
    try:
        first_stat = first.stat()
        second_stat = second.stat()
    except OSError:
        return False
    return (first_stat.st_dev, first_stat.st_ino) == (second_stat.st_dev, second_stat.st_ino)


def install_file_no_overwrite(
    source: Path,
    target: Path,
    validator: Callable[[Path], Any],
) -> Any:
    """复制、复验并以本次调用拥有的保留文件原子安装。"""

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        raise PackageError("TARGET_EXISTS", f"目标已存在，拒绝覆盖：{target}")
    temporary = _temporary_path(target, "tmp")
    reserve = _temporary_path(target, "reserve")
    target_reserved = False
    try:
        with source.open("rb") as input_stream, temporary.open("xb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        validation_result = validator(temporary)

        with reserve.open("xb") as reserve_stream:
            reserve_stream.flush()
            os.fsync(reserve_stream.fileno())
        try:
            os.link(reserve, target)
        except FileExistsError as exc:
            raise PackageError("TARGET_EXISTS", f"目标已存在，拒绝覆盖：{target}") from exc
        target_reserved = True
        os.replace(temporary, target)
        target_reserved = False
        _fsync_directory(target.parent)
        return validation_result
    finally:
        if target_reserved and _same_inode(target, reserve):
            try:
                target.unlink()
            except FileNotFoundError:
                pass
        for owned_path in (temporary, reserve):
            try:
                owned_path.unlink()
            except FileNotFoundError:
                pass


def json_text(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_internal(path: Path) -> bool:
    return INTERNAL_RE.fullmatch(path.name) is not None


def collect_files(package: Path) -> list[str]:
    files: list[str] = []
    for path in package.rglob("*"):
        if _is_internal(path):
            continue
        if path.is_file() or path.is_symlink():
            files.append(path.relative_to(package).as_posix())
    if "manifest.json" not in files:
        files.append("manifest.json")
    return sorted(set(files))


def _validate_error_objects(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, dict)
        and set(item) == {"stage", "code", "message"}
        and all(isinstance(item[key], str) for key in ("stage", "code", "message"))
        for item in value
    )


def load_manifest(package: Path) -> dict[str, Any]:
    package = package.resolve()
    if not package.is_dir() or package.is_symlink():
        raise PackageError("PACKAGE_INVALID", f"文章包目录无效：{package}")
    manifest_path = package / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackageError("PACKAGE_INVALID", f"无法读取 manifest.json：{exc}") from exc
    required = {
        "schema_version",
        "status",
        "source_file",
        "article_source_file",
        "package_version",
        "mode",
        "title",
        "body_character_count",
        "expected_body_image_count",
        "article_sha256",
        "illustration_plan",
        "files",
        "prompts",
        "images",
        "errors",
    }
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise PackageError("PACKAGE_INVALID", "manifest.json 字段不符合 schema")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise PackageError("PACKAGE_INVALID", "manifest.json schema_version 不受支持")
    if manifest["status"] not in PACKAGE_STATUSES:
        raise PackageError("PACKAGE_INVALID", "manifest.json package 状态非法")
    if not isinstance(manifest["source_file"], str) or not manifest["source_file"]:
        raise PackageError("PACKAGE_INVALID", "manifest.json source_file 非法")
    if not Path(manifest["source_file"]).is_absolute():
        raise PackageError("PACKAGE_INVALID", "manifest.json source_file 必须是绝对路径")
    if (
        not isinstance(manifest["article_source_file"], str)
        or not manifest["article_source_file"]
        or not Path(manifest["article_source_file"]).is_absolute()
    ):
        raise PackageError("PACKAGE_INVALID", "manifest.json article_source_file 必须是绝对路径")
    if not isinstance(manifest["package_version"], int) or manifest["package_version"] < 1:
        raise PackageError("PACKAGE_INVALID", "manifest.json package_version 非法")
    base = sanitize_stem(Path(manifest["source_file"]).name)
    expected_name = base if manifest["package_version"] == 1 else f"{base}-v{manifest['package_version']}"
    if package.name != expected_name:
        raise PackageError("PACKAGE_INVALID", "目录名与 package_version 不一致")
    if manifest["mode"] not in PACKAGE_MODES:
        raise PackageError("PACKAGE_INVALID", "manifest.json mode 非法")
    if not isinstance(manifest["title"], str) or not manifest["title"].strip():
        raise PackageError("PACKAGE_INVALID", "manifest.json title 非法")
    if not isinstance(manifest["body_character_count"], int) or manifest["body_character_count"] < 0:
        raise PackageError("PACKAGE_INVALID", "manifest.json body_character_count 非法")
    if not isinstance(manifest["files"], list) or not all(isinstance(item, str) for item in manifest["files"]):
        raise PackageError("PACKAGE_INVALID", "manifest.json files 非法")
    if manifest["files"] != sorted(set(manifest["files"])):
        raise PackageError("PACKAGE_INVALID", "manifest.json files 必须稳定排序且无重复")
    prompts = manifest["prompts"]
    if (
        not isinstance(prompts, dict)
        or set(prompts) != {"file", "status", "sha256", "roles"}
        or prompts.get("file") != "image-prompts.md"
        or prompts.get("status") not in PROMPT_STATUSES
        or not isinstance(prompts.get("roles"), list)
        or not all(isinstance(role, str) for role in prompts.get("roles", []))
    ):
        raise PackageError("PACKAGE_INVALID", "manifest.json prompts 非法")
    if prompts["sha256"] is not None and (
        not isinstance(prompts["sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", prompts["sha256"]) is None
    ):
        raise PackageError("PACKAGE_INVALID", "manifest.json prompts.sha256 非法")
    if not isinstance(manifest["expected_body_image_count"], int) or not 0 <= manifest["expected_body_image_count"] <= 4:
        raise PackageError("PACKAGE_INVALID", "manifest.json expected_body_image_count 非法")
    plan = manifest["illustration_plan"]
    if (
        not isinstance(plan, dict)
        or set(plan) != {"file", "sha256", "image_count"}
        or not isinstance(plan.get("image_count"), int)
        or not 0 <= plan["image_count"] <= 4
    ):
        raise PackageError("PACKAGE_INVALID", "manifest.json illustration_plan 非法")
    if plan["file"] is None:
        if plan["sha256"] is not None or plan["image_count"] != 0:
            raise PackageError("PACKAGE_INVALID", "manifest.json illustration_plan 空配置非法")
    elif (
        plan["file"] != ILLUSTRATION_PLAN_FILE
        or not isinstance(plan["sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", plan["sha256"]) is None
    ):
        raise PackageError("PACKAGE_INVALID", "manifest.json illustration_plan 文件配置非法")
    if plan["image_count"] != manifest["expected_body_image_count"]:
        raise PackageError("PACKAGE_INVALID", "manifest.json illustration_plan 图片数量不一致")
    if manifest["mode"] == "cover-only" and manifest["expected_body_image_count"] != 0:
        raise PackageError("PACKAGE_INVALID", "cover-only 模式不得包含正文图片")
    if manifest["mode"] == "body-images" and manifest["expected_body_image_count"] < 1:
        raise PackageError("PACKAGE_INVALID", "body-images 模式必须包含正文图片计划")
    images = manifest["images"]
    if not isinstance(images, list) or len(images) != manifest["expected_body_image_count"] + 1:
        raise PackageError("PACKAGE_INVALID", "manifest.json images 数量非法")
    expected_files = ["cover.png"] + [
        f"images/body-{index:02d}.png"
        for index in range(1, manifest["expected_body_image_count"] + 1)
    ]
    for index, (item, expected_file) in enumerate(zip(images, expected_files)):
        required_image_keys = {
            "file",
            "role",
            "purpose",
            "section",
            "insert_after_paragraph",
            "status",
            "size_bytes",
            "sha256",
            "width",
            "height",
        }
        if not isinstance(item, dict) or set(item) != required_image_keys:
            raise PackageError("PACKAGE_INVALID", "manifest.json image 字段非法")
        if item["file"] != expected_file or item["status"] not in IMAGE_STATUSES:
            raise PackageError("PACKAGE_INVALID", "manifest.json image 路径或状态非法")
        expected_role = "cover" if index == 0 else "body"
        if item["role"] != expected_role:
            raise PackageError("PACKAGE_INVALID", "manifest.json image 角色非法")
        if not isinstance(item["purpose"], str) or not item["purpose"].strip():
            raise PackageError("PACKAGE_INVALID", "manifest.json image purpose 非法")
        if index == 0:
            if item["section"] is not None or item["insert_after_paragraph"] is not None:
                raise PackageError("PACKAGE_INVALID", "manifest.json cover 位置字段非法")
        elif (
            not isinstance(item["section"], str)
            or not item["section"].strip()
            or not isinstance(item["insert_after_paragraph"], int)
            or item["insert_after_paragraph"] < 1
        ):
            raise PackageError("PACKAGE_INVALID", "manifest.json body 位置字段非法")
        for numeric_key in ("size_bytes", "width", "height"):
            if item[numeric_key] is not None and (
                not isinstance(item[numeric_key], int) or item[numeric_key] <= 0
            ):
                raise PackageError("PACKAGE_INVALID", f"manifest.json image {numeric_key} 非法")
        if item["sha256"] is not None and (
            not isinstance(item["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None
        ):
            raise PackageError("PACKAGE_INVALID", "manifest.json image sha256 非法")
    if not _validate_error_objects(manifest["errors"]):
        raise PackageError("PACKAGE_INVALID", "manifest.json errors 非法")
    if not isinstance(manifest["article_sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", manifest["article_sha256"]) is None:
        raise PackageError("PACKAGE_INVALID", "manifest.json article_sha256 非法")
    if manifest["status"] == "complete" and manifest["errors"]:
        raise PackageError("PACKAGE_INVALID", "complete manifest 的 errors 必须为空")
    return manifest


def ensure_incomplete(manifest: dict[str, Any]) -> None:
    if manifest["status"] == "complete":
        raise PackageError("PACKAGE_COMPLETE", "complete 文章包永久只读")


def parse_prompts(text: str, expected_body_count: int) -> list[str]:
    current_role: str | None = None
    content: dict[str, list[str]] = {}
    roles: list[str] = []
    for line_number, line in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1):
        heading = PROMPT_HEADING_RE.fullmatch(line)
        if heading:
            role = heading.group(1)
            if role in content:
                raise PackageError("PROMPTS_INVALID", f"第 {line_number} 行提示词角色重复：{role}")
            roles.append(role)
            content[role] = []
            current_role = role
            continue
        if line.startswith("## "):
            raise PackageError("PROMPTS_INVALID", f"第 {line_number} 行包含未知提示词角色")
        if current_role is None:
            if line.strip():
                raise PackageError("PROMPTS_INVALID", f"第 {line_number} 行位于提示词角色之外")
        else:
            content[current_role].append(line)
    expected_roles = ["cover"] + [f"body-{index:02d}" for index in range(1, expected_body_count + 1)]
    if roles != expected_roles:
        raise PackageError("PROMPTS_INVALID", f"提示词角色必须依次为：{', '.join(expected_roles)}")
    for role in expected_roles:
        if not "\n".join(content[role]).strip():
            raise PackageError("PROMPTS_INVALID", f"提示词内容不能为空：{role}")
    return roles


def _manifest_images(illustrations: tuple[ImagePlacement, ...]) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = [
        {
            "file": "cover.png",
            "role": "cover",
            "purpose": "公众号封面",
            "section": None,
            "insert_after_paragraph": None,
            "status": "missing",
            "size_bytes": None,
            "sha256": None,
            "width": None,
            "height": None,
        }
    ]
    for placement in illustrations:
        images.append(
            {
                "file": placement.file,
                "role": "body",
                "purpose": placement.purpose,
                "section": placement.section,
                "insert_after_paragraph": placement.insert_after_paragraph,
                "status": "missing",
                "size_bytes": None,
                "sha256": None,
                "width": None,
                "height": None,
            }
        )
    return images


def _image_metadata(item: dict[str, Any], status: str, info: PngInfo | None = None) -> None:
    item["status"] = status
    item["size_bytes"] = info.size_bytes if info else None
    item["sha256"] = info.sha256 if info else None
    item["width"] = info.width if info else None
    item["height"] = info.height if info else None


def _manifest_matches_snapshot(
    manifest: dict[str, Any],
    analysis: StructureAnalysis,
    illustrations: tuple[ImagePlacement, ...],
) -> bool:
    if (
        manifest["title"] != analysis.title
        or manifest["body_character_count"] != analysis.body_character_count
        or manifest["expected_body_image_count"] != len(illustrations)
    ):
        return False
    expected = _manifest_images(illustrations)
    for actual, wanted in zip(manifest["images"], expected):
        for key in ("file", "role", "purpose", "section", "insert_after_paragraph"):
            if actual[key] != wanted[key]:
                return False
    return True


def _scan_package_assets(package: Path, expected_images: set[str]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for path in package.rglob("*"):
        relative = path.relative_to(package).as_posix()
        if _is_internal(path):
            errors.append(error("package", "INTERNAL_TEMP_PRESENT", f"文章包存在内部临时文件：{relative}"))
        if (path.is_file() or path.is_symlink()) and path.suffix.lower() == ".png" and relative not in expected_images:
            errors.append(error("images", "EXTRA_IMAGE_ASSET", f"文章包存在未记录图片：{relative}"))
    return errors


def collect_current_state(
    package: Path,
    manifest: dict[str, Any],
) -> CurrentState:
    """重新生成当前阻塞原因；不保留历史错误。"""

    errors: list[dict[str, str]] = []
    article_path = package / "article.md"
    try:
        article_hash = sha256_file(article_path)
    except (OSError, PngValidationError) as exc:
        errors.append(error("article", "PACKAGE_INVALID", f"无法读取 article.md：{exc}"))
        manifest["errors"] = sort_errors(errors)
        manifest["files"] = collect_files(package)
        return CurrentState(None, (), manifest["errors"])
    if article_hash != manifest["article_sha256"]:
        errors.append(
            error(
                "article",
                "ARTICLE_HASH_MISMATCH",
                "article.md 已在初始化后发生变化，请重新运行 init。",
            )
        )
        manifest["errors"] = sort_errors(errors)
        manifest["files"] = collect_files(package)
        return CurrentState(None, (), manifest["errors"])

    try:
        article_text = article_path.read_text(encoding="utf-8")
        analysis = parse_and_validate(article_text)
    except (OSError, UnicodeError, MarkdownValidationError) as exc:
        errors.append(error("markdown", "MARKDOWN_INVALID", str(exc)))
        manifest["errors"] = sort_errors(errors)
        manifest["files"] = collect_files(package)
        return CurrentState(None, (), manifest["errors"])

    illustrations: tuple[ImagePlacement, ...] = ()
    plan_meta = manifest["illustration_plan"]
    if plan_meta["file"] is not None:
        plan_path = package / ILLUSTRATION_PLAN_FILE
        try:
            if plan_path.is_symlink() or not plan_path.is_file():
                raise IllustrationPlanError("illustration-plan.json 不是普通文件")
            plan_bytes = plan_path.read_bytes()
            if sha256_bytes(plan_bytes) != plan_meta["sha256"]:
                errors.append(
                    error(
                        "illustrations",
                        "ILLUSTRATION_PLAN_HASH_MISMATCH",
                        "illustration-plan.json 已在初始化后发生变化，请创建新的发布包。",
                    )
                )
            else:
                plan_text = plan_bytes.decode("utf-8")
                illustrations = parse_illustration_plan(
                    plan_text,
                    analysis,
                    require_images=manifest["mode"] == "body-images",
                ).images
                if manifest["mode"] == "cover-only" and illustrations:
                    raise IllustrationPlanError("cover-only 模式的插图计划必须为空")
        except (OSError, UnicodeError, IllustrationPlanError) as exc:
            errors.append(error("illustrations", "ILLUSTRATION_PLAN_INVALID", str(exc)))
    elif manifest["mode"] == "body-images":
        errors.append(
            error("illustrations", "ILLUSTRATION_PLAN_INVALID", "body-images 模式缺少 illustration-plan.json")
        )

    if not _manifest_matches_snapshot(manifest, analysis, illustrations):
        errors.append(error("package", "PACKAGE_INVALID", "manifest 推导字段与冻结快照不一致"))

    prompts_path = package / "image-prompts.md"
    if not prompts_path.exists():
        manifest["prompts"] = {
            "file": "image-prompts.md",
            "status": "missing",
            "sha256": None,
            "roles": [],
        }
        errors.append(error("prompts", "PROMPTS_MISSING", "缺少 image-prompts.md"))
    elif prompts_path.is_symlink() or not prompts_path.is_file():
        manifest["prompts"]["status"] = "invalid"
        manifest["prompts"]["sha256"] = None
        manifest["prompts"]["roles"] = []
        errors.append(error("prompts", "PROMPTS_INVALID", "image-prompts.md 不是普通文件"))
    else:
        try:
            prompt_bytes = prompts_path.read_bytes()
            prompt_text = prompt_bytes.decode("utf-8")
            roles = parse_prompts(prompt_text, manifest["expected_body_image_count"])
            manifest["prompts"] = {
                "file": "image-prompts.md",
                "status": "ready",
                "sha256": sha256_bytes(prompt_bytes),
                "roles": roles,
            }
        except (OSError, UnicodeError, PackageError) as exc:
            manifest["prompts"]["status"] = "invalid"
            manifest["prompts"]["sha256"] = None
            manifest["prompts"]["roles"] = []
            errors.append(error("prompts", "PROMPTS_INVALID", str(exc)))

    cover_item = manifest["images"][0]
    cover_path = package / "cover.png"
    if not cover_path.exists():
        _image_metadata(cover_item, "missing")
        errors.append(error("images", "IMAGE_MISSING", "缺少封面图片 cover.png"))
    else:
        try:
            cover_info = validate_png_file(cover_path)
            if cover_info.width / cover_info.height < 1.8:
                _image_metadata(cover_item, "invalid", cover_info)
                errors.append(error("images", "COVER_ASPECT_RATIO", "封面宽高比必须至少为 1.8:1"))
            else:
                _image_metadata(cover_item, "ready", cover_info)
        except PngValidationError as exc:
            _image_metadata(cover_item, "invalid")
            errors.append(error("images", "IMAGE_INVALID", f"封面图片无效：{exc}"))

    body_infos, resource_issues = validate_article_resources(illustrations, package)
    for item in manifest["images"][1:]:
        info = body_infos.get(item["file"])
        if info is not None:
            _image_metadata(item, "ready", info)
        else:
            matching = next((issue for issue in resource_issues if issue.file == item["file"]), None)
            _image_metadata(item, "missing" if matching and matching.code == "IMAGE_MISSING" else "invalid")
    for issue in resource_issues:
        errors.append(error("images", issue.code, issue.message))

    expected_assets = {item["file"] for item in manifest["images"]}
    errors.extend(_scan_package_assets(package, expected_assets))
    manifest["files"] = collect_files(package)
    manifest["errors"] = sort_errors(errors)
    return CurrentState(analysis, illustrations, manifest["errors"])


def render_publish_guide(manifest: dict[str, Any]) -> str:
    complete = manifest["status"] == "complete"
    lines = [
        "# 公众号发布指南",
        "",
        f"当前状态：`{manifest['status']}`",
        f"发布模式：`{manifest['mode']}`",
        f"源稿位置：`{manifest['article_source_file']}`",
        "",
    ]
    if complete:
        lines.extend(["文章包校验完成。请按以下步骤发布。", ""])
    else:
        lines.extend(["文章包尚未完成，不得作为成品发布。", ""])
    lines.extend(
        [
            "## 标题",
            "",
            f"将 `title.txt` 中的标题复制到公众号标题栏：{manifest['title']}",
            "",
            "## 封面",
            "",
        ]
    )
    cover = manifest["images"][0]
    if cover["status"] == "ready":
        ratio = cover["width"] / cover["height"]
        lines.append(
            f"上传 `cover.png`。当前尺寸为 {cover['width']}×{cover['height']}，宽高比 {ratio:.2f}:1；建议接近 2.35:1。"
        )
    else:
        lines.append("封面尚未通过校验；必须使用真实 `cover.png`，宽高比至少为 1.8:1。")
    lines.extend(["", "## HTML", ""])
    if complete:
        lines.append("在浏览器打开 `wechat-body.html`，复制渲染后的正文并粘贴到公众号编辑器。")
    else:
        lines.append("`wechat-body.html` 尚不可作为完成稿使用；请先修复下方阻塞问题并重新 finalize。")
    if manifest["expected_body_image_count"]:
        lines.extend(
            [
                "",
                "粘贴后检查所有二级标题是否稳定放大、加粗，并逐张核对正文图片。若本地图片未随 HTML 复制，请按下列位置手动插入。",
                "",
                "## 正文图片位置",
                "",
            ]
        )
        for item in manifest["images"][1:]:
            lines.append(
                f"- `{item['file']}`：{item['purpose']}；章节“{item['section']}”；该章节第 {item['insert_after_paragraph']} 个普通段落之后。"
            )
    else:
        lines.extend(["", "粘贴后检查所有二级标题是否稳定放大、加粗。"])
    if manifest["errors"]:
        lines.extend(["", "## 当前阻塞问题", ""])
        for item in manifest["errors"]:
            lines.append(f"- `{item['stage']}/{item['code']}`：{item['message']}")
    return "\n".join(lines) + "\n"


def write_package_state(package: Path, manifest: dict[str, Any]) -> None:
    manifest["files"] = collect_files(package)
    guide = render_publish_guide(manifest)
    atomic_write_text(package / "publish-guide.md", guide)
    manifest["files"] = collect_files(package)
    atomic_write_text(package / "manifest.json", json_text(manifest))


def create_package(
    source: Path,
    article: Path,
    output_root: Path,
    *,
    mode: str = "cover-only",
    illustration_plan: Path | None = None,
    require_source: bool = True,
) -> Path:
    source = source.resolve()
    article = article.resolve()
    if require_source and (not source.is_file() or source.is_symlink()):
        raise PackageError("PACKAGE_INVALID", f"来源字幕不可用：{source}")
    if mode not in PACKAGE_MODES:
        raise PackageError("PACKAGE_INVALID", f"不支持的发布模式：{mode}")
    if not article.is_file() or article.is_symlink():
        raise PackageError("PACKAGE_INVALID", f"文章源稿不可用：{article}")
    try:
        article_bytes = article.read_bytes()
        article_text = article_bytes.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise PackageError("PACKAGE_INVALID", f"无法读取 UTF-8 article.md：{exc}") from exc
    try:
        analysis = parse_and_validate(article_text)
    except MarkdownValidationError as exc:
        first_code = exc.issues[0].code if exc.issues else "MARKDOWN_INVALID"
        raise PackageError(first_code, str(exc)) from exc

    plan_bytes: bytes | None = None
    illustrations: tuple[ImagePlacement, ...] = ()
    if illustration_plan is not None:
        illustration_plan = illustration_plan.resolve()
        if not illustration_plan.is_file() or illustration_plan.is_symlink():
            raise PackageError("ILLUSTRATION_PLAN_INVALID", "插图计划不是普通文件")
        try:
            plan_bytes = illustration_plan.read_bytes()
            plan_text = plan_bytes.decode("utf-8")
            illustrations = parse_illustration_plan(
                plan_text,
                analysis,
                require_images=mode == "body-images",
            ).images
        except (OSError, UnicodeError, IllustrationPlanError) as exc:
            raise PackageError("ILLUSTRATION_PLAN_INVALID", str(exc)) from exc
    elif mode == "body-images":
        raise PackageError(
            "ILLUSTRATION_PLAN_INVALID",
            "body-images 模式必须通过 --illustration-plan 提供插图计划",
        )
    if mode == "cover-only" and illustrations:
        raise PackageError("ILLUSTRATION_PLAN_INVALID", "cover-only 模式的插图计划必须为空")

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    base = sanitize_stem(source.name)
    package: Path | None = None
    package_version = 1
    while package is None:
        name = base if package_version == 1 else f"{base}-v{package_version}"
        candidate = output_root / name
        try:
            candidate.mkdir()
            package = candidate
        except FileExistsError:
            package_version += 1

    created = package
    try:
        (created / "images").mkdir()
        atomic_write_bytes(created / "article.md", article_bytes)
        if plan_bytes is not None:
            atomic_write_bytes(created / ILLUSTRATION_PLAN_FILE, plan_bytes)
        atomic_write_text(created / "title.txt", analysis.title + "\n")
        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "status": "incomplete",
            "source_file": str(source),
            "article_source_file": str(article),
            "package_version": package_version,
            "mode": mode,
            "title": analysis.title,
            "body_character_count": analysis.body_character_count,
            "expected_body_image_count": len(illustrations),
            "article_sha256": sha256_bytes(article_bytes),
            "illustration_plan": {
                "file": ILLUSTRATION_PLAN_FILE if plan_bytes is not None else None,
                "sha256": sha256_bytes(plan_bytes) if plan_bytes is not None else None,
                "image_count": len(illustrations),
            },
            "files": [],
            "prompts": {
                "file": "image-prompts.md",
                "status": "missing",
                "sha256": None,
                "roles": [],
            },
            "images": _manifest_images(illustrations),
            "errors": [],
        }
        state = collect_current_state(created, manifest)
        manifest["errors"] = state.errors
        write_package_state(created, manifest)
        return created.resolve()
    except Exception:
        for path in sorted(created.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            try:
                if path.is_dir() and not path.is_symlink():
                    path.rmdir()
                else:
                    path.unlink()
            except FileNotFoundError:
                pass
        try:
            created.rmdir()
        except FileNotFoundError:
            pass
        raise


def _load_rebuild_metadata(package: Path) -> tuple[dict[str, Any], Path]:
    """只读加载新旧文章包中重建所需的最小可信信息。"""

    package = package.resolve()
    if not package.is_dir() or package.is_symlink():
        raise PackageError("PACKAGE_INVALID", f"文章包目录无效：{package}")
    try:
        raw = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackageError("PACKAGE_INVALID", f"无法读取旧 manifest.json：{exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") not in {1, SCHEMA_VERSION}:
        raise PackageError("PACKAGE_INVALID", "旧文章包 schema_version 不受支持")
    if raw.get("schema_version") == SCHEMA_VERSION:
        raw = load_manifest(package)
    else:
        source_file = raw.get("source_file")
        expected_count = raw.get("expected_body_image_count")
        if (
            not isinstance(source_file, str)
            or not source_file
            or not Path(source_file).is_absolute()
            or not isinstance(expected_count, int)
            or not 0 <= expected_count <= 4
        ):
            raise PackageError("PACKAGE_INVALID", "旧文章包缺少可用于 rebuild 的来源或模式信息")
    article_snapshot = package / "article.md"
    if article_snapshot.is_symlink() or not article_snapshot.is_file():
        raise PackageError("PACKAGE_INVALID", "旧文章包缺少可读取的 article.md 快照")
    return raw, article_snapshot


def rebuild_package(
    package: Path,
    *,
    article: Path | None = None,
    output_root: Path | None = None,
    mode: str | None = None,
    illustration_plan: Path | None = None,
) -> Path:
    """从旧快照或新源稿创建新版本；绝不修改旧文章包。"""

    old_package = package.resolve()
    manifest, article_snapshot = _load_rebuild_metadata(old_package)
    selected_article = article.resolve() if article is not None else article_snapshot
    old_mode = manifest.get("mode")
    if old_mode not in PACKAGE_MODES:
        old_mode = "body-images" if manifest.get("expected_body_image_count", 0) else "cover-only"
    selected_mode = mode or old_mode
    selected_plan = illustration_plan.resolve() if illustration_plan is not None else None
    if selected_plan is None and selected_mode == "body-images":
        old_plan = old_package / ILLUSTRATION_PLAN_FILE
        if old_plan.is_file() and not old_plan.is_symlink():
            selected_plan = old_plan
        else:
            raise PackageError(
                "ILLUSTRATION_PLAN_INVALID",
                "body-images rebuild 必须提供 --illustration-plan；旧包没有独立插图计划。",
            )
    return create_package(
        Path(manifest["source_file"]),
        selected_article,
        output_root.resolve() if output_root is not None else old_package.parent,
        mode=selected_mode,
        illustration_plan=selected_plan,
        require_source=False,
    )


def set_prompts(package: Path, prompts_file: Path) -> None:
    package = package.resolve()
    manifest = load_manifest(package)
    ensure_incomplete(manifest)
    try:
        prompt_bytes = prompts_file.read_bytes()
        prompt_text = prompt_bytes.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise PackageError("PROMPTS_INVALID", f"无法读取 UTF-8 提示词文件：{exc}") from exc
    roles = parse_prompts(prompt_text, manifest["expected_body_image_count"])

    def validate_prompt_copy(path: Path) -> list[str]:
        try:
            return parse_prompts(path.read_text(encoding="utf-8"), manifest["expected_body_image_count"])
        except (OSError, UnicodeError) as exc:
            raise PackageError("PROMPTS_INVALID", f"复制后的提示词文件无效：{exc}") from exc

    installed_roles = install_file_no_overwrite(
        prompts_file.resolve(),
        package / "image-prompts.md",
        validate_prompt_copy,
    )
    manifest["prompts"] = {
        "file": "image-prompts.md",
        "status": "ready",
        "sha256": sha256_file(package / "image-prompts.md"),
        "roles": installed_roles or roles,
    }
    collect_current_state(package, manifest)
    write_package_state(package, manifest)


def add_image(package: Path, source: Path, role: str, index: int | None) -> None:
    package = package.resolve()
    manifest = load_manifest(package)
    ensure_incomplete(manifest)
    if role == "cover":
        if index is not None:
            raise PackageError("INDEX_OUT_OF_RANGE", "封面图片不能指定 --index")
        target = package / "cover.png"
    else:
        if index is None or not 1 <= index <= manifest["expected_body_image_count"]:
            raise PackageError("INDEX_OUT_OF_RANGE", "正文图片 index 超出预期范围")
        target = package / "images" / f"body-{index:02d}.png"
    if source.is_symlink():
        raise PackageError("IMAGE_INVALID", f"来源图片不能是符号链接：{source}")
    source = source.resolve()
    if not source.is_file():
        raise PackageError("IMAGE_INVALID", f"来源图片不是普通文件：{source}")
    try:
        source_info = validate_png_file(source)
    except PngValidationError as exc:
        raise PackageError("IMAGE_INVALID", str(exc)) from exc
    if role == "cover" and source_info.width / source_info.height < 1.8:
        raise PackageError("COVER_ASPECT_RATIO", "封面宽高比必须至少为 1.8:1")

    def validate_copy(path: Path) -> PngInfo:
        try:
            info = validate_png_file(path)
        except PngValidationError as exc:
            raise PackageError("IMAGE_INVALID", str(exc)) from exc
        if role == "cover" and info.width / info.height < 1.8:
            raise PackageError("COVER_ASPECT_RATIO", "封面宽高比必须至少为 1.8:1")
        return info

    install_file_no_overwrite(source, target, validate_copy)
    collect_current_state(package, manifest)
    write_package_state(package, manifest)


def finalize_package(package: Path) -> None:
    package = package.resolve()
    manifest = load_manifest(package)
    ensure_incomplete(manifest)
    state = collect_current_state(package, manifest)
    if state.errors:
        manifest["status"] = "incomplete"
        write_package_state(package, manifest)
        first = state.errors[0]
        raise PackageError(first["code"], first["message"])
    assert state.analysis is not None
    try:
        html_text = render_html(state.analysis, state.illustrations)
        atomic_write_text(package / "wechat-body.html", html_text)
    except Exception as exc:
        manifest["status"] = "incomplete"
        manifest["errors"] = [error("render", "RENDER_FAILED", f"HTML 渲染失败：{exc}")]
        write_package_state(package, manifest)
        raise PackageError("RENDER_FAILED", str(exc)) from exc

    post_render_state = collect_current_state(package, manifest)
    if post_render_state.errors:
        manifest["status"] = "incomplete"
        write_package_state(package, manifest)
        first = post_render_state.errors[0]
        raise PackageError(first["code"], first["message"])
    manifest["errors"] = []
    manifest["status"] = "complete"
    manifest["files"] = collect_files(package)
    write_package_state(package, manifest)


def record_failure(package: Path, reason: str) -> None:
    package = package.resolve()
    manifest = load_manifest(package)
    ensure_incomplete(manifest)
    collect_current_state(package, manifest)
    manifest["errors"] = sort_errors(
        manifest["errors"]
        + [error("image_generation", "IMAGE_GENERATION_FAILED", reason.strip() or "图片生成失败")]
    )
    manifest["status"] = "incomplete"
    write_package_state(package, manifest)
    raise PackageError("IMAGE_GENERATION_FAILED", reason.strip() or "图片生成失败")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="创建新的 incomplete 文章包")
    init_parser.add_argument("--source", required=True, type=Path)
    init_parser.add_argument("--article", required=True, type=Path)
    init_parser.add_argument("--output-root", required=True, type=Path)
    init_parser.add_argument(
        "--mode",
        choices=("cover-only", "body-images"),
        default="cover-only",
        help="发布包模式；默认 cover-only",
    )
    init_parser.add_argument("--illustration-plan", type=Path)

    rebuild_parser = subparsers.add_parser("rebuild", help="从旧快照或新源稿创建新版本")
    rebuild_parser.add_argument("package", type=Path)
    rebuild_parser.add_argument("--article", type=Path, help="可选的新可编辑源稿")
    rebuild_parser.add_argument("--output-root", type=Path)
    rebuild_parser.add_argument("--mode", choices=("cover-only", "body-images"))
    rebuild_parser.add_argument("--illustration-plan", type=Path)

    prompts_parser = subparsers.add_parser("set-prompts", help="安装图片提示词")
    prompts_parser.add_argument("package", type=Path)
    prompts_parser.add_argument("prompts_file", type=Path)

    image_parser = subparsers.add_parser("add-image", help="安装真实 PNG 图片")
    image_parser.add_argument("package", type=Path)
    image_parser.add_argument("source", type=Path)
    image_parser.add_argument("--role", required=True, choices=("cover", "body"))
    image_parser.add_argument("--index", type=int)

    finalize_parser = subparsers.add_parser("finalize", help="校验并完成文章包")
    finalize_parser.add_argument("package", type=Path)

    fail_parser = subparsers.add_parser("fail", help="记录图片生成失败")
    fail_parser.add_argument("package", type=Path)
    fail_parser.add_argument("--reason", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            package = create_package(
                args.source,
                args.article,
                args.output_root,
                mode=args.mode,
                illustration_plan=args.illustration_plan,
            )
            print(package)
        elif args.command == "rebuild":
            package = rebuild_package(
                args.package,
                article=args.article,
                output_root=args.output_root,
                mode=args.mode,
                illustration_plan=args.illustration_plan,
            )
            print(package)
        elif args.command == "set-prompts":
            set_prompts(args.package, args.prompts_file)
        elif args.command == "add-image":
            add_image(args.package, args.source, args.role, args.index)
        elif args.command == "finalize":
            finalize_package(args.package)
        elif args.command == "fail":
            record_failure(args.package, args.reason)
        return 0
    except PackageError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"PACKAGE_INVALID: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
