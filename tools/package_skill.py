#!/usr/bin/env python3
"""校验并打包仓库中的单个 Agent Skill。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
root_text = str(REPOSITORY_ROOT)
if root_text not in sys.path:
    sys.path.insert(0, root_text)

from skill_framework.packaging import PackageError, PackageResult, package_skill  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
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
        default=REPOSITORY_ROOT,
        help="仓库根目录；默认使用当前脚本所在仓库",
    )
    return parser


def select_skill_name(positional: str | None, option: str | None) -> str:
    if positional and option:
        raise PackageError("请只使用位置参数或 --skill 指定一次 Skill 名称")
    skill_name = positional or option
    if not skill_name:
        raise PackageError("缺少 Skill 名称；请使用位置参数或 --skill")
    return skill_name


def print_result(result: PackageResult) -> None:
    if result.warnings:
        print("警告：")
        for warning in result.warnings:
            print(f"- {warning.render()}")
    print(f"Skill 名称：{result.skill_name}")
    print(f"输出路径：{result.output_path}")
    print(f"文件数量：{result.file_count}")
    print(f"ZIP 文件大小：{result.size_bytes} 字节")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        skill_name = select_skill_name(args.skill_name, args.skill_option)
        result = package_skill(
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
