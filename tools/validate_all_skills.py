#!/usr/bin/env python3
"""校验仓库内全部 Agent Skill。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
root_text = str(REPOSITORY_ROOT)
if root_text not in sys.path:
    sys.path.insert(0, root_text)

from skill_framework.models import RepositoryValidation  # noqa: E402
from skill_framework.repository import validate_repository  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "扫描 .agents/skills/*，执行通用结构、安全规则及已注册 Skill 插件校验。"
            "frontmatter 仅支持扁平 key: value 字段。"
        ),
        add_help=False,
    )
    parser._positionals.title = "位置参数"
    parser._optionals.title = "选项"
    parser.add_argument("-h", "--help", action="help", help="显示此帮助信息并退出")
    parser.add_argument(
        "repository",
        nargs="?",
        type=Path,
        default=REPOSITORY_ROOT,
        help="仓库目录；默认使用当前脚本所在仓库",
    )
    return parser


def print_report(report: RepositoryValidation) -> None:
    if report.errors:
        print("错误：", file=sys.stderr)
        for issue in report.errors:
            print(f"- {issue.render()}", file=sys.stderr)
    if report.warnings:
        print("警告：")
        for issue in report.warnings:
            print(f"- {issue.render()}")
    status = "通过" if report.is_valid else "失败"
    summary = (
        f"校验{status}：已校验 {report.skill_count} 个 Skill、加载 {report.plugin_count} 个插件，"
        f"发现 {len(report.errors)} 个错误和 {len(report.warnings)} 个警告。"
    )
    print(summary, file=sys.stdout if report.is_valid else sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = validate_repository(args.repository)
    print_report(report)
    return 0 if report.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
