"""Skill 目录发现与名称校验。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import codes
from .models import Issue, ValidationResult


SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True, slots=True)
class SkillDiscoveryResult:
    """目录发现结果。"""

    skill_dirs: tuple[Path, ...]
    result: ValidationResult


def validate_skill_name(skill_name: str) -> ValidationResult:
    """校验可移植的 Skill 名称。"""

    if SKILL_NAME_RE.fullmatch(skill_name):
        return ValidationResult()
    return ValidationResult(
        errors=(
            Issue(
                codes.SKILL_INVALID_NAME,
                skill_name or ".",
                "Skill 名称只能包含小写英文字母、数字和连字符",
            ),
        )
    )


def discover_skill_directories(repository_root: Path) -> SkillDiscoveryResult:
    """按目录名排序发现 ``.agents/skills/*/``。"""

    root = repository_root.expanduser().resolve()
    if not root.is_dir():
        return SkillDiscoveryResult(
            (),
            ValidationResult(
                errors=(
                    Issue(codes.REPOSITORY_INVALID_ROOT, str(root), "仓库目录不存在或不是目录"),
                )
            ),
        )
    skills_root = root / ".agents" / "skills"
    if not skills_root.is_dir():
        return SkillDiscoveryResult(
            (),
            ValidationResult(
                errors=(
                    Issue(codes.SKILL_ROOT_MISSING, ".agents/skills", "缺少 Skill 根目录"),
                )
            ),
        )
    skill_dirs = tuple(sorted(path for path in skills_root.iterdir() if path.is_dir()))
    results = [validate_skill_name(path.name) for path in skill_dirs]
    if not skill_dirs:
        results.append(
            ValidationResult(
                errors=(
                    Issue(codes.SKILL_NONE_FOUND, ".agents/skills", "未发现任何 Skill 目录"),
                )
            )
        )
    return SkillDiscoveryResult(skill_dirs, ValidationResult.merge(*results))
