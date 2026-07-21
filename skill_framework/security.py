"""仓库文本中的高可信敏感信息扫描。"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable

from . import codes
from .markdown import relative_path
from .models import Issue, ValidationResult


IGNORED_DIRECTORIES = frozenset(
    {
        ".git", ".hg", ".svn", ".idea", ".vscode", ".mypy_cache", ".pytest_cache",
        ".ruff_cache", ".tox", ".nox", ".venv", "venv", "env", "dist", "build",
        "node_modules", "__pycache__",
    }
)
TEXT_SUFFIXES = frozenset(
    {".cfg", ".conf", ".csv", ".env", ".ini", ".json", ".jsonl", ".md", ".py", ".sh", ".toml", ".txt", ".yaml", ".yml"}
)
TEXT_FILENAMES = frozenset({"AGENTS.md", "README.md", ".gitignore"})
PLACEHOLDER_MARKERS = ("EXAMPLE", "FAKE", "DUMMY", "REDACTED", "PLACEHOLDER")
SENSITIVE_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (codes.SECURITY_PRIVATE_KEY, "私钥头", re.compile(r"(?P<secret>-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")),
    (codes.SECURITY_SK_KEY, "sk- 密钥", re.compile(r"\b(?P<secret>sk-[A-Za-z0-9_-]{20,})\b")),
    (codes.SECURITY_AWS_ACCESS_KEY, "AWS access key", re.compile(r"\b(?P<secret>(?:AKIA|ASIA)[A-Z0-9]{16})\b")),
    (
        codes.SECURITY_BEARER_TOKEN,
        "Authorization bearer token",
        re.compile(r"Authorization\s*:\s*Bearer\s+(?P<secret>[A-Za-z0-9._~+/=-]{20,})", re.IGNORECASE),
    ),
    (
        codes.SECURITY_CREDENTIAL_ASSIGNMENT,
        "凭据赋值",
        re.compile(
            r"\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|cookie|client[_-]?secret|secret[_-]?key|aws_secret_access_key)\b\s*[:=]\s*[\"']?(?P<secret>[A-Za-z0-9+/_.=-]{20,})",
            re.IGNORECASE,
        ),
    ),
)


def walk_repository(root: Path, *, ignored_dirs: frozenset[str] = IGNORED_DIRECTORIES) -> Iterable[Path]:
    for current_root, directory_names, file_names in os.walk(root):
        directory_names[:] = sorted(name for name in directory_names if name not in ignored_dirs)
        current_path = Path(current_root)
        for file_name in sorted(file_names):
            path = current_path / file_name
            if not path.is_symlink():
                yield path


def is_placeholder_secret(value: str) -> bool:
    return any(marker in value.upper() for marker in PLACEHOLDER_MARKERS)


def redact_secret(value: str) -> str:
    compact = value.strip().strip("\"'")
    return "[已脱敏]" if len(compact) <= 6 else f"{compact[:4]}…{compact[-2:]}"


def scan_sensitive_information(root: Path) -> ValidationResult:
    """只报告高可信模式，并确保输出中不包含完整秘密值。"""

    errors: list[Issue] = []
    for path in walk_repository(root):
        if path.name not in TEXT_FILENAMES and path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            if path.stat().st_size > 2_000_000:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for code, pattern_name, pattern in SENSITIVE_PATTERNS:
                for match in pattern.finditer(line):
                    secret = match.group("secret")
                    if is_placeholder_secret(secret):
                        continue
                    errors.append(
                        Issue(
                            code,
                            relative_path(path, root),
                            f"发现高可信疑似敏感信息（{pattern_name}）",
                            line_number,
                            redact_secret(secret),
                        )
                    )
    return ValidationResult(errors=tuple(errors))
