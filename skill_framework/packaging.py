"""单个自包含 Agent Skill 的通用打包实现。"""

from __future__ import annotations

import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .discovery import SKILL_NAME_RE
from .models import Issue, SkillContext, ValidationResult
from .registry import load_plugin_for_skill, run_plugin
from .security import scan_sensitive_information
from .validator import validate_skill


IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".git", ".hg", ".svn", ".idea", ".vscode", ".mypy_cache", ".pytest_cache",
        ".ruff_cache", ".tox", ".nox", "__pycache__", "build", "dist", "node_modules",
    }
)
IGNORED_FILE_NAMES = frozenset({".DS_Store"})
IGNORED_FILE_SUFFIXES = frozenset({".pyc", ".pyo"})
TEMPORARY_FILE_SUFFIXES = ("~", ".swp", ".swo", ".tmp")
FORBIDDEN_ARCHIVE_TOP_LEVEL_NAMES = frozenset(
    {"skill_framework", "plugins", "tools", "tests", ".github"}
)


class PackageError(Exception):
    """可直接展示给用户的打包失败。"""


@dataclass(frozen=True, slots=True)
class PackageResult:
    """一次成功打包的结构化结果。"""

    skill_name: str
    output_path: Path
    file_count: int
    size_bytes: int
    warnings: tuple[Issue, ...] = ()


def validate_skill_name(skill_name: str) -> None:
    if not SKILL_NAME_RE.fullmatch(skill_name):
        raise PackageError("Skill 名称只能包含小写英文字母、数字和连字符")


def is_ignored_file(path: Path) -> bool:
    return (
        path.name in IGNORED_FILE_NAMES
        or path.suffix.lower() in IGNORED_FILE_SUFFIXES
        or path.name.endswith(TEMPORARY_FILE_SUFFIXES)
        or path.name.startswith(".#")
    )


def validate_source_skill(skill_dir: Path, repository_root: Path) -> ValidationResult:
    """执行通用校验、安全扫描，并只加载目标 Skill 插件。"""

    context = SkillContext(repository_root, skill_dir, skill_dir.name)
    plugin_load = load_plugin_for_skill(repository_root / "plugins", skill_dir.name)
    results = [validate_skill(context), plugin_load.result, scan_sensitive_information(skill_dir)]
    if plugin_load.plugin is not None:
        results.append(run_plugin(plugin_load.plugin, context))
    return ValidationResult.merge(*results)


def collect_skill_files(skill_dir: Path) -> tuple[Path, ...]:
    """收集合法普通文件，不遍历或打包任何符号链接。"""

    resolved_skill_dir = skill_dir.resolve()
    files: list[Path] = []
    for current_root, directory_names, file_names in os.walk(skill_dir, followlinks=False):
        current_path = Path(current_root)
        directory_names[:] = [
            name
            for name in sorted(directory_names)
            if name not in IGNORED_DIRECTORY_NAMES and not (current_path / name).is_symlink()
        ]
        for file_name in sorted(file_names):
            path = current_path / file_name
            if path.is_symlink() or is_ignored_file(path):
                continue
            try:
                path.resolve(strict=True).relative_to(resolved_skill_dir)
            except (OSError, ValueError) as exc:
                raise PackageError(f"文件不在 Skill 目录边界内：{path}") from exc
            if path.is_file():
                files.append(path)
    return tuple(sorted(files, key=lambda path: path.relative_to(skill_dir).as_posix()))


def archive_name(skill_name: str, source_file: Path, skill_dir: Path) -> str:
    relative = source_file.relative_to(skill_dir)
    return PurePosixPath(skill_name, *relative.parts).as_posix()


def validate_skill_archive(archive_path: Path, skill_name: str) -> tuple[str, ...]:
    """验证 ZIP 的完整性、单一 Skill 边界和仓库设施隔离。"""

    validate_skill_name(skill_name)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            corrupt_member = archive.testzip()
            if corrupt_member is not None:
                raise PackageError(f"ZIP 成员损坏：{corrupt_member}")
            names = tuple(archive.namelist())
    except PackageError:
        raise
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise PackageError(f"ZIP 无法读取：{exc}") from exc

    if not names:
        raise PackageError("ZIP 不得为空")

    member_paths = tuple(PurePosixPath(name) for name in names)
    for name, member_path in zip(names, member_paths, strict=True):
        if member_path.is_absolute() or ".." in member_path.parts:
            raise PackageError(f"ZIP 成员路径不安全：{name}")
        if not member_path.parts or member_path.parts[0] != skill_name:
            raise PackageError(f"ZIP 成员不在目标 Skill 顶层目录内：{name}")
        if (
            len(member_path.parts) >= 2
            and member_path.parts[1] in FORBIDDEN_ARCHIVE_TOP_LEVEL_NAMES
        ):
            raise PackageError(
                f"ZIP 不得包含仓库设施目录：{member_path.parts[1]}"
            )

    top_levels = {member_path.parts[0] for member_path in member_paths}
    if top_levels != {skill_name}:
        raise PackageError(f"ZIP 必须只有一个名为 {skill_name} 的顶层目录")
    if f"{skill_name}/SKILL.md" not in names:
        raise PackageError("ZIP 缺少 Skill 入口文件 SKILL.md")
    return names


def package_skill(
    skill_name: str,
    *,
    repository_root: Path,
    output_dir: Path,
) -> PackageResult:
    """校验并原子创建 ZIP；失败时不创建或覆盖正式输出。"""

    validate_skill_name(skill_name)
    repository_root = repository_root.expanduser().resolve()
    if not repository_root.is_dir():
        raise PackageError(f"仓库目录不存在或不是目录：{repository_root}")
    skill_dir = repository_root / ".agents" / "skills" / skill_name
    if not skill_dir.is_dir():
        raise PackageError(f"Skill 不存在：{skill_name}")
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        raise PackageError(f"Skill 缺少入口文件：{skill_file}")

    output_dir = output_dir if output_dir.is_absolute() else repository_root / output_dir
    output_dir = output_dir.expanduser().resolve()
    output_path = output_dir / f"{skill_name}.zip"
    try:
        output_path.relative_to(skill_dir.resolve())
    except ValueError:
        pass
    else:
        raise PackageError("输出目录不得位于待打包的 Skill 目录内部")

    validation = validate_source_skill(skill_dir, repository_root)
    if validation.errors:
        details = "\n".join(f"- {issue.render()}" for issue in validation.errors)
        raise PackageError(f"Skill 校验失败，已停止打包：\n{details}")
    source_files = collect_skill_files(skill_dir)
    if skill_file not in source_files:
        raise PackageError("SKILL.md 未进入待打包文件列表，已停止打包")

    temporary_path: Path | None = None
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=output_dir,
            prefix=f".{skill_name}-",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for source_file in source_files:
                archive.write(source_file, arcname=archive_name(skill_name, source_file, skill_dir))
        validate_skill_archive(temporary_path, skill_name)
        os.replace(temporary_path, output_path)
        temporary_path = None
        size_bytes = output_path.stat().st_size
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise PackageError(f"创建 ZIP 失败：{exc}") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return PackageResult(
        skill_name,
        output_path,
        len(source_files),
        size_bytes,
        validation.warnings,
    )


# 兼容第一版库调用名称；CLI 已使用 ``package_skill``。
create_skill_archive = package_skill
