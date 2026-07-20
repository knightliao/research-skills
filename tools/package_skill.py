#!/usr/bin/env python3
"""校验并打包仓库中的单个 Agent Skill。"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Sequence


SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".idea",
        ".vscode",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    }
)
IGNORED_FILE_NAMES = frozenset({".DS_Store"})
IGNORED_FILE_SUFFIXES = frozenset({".pyc", ".pyo"})
TEMPORARY_FILE_SUFFIXES = ("~", ".swp", ".swo", ".tmp")


class PackageError(Exception):
    """表示可直接展示给用户的打包失败。"""


@dataclass(frozen=True, slots=True)
class PackageResult:
    """一次成功打包的结构化结果。"""

    skill_name: str
    output_path: Path
    file_count: int
    size_bytes: int
    warnings: tuple[str, ...] = ()


def load_skill_validator() -> ModuleType:
    """从同一 tools 目录加载仓库级校验器，避免复制校验规则。"""

    module_name = "_research_skills_validate_all_skills"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing

    validator_path = Path(__file__).resolve().with_name("validate_all_skills.py")
    spec = importlib.util.spec_from_file_location(module_name, validator_path)
    if spec is None or spec.loader is None:
        raise PackageError(f"无法加载 Skill 校验器：{validator_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except (OSError, ImportError, SyntaxError) as exc:
        sys.modules.pop(module_name, None)
        raise PackageError(f"加载 Skill 校验器失败：{exc}") from exc
    return module


def validate_skill_name(skill_name: str) -> None:
    """限制 Skill 名称，防止路径穿越和不可移植目录名。"""

    if not SKILL_NAME_RE.fullmatch(skill_name):
        raise PackageError("Skill 名称只能包含小写英文字母、数字和连字符")


def is_ignored_file(path: Path) -> bool:
    """判断文件是否属于缓存、系统文件或临时编辑器文件。"""

    return (
        path.name in IGNORED_FILE_NAMES
        or path.suffix.lower() in IGNORED_FILE_SUFFIXES
        or path.name.endswith(TEMPORARY_FILE_SUFFIXES)
        or path.name.startswith(".#")
    )


def validate_source_skill(skill_dir: Path, repository_root: Path) -> tuple[str, ...]:
    """复用仓库校验器检查目标 Skill，并返回非致命警告。"""

    validator = load_skill_validator()
    report = validator.ValidationReport(skill_count=1)
    validator.validate_skill(skill_dir, repository_root, report)
    validator.scan_sensitive_information(skill_dir, report)
    if report.errors:
        details = "\n".join(f"- {issue.render()}" for issue in report.errors)
        raise PackageError(f"Skill 校验失败，已停止打包：\n{details}")
    return tuple(issue.render() for issue in report.warnings)


def collect_skill_files(skill_dir: Path) -> list[Path]:
    """收集可打包文件；不遍历符号链接目录，也不包含任何符号链接文件。"""

    resolved_skill_dir = skill_dir.resolve()
    files: list[Path] = []
    for current_root, directory_names, file_names in os.walk(skill_dir, followlinks=False):
        current_path = Path(current_root)
        kept_directories: list[str] = []
        for directory_name in sorted(directory_names):
            directory_path = current_path / directory_name
            if directory_name in IGNORED_DIRECTORY_NAMES or directory_path.is_symlink():
                continue
            kept_directories.append(directory_name)
        directory_names[:] = kept_directories

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
    return sorted(files, key=lambda path: path.relative_to(skill_dir).as_posix())


def archive_name(skill_name: str, source_file: Path, skill_dir: Path) -> str:
    """生成仅含一个顶层 Skill 目录的 POSIX ZIP 路径。"""

    relative = source_file.relative_to(skill_dir)
    return PurePosixPath(skill_name, *relative.parts).as_posix()


def create_skill_archive(
    skill_name: str,
    *,
    repository_root: Path,
    output_dir: Path,
) -> PackageResult:
    """校验并原子地创建单个 Skill ZIP；不会修改源目录。"""

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

    if not output_dir.is_absolute():
        output_dir = repository_root / output_dir
    output_dir = output_dir.expanduser().resolve()
    output_path = output_dir / f"{skill_name}.zip"
    try:
        output_path.relative_to(skill_dir.resolve())
    except ValueError:
        pass
    else:
        raise PackageError("输出目录不得位于待打包的 Skill 目录内部")

    warnings = validate_source_skill(skill_dir, repository_root)
    source_files = collect_skill_files(skill_dir)
    if skill_file not in source_files:
        raise PackageError("SKILL.md 未进入待打包文件列表，已停止打包")

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=output_dir,
            prefix=f".{skill_name}-",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
        try:
            with zipfile.ZipFile(
                temporary_path,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            ) as archive:
                for source_file in source_files:
                    archive.write(
                        source_file,
                        arcname=archive_name(skill_name, source_file, skill_dir),
                    )
            os.replace(temporary_path, output_path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        size_bytes = output_path.stat().st_size
    except (
        OSError,
        RuntimeError,
        ValueError,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
    ) as exc:
        raise PackageError(f"创建 ZIP 失败：{exc}") from exc

    return PackageResult(
        skill_name=skill_name,
        output_path=output_path,
        file_count=len(source_files),
        size_bytes=size_bytes,
        warnings=warnings,
    )


def build_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器。"""

    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="校验并打包一个自包含 Agent Skill，安全覆盖已有同名 ZIP。",
        add_help=False,
    )
    parser._positionals.title = "位置参数"
    parser._optionals.title = "选项"
    parser.add_argument("-h", "--help", action="help", help="显示此帮助信息并退出")
    parser.add_argument("skill_name", nargs="?", help="要打包的 Skill 名称")
    parser.add_argument("--skill", dest="skill_option", help="要打包的 Skill 名称")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("dist"),
        help="ZIP 输出目录；相对路径按仓库根目录解析，默认为 dist",
    )
    parser.add_argument(
        "--repository",
        type=Path,
        default=default_root,
        help="仓库根目录；默认使用当前脚本所在仓库",
    )
    return parser


def select_skill_name(positional: str | None, option: str | None) -> str:
    """合并两种 CLI 写法，并拒绝含糊输入。"""

    if positional and option:
        raise PackageError("请只使用位置参数或 --skill 指定一次 Skill 名称")
    skill_name = positional or option
    if not skill_name:
        raise PackageError("缺少 Skill 名称；请使用位置参数或 --skill")
    return skill_name


def print_result(result: PackageResult) -> None:
    """打印打包结果和非致命校验警告。"""

    if result.warnings:
        print("警告：")
        for warning in result.warnings:
            print(f"- {warning}")
    print(f"Skill 名称：{result.skill_name}")
    print(f"输出路径：{result.output_path}")
    print(f"文件数量：{result.file_count}")
    print(f"ZIP 文件大小：{result.size_bytes} 字节")


def main(argv: Sequence[str] | None = None) -> int:
    """运行打包命令并返回进程退出码。"""

    args = build_parser().parse_args(argv)
    try:
        skill_name = select_skill_name(args.skill_name, args.skill_option)
        result = create_skill_archive(
            skill_name,
            repository_root=args.repository,
            output_dir=args.output_dir,
        )
    except PackageError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
