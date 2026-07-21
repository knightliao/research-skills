"""单个 Skill 的通用结构校验。"""

from __future__ import annotations

from pathlib import Path

from . import codes
from .markdown import read_text, relative_path, validate_frontmatter, validate_markdown_links
from .models import Issue, SkillContext, ValidationResult
from .python_checks import validate_python_scripts


OPTIONAL_SKILL_DIRECTORIES = ("references", "examples", "assets", "scripts")


def validate_skill(context: SkillContext) -> ValidationResult:
    """执行与具体 Skill 业务无关的通用校验。"""

    root = context.repository_root.resolve()
    skill_dir = context.skill_dir
    display_dir = relative_path(skill_dir, root)
    results: list[ValidationResult] = []
    errors: list[Issue] = []
    resolved_skill_dir = skill_dir.resolve()

    for path in sorted(skill_dir.rglob("*")):
        if not path.is_symlink():
            continue
        try:
            path.resolve(strict=True).relative_to(resolved_skill_dir)
        except (OSError, ValueError):
            errors.append(
                Issue(
                    codes.PATH_SYMLINK_ESCAPE,
                    relative_path(path, root),
                    "Skill 内的符号链接不得指向 Skill 目录外或不存在的目标",
                )
            )

    skill_files = sorted(skill_dir.rglob("SKILL.md"))
    entry_file = skill_dir / "SKILL.md"
    if not entry_file.is_file():
        errors.append(Issue(codes.SKILL_MISSING_ENTRY, display_dir, "缺少入口文件 SKILL.md"))
    if len(skill_files) > 1:
        errors.append(
            Issue(codes.SKILL_MULTIPLE_ENTRIES, display_dir, "一个 Skill 只能包含一个作为入口的 SKILL.md")
        )

    for directory_name in OPTIONAL_SKILL_DIRECTORIES:
        candidate = skill_dir / directory_name
        if candidate.exists() and not candidate.is_dir():
            errors.append(
                Issue(
                    codes.SKILL_INVALID_OPTIONAL_DIRECTORY,
                    relative_path(candidate, root),
                    f"{directory_name} 存在时必须是目录",
                )
            )

    results.append(ValidationResult(errors=tuple(errors)))
    for markdown_file in sorted(skill_dir.rglob("*.md")):
        text, read_result = read_text(markdown_file, root)
        results.append(read_result)
        if text is None:
            continue
        if not text.strip():
            results.append(
                ValidationResult(
                    errors=(
                        Issue(
                            codes.SKILL_EMPTY_MARKDOWN,
                            relative_path(markdown_file, root),
                            "Markdown 文件不得为空",
                        ),
                    )
                )
            )
            continue
        results.append(validate_markdown_links(markdown_file, text, skill_dir, root))
        if markdown_file == entry_file:
            results.append(validate_frontmatter(markdown_file, context.skill_name, text, root))

    results.append(validate_python_scripts(skill_dir, root))
    return ValidationResult.merge(*results)
