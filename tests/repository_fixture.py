"""从真实仓库创建隔离、可重复的最小测试副本。"""

from __future__ import annotations

import shutil
from pathlib import Path


IGNORED_FIXTURE_NAMES = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")


def copy_repository_fixture(source_root: Path, destination_root: Path) -> None:
    """复制 Skill 与插件源码，排除工作站生成的忽略文件。"""

    for directory_name in (".agents", "plugins"):
        shutil.copytree(
            source_root / directory_name,
            destination_root / directory_name,
            ignore=IGNORED_FIXTURE_NAMES,
        )
    for file_name in (".gitignore", "AGENTS.md", "README.md"):
        shutil.copy2(source_root / file_name, destination_root / file_name)
