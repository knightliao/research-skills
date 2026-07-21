"""框架层共享的不可变数据模型。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Issue:
    """一条可定位且具有稳定类别的错误或警告。"""

    code: str
    path: str
    message: str
    line: int | None = None
    snippet: str | None = None

    def render(self) -> str:
        """生成适合中文 CLI 的脱敏问题描述。"""

        location = f"{self.path}:{self.line}" if self.line is not None else self.path
        suffix = f"；片段：{self.snippet}" if self.snippet else ""
        return f"[{self.code}] {location}：{self.message}{suffix}"


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """一次校验的独立、不可变结果。"""

    errors: tuple[Issue, ...] = ()
    warnings: tuple[Issue, ...] = ()

    @property
    def is_valid(self) -> bool:
        """没有错误时返回 ``True``；警告不影响有效性。"""

        return not self.errors

    @classmethod
    def merge(cls, *results: ValidationResult) -> ValidationResult:
        """按传入顺序合并结果，不修改输入，也不自动去重。"""

        return cls(
            errors=tuple(issue for result in results for issue in result.errors),
            warnings=tuple(issue for result in results for issue in result.warnings),
        )


@dataclass(frozen=True, slots=True)
class SkillContext:
    """通用校验器和插件访问单个 Skill 所需的全部上下文。"""

    repository_root: Path
    skill_dir: Path
    skill_name: str


@dataclass(frozen=True, slots=True)
class RepositoryValidation:
    """仓库校验的计数与聚合结果。"""

    skill_count: int
    plugin_count: int
    result: ValidationResult

    @property
    def is_valid(self) -> bool:
        return self.result.is_valid

    @property
    def errors(self) -> tuple[Issue, ...]:
        return self.result.errors

    @property
    def warnings(self) -> tuple[Issue, ...]:
        return self.result.warnings
