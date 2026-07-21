"""仓库级通用校验编排。"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from . import codes
from .discovery import discover_skill_directories
from .markdown import relative_path
from .models import Issue, RepositoryValidation, SkillContext, ValidationResult
from .security import scan_sensitive_information
from .validator import validate_skill


IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".git", ".hg", ".svn", ".idea", ".vscode", ".mypy_cache", ".pytest_cache",
        ".ruff_cache", ".tox", ".nox", ".venv", "venv", "env", "dist", "build", "node_modules",
    }
)


@dataclass(frozen=True, slots=True)
class IgnoreRule:
    pattern: str
    negated: bool
    directory_only: bool
    anchored: bool


def load_gitignore_rules(root: Path) -> tuple[IgnoreRule, ...]:
    try:
        lines = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ()
    rules: list[IgnoreRule] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        line = line[1:] if negated else line
        anchored = line.startswith("/")
        line = line[1:] if anchored else line
        directory_only = line.endswith("/")
        line = line[:-1] if directory_only else line
        if line:
            rules.append(IgnoreRule(line, negated, directory_only, anchored))
    return tuple(rules)


def _rule_matches(rule: IgnoreRule, relative: Path, *, is_directory: bool) -> bool:
    if rule.directory_only and not is_directory:
        return False
    path_text = relative.as_posix()
    if rule.anchored or "/" in rule.pattern:
        return fnmatch.fnmatchcase(path_text, rule.pattern)
    return any(fnmatch.fnmatchcase(part, rule.pattern) for part in relative.parts)


def is_gitignored_generated_path(path: Path, root: Path, rules: Sequence[IgnoreRule]) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    ignored = False
    for rule in rules:
        if _rule_matches(rule, relative, is_directory=path.is_dir()):
            ignored = not rule.negated
    return ignored


def validate_forbidden_paths(root: Path) -> ValidationResult:
    """发现系统文件、未忽略缓存和临时编辑器文件。"""

    rules = load_gitignore_rules(root)
    errors: list[Issue] = []
    for current_root, directory_names, file_names in os.walk(root):
        directory_names[:] = sorted(name for name in directory_names if name not in IGNORED_DIRECTORY_NAMES)
        current_path = Path(current_root)
        if "__pycache__" in directory_names:
            cache_path = current_path / "__pycache__"
            if not is_gitignored_generated_path(cache_path, root, rules):
                errors.append(
                    Issue(
                        codes.PATH_UNIGNORED_CACHE,
                        relative_path(cache_path, root),
                        "不允许存在未被 .gitignore 排除的 __pycache__ 目录",
                    )
                )
            directory_names.remove("__pycache__")
        for file_name in sorted(file_names):
            path = current_path / file_name
            if file_name == ".DS_Store":
                errors.append(Issue(codes.PATH_DS_STORE, relative_path(path, root), "不允许存在 .DS_Store"))
            elif file_name.endswith(".pyc") and not is_gitignored_generated_path(path, root, rules):
                errors.append(
                    Issue(
                        codes.PATH_UNIGNORED_CACHE,
                        relative_path(path, root),
                        "不允许存在未被 .gitignore 排除的 .pyc 文件",
                    )
                )
            elif file_name.endswith(("~", ".swp", ".swo", ".tmp")) or file_name.startswith(".#"):
                errors.append(
                    Issue(codes.PATH_TEMPORARY_FILE, relative_path(path, root), "不允许存在临时编辑器文件")
                )
    return ValidationResult(errors=tuple(errors))


def validate_repository_common(root: Path) -> RepositoryValidation:
    """只执行通用规则，不发现或执行 Skill 插件。"""

    root = root.expanduser().resolve()
    discovery = discover_skill_directories(root)
    results: list[ValidationResult] = [discovery.result]
    for skill_dir in discovery.skill_dirs:
        results.append(validate_skill(SkillContext(root, skill_dir, skill_dir.name)))
    if root.is_dir():
        results.extend((validate_forbidden_paths(root), scan_sensitive_information(root)))
    return RepositoryValidation(len(discovery.skill_dirs), 0, ValidationResult.merge(*results))
