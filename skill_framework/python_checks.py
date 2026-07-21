"""Skill 内 Python 脚本的通用静态检查。"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from . import codes
from .markdown import read_text, relative_path
from .models import Issue, ValidationResult


def validate_python_scripts(skill_dir: Path, root: Path) -> ValidationResult:
    """检查语法、相对导入边界和显式第三方依赖。"""

    scripts_dir = skill_dir / "scripts"
    if not scripts_dir.is_dir():
        return ValidationResult()
    standard_library = sys.stdlib_module_names | {"__future__"}
    local_module_names = {path.stem for path in skill_dir.rglob("*.py")}
    local_module_names.update(path.name for path in skill_dir.rglob("*") if path.is_dir())
    resolved_skill_dir = skill_dir.resolve()
    results: list[ValidationResult] = []
    errors: list[Issue] = []

    for script_path in sorted(scripts_dir.rglob("*.py")):
        text, read_result = read_text(script_path, root)
        results.append(read_result)
        if text is None:
            continue
        display_path = relative_path(script_path, root)
        try:
            tree = ast.parse(text, filename=display_path)
        except SyntaxError as exc:
            errors.append(
                Issue(codes.PYTHON_SYNTAX_ERROR, display_path, f"Python 语法错误：{exc.msg}", exc.lineno)
            )
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                module_names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    import_base = script_path.parent
                    for _ in range(node.level - 1):
                        import_base = import_base.parent
                    try:
                        import_base.resolve().relative_to(resolved_skill_dir)
                    except ValueError:
                        errors.append(
                            Issue(
                                codes.PYTHON_IMPORT_ESCAPE,
                                display_path,
                                "Python 相对导入逃逸 Skill 目录",
                                node.lineno,
                            )
                        )
                    continue
                module_names = [node.module] if node.module else []
            else:
                continue
            for module_name in module_names:
                if module_name is None:
                    continue
                top_level = module_name.split(".", 1)[0]
                if top_level in standard_library or top_level in local_module_names:
                    continue
                errors.append(
                    Issue(
                        codes.PYTHON_EXTERNAL_DEPENDENCY,
                        display_path,
                        f"脚本存在非标准库或 Skill 外部 Python 依赖：{module_name}",
                        node.lineno,
                    )
                )
    results.append(ValidationResult(errors=tuple(errors)))
    return ValidationResult.merge(*results)
