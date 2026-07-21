"""Skill 校验插件的版本化发现与定向加载。"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Callable

from . import codes
from .models import Issue, SkillContext, ValidationResult


PLUGIN_API_VERSION = 1
PLUGIN_FILE_RE = re.compile(r"^[a-z0-9_]+$")
PluginValidator = Callable[[SkillContext], ValidationResult]


@dataclass(frozen=True, slots=True)
class PluginHandle:
    """已通过接口检查的插件句柄。"""

    skill_name: str
    path: Path
    validate: PluginValidator


@dataclass(frozen=True, slots=True)
class PluginDiscoveryResult:
    plugins: tuple[PluginHandle, ...]
    result: ValidationResult


@dataclass(frozen=True, slots=True)
class PluginLoadResult:
    plugin: PluginHandle | None
    result: ValidationResult


def plugin_filename(skill_name: str) -> str:
    return f"{skill_name.replace('-', '_')}.py"


def _display_path(path: Path, plugin_dir: Path) -> str:
    try:
        return path.relative_to(plugin_dir.parent).as_posix()
    except ValueError:
        return str(path)


def _load_module(path: Path, plugin_dir: Path) -> tuple[ModuleType | None, ValidationResult]:
    display_path = _display_path(path, plugin_dir)
    module_name = f"_skill_plugin_{path.stem}_{abs(hash(path.resolve()))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return None, ValidationResult(
            errors=(Issue(codes.PLUGIN_IMPORT_FAILED, display_path, "无法创建插件导入规范"),)
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # 插件是受信任代码，但导入失败必须隔离并继续。
        sys.modules.pop(module_name, None)
        return None, ValidationResult(
            errors=(
                Issue(
                    codes.PLUGIN_IMPORT_FAILED,
                    display_path,
                    f"插件导入失败：{type(exc).__name__}: {exc}",
                ),
            )
        )
    return module, ValidationResult()


def _module_to_handle(module: ModuleType, path: Path, plugin_dir: Path) -> PluginLoadResult:
    display_path = _display_path(path, plugin_dir)
    version = getattr(module, "PLUGIN_API_VERSION", None)
    if version != PLUGIN_API_VERSION:
        return PluginLoadResult(
            None,
            ValidationResult(
                errors=(
                    Issue(
                        codes.PLUGIN_API_VERSION_UNSUPPORTED,
                        display_path,
                        f"PLUGIN_API_VERSION 必须为 {PLUGIN_API_VERSION}，当前为 {version!r}",
                    ),
                )
            ),
        )
    skill_name = getattr(module, "SKILL_NAME", None)
    validate = getattr(module, "validate", None)
    errors: list[Issue] = []
    if not isinstance(skill_name, str) or not skill_name.strip():
        errors.append(
            Issue(codes.PLUGIN_INVALID_INTERFACE, display_path, "SKILL_NAME 必须是非空字符串")
        )
    if not callable(validate):
        errors.append(Issue(codes.PLUGIN_INVALID_INTERFACE, display_path, "validate 必须可调用"))
    if errors:
        return PluginLoadResult(None, ValidationResult(errors=tuple(errors)))

    assert isinstance(skill_name, str)
    expected_name = plugin_filename(skill_name)
    if path.name != expected_name:
        return PluginLoadResult(
            PluginHandle(skill_name, path, validate),
            ValidationResult(
                errors=(
                    Issue(
                        codes.PLUGIN_NAME_MISMATCH,
                        display_path,
                        f"插件文件名应为 {expected_name}，与 SKILL_NAME {skill_name} 对应",
                    ),
                )
            ),
        )
    return PluginLoadResult(PluginHandle(skill_name, path, validate), ValidationResult())


def _load_plugin_file(path: Path, plugin_dir: Path) -> PluginLoadResult:
    module, import_result = _load_module(path, plugin_dir)
    if module is None:
        return PluginLoadResult(None, import_result)
    interface_result = _module_to_handle(module, path, plugin_dir)
    return PluginLoadResult(interface_result.plugin, ValidationResult.merge(import_result, interface_result.result))


def discover_plugins(plugin_dir: Path) -> PluginDiscoveryResult:
    """按文件名排序加载全部插件；单个插件失败不终止发现。"""

    if not plugin_dir.is_dir():
        return PluginDiscoveryResult((), ValidationResult())
    paths = tuple(
        path
        for path in sorted(plugin_dir.glob("*.py"))
        if path.name != "__init__.py" and not path.name.startswith("_")
    )
    plugins: list[PluginHandle] = []
    results: list[ValidationResult] = []
    seen: dict[str, Path] = {}
    for path in paths:
        if not PLUGIN_FILE_RE.fullmatch(path.stem):
            results.append(
                ValidationResult(
                    errors=(
                        Issue(
                            codes.PLUGIN_NAME_MISMATCH,
                            _display_path(path, plugin_dir),
                            "插件文件名只能使用小写字母、数字和下划线",
                        ),
                    )
                )
            )
            continue
        loaded = _load_plugin_file(path, plugin_dir)
        results.append(loaded.result)
        if loaded.plugin is None:
            continue
        previous = seen.get(loaded.plugin.skill_name)
        if previous is not None:
            results.append(
                ValidationResult(
                    errors=(
                        Issue(
                            codes.PLUGIN_DUPLICATE,
                            _display_path(path, plugin_dir),
                            f"Skill {loaded.plugin.skill_name} 已由 {_display_path(previous, plugin_dir)} 注册",
                        ),
                    )
                )
            )
            continue
        seen[loaded.plugin.skill_name] = path
        plugins.append(loaded.plugin)
    return PluginDiscoveryResult(tuple(plugins), ValidationResult.merge(*results))


def load_plugin_for_skill(plugin_dir: Path, skill_name: str) -> PluginLoadResult:
    """只定位和导入目标 Skill 插件，不扫描其他插件。"""

    path = plugin_dir / plugin_filename(skill_name)
    if not path.is_file():
        return PluginLoadResult(None, ValidationResult())
    loaded = _load_plugin_file(path, plugin_dir)
    if loaded.plugin is not None and loaded.plugin.skill_name != skill_name:
        return PluginLoadResult(
            None,
            ValidationResult.merge(
                loaded.result,
                ValidationResult(
                    errors=(
                        Issue(
                            codes.PLUGIN_NAME_MISMATCH,
                            _display_path(path, plugin_dir),
                            f"目标 Skill 为 {skill_name}，插件声明为 {loaded.plugin.skill_name}",
                        ),
                    )
                ),
            ),
        )
    return loaded


def run_plugin(plugin: PluginHandle, context: SkillContext) -> ValidationResult:
    """隔离插件执行异常并验证返回类型。"""

    display_path = _display_path(plugin.path, plugin.path.parent)
    try:
        result = plugin.validate(context)
    except Exception as exc:
        return ValidationResult(
            errors=(
                Issue(
                    codes.PLUGIN_EXECUTION_FAILED,
                    display_path,
                    f"插件执行失败：{type(exc).__name__}: {exc}",
                ),
            )
        )
    if not isinstance(result, ValidationResult):
        return ValidationResult(
            errors=(
                Issue(
                    codes.PLUGIN_INVALID_RESULT,
                    display_path,
                    "插件 validate 必须返回 ValidationResult",
                ),
            )
        )
    return result
