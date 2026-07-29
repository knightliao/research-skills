"""仓库内正式 Skill 用户使用文档的结构与链接测试。"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / ".agents" / "skills"
README_PATH = ROOT / "README.md"

MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)\n]+)\)")
TEXT_FENCE_RE = re.compile(r"```text[ \t]*\n.+?\n```", re.DOTALL)
SEMANTIC_KEYWORDS = {
    "快速开始": ("快速开始", "快速使用", "开始使用"),
    "可复制输入": ("可复制输入", "复制输入", "示例输入"),
    "预期交付": ("预期交付", "预计获得", "预期结果", "交付内容"),
    "不适用场景": ("不适用场景", "不适合", "不要使用"),
}
MIN_NON_WHITESPACE_CHARACTERS = 400


def discover_skill_dirs() -> tuple[Path, ...]:
    """自动发现以 SKILL.md 为入口的正式 Skill。"""

    return tuple(sorted(path.parent for path in SKILLS_ROOT.glob("*/SKILL.md")))


def markdown_link_targets(text: str) -> tuple[str, ...]:
    """提取普通 Markdown 链接目标，忽略可选标题。"""

    targets: list[str] = []
    for raw_target in MARKDOWN_LINK_RE.findall(text):
        target = raw_target.strip()
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1]
        else:
            target = target.split(maxsplit=1)[0]
        targets.append(target)
    return tuple(targets)


def local_link_path(source_file: Path, target: str) -> Path | None:
    """把本地 Markdown 目标解析为绝对路径；远程和页内链接返回 None。"""

    if not target or target.startswith("#") or urlsplit(target).scheme:
        return None
    path_text = unquote(target.split("#", 1)[0])
    return (source_file.parent / path_text).resolve()


class SkillUsageDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill_dirs = discover_skill_dirs()
        cls.readme_text = README_PATH.read_text(encoding="utf-8")
        cls.readme_targets = markdown_link_targets(cls.readme_text)

    def test_repository_has_discoverable_formal_skills(self) -> None:
        self.assertTrue(self.skill_dirs, "没有发现 .agents/skills/*/SKILL.md")

    def test_each_skill_has_usage_doc_and_skill_entry_link(self) -> None:
        for skill_dir in self.skill_dirs:
            skill_name = skill_dir.name
            with self.subTest(skill=skill_name):
                usage_path = skill_dir / "examples" / "usage.md"
                self.assertTrue(
                    usage_path.is_file(),
                    f"{skill_name} 缺少 examples/usage.md",
                )

                skill_path = skill_dir / "SKILL.md"
                targets = markdown_link_targets(skill_path.read_text(encoding="utf-8"))
                self.assertIn(
                    "examples/usage.md",
                    targets,
                    f"{skill_name}/SKILL.md 缺少指向 examples/usage.md 的相对链接",
                )
                self.assertTrue(
                    (skill_path.parent / "examples" / "usage.md").is_file(),
                    f"{skill_name}/SKILL.md 的 examples/usage.md 链接目标不存在",
                )

    def test_each_usage_doc_has_copyable_input_and_required_semantics(self) -> None:
        for skill_dir in self.skill_dirs:
            skill_name = skill_dir.name
            usage_path = skill_dir / "examples" / "usage.md"
            with self.subTest(skill=skill_name):
                text = usage_path.read_text(encoding="utf-8")
                compact_length = len(re.sub(r"\s+", "", text))
                self.assertGreaterEqual(
                    compact_length,
                    MIN_NON_WHITESPACE_CHARACTERS,
                    f"{skill_name}/examples/usage.md 内容过少，疑似空壳文档",
                )
                self.assertRegex(
                    text,
                    TEXT_FENCE_RE,
                    f"{skill_name}/examples/usage.md 缺少 fenced text 可复制输入",
                )
                for label, keywords in SEMANTIC_KEYWORDS.items():
                    self.assertTrue(
                        any(keyword in text for keyword in keywords),
                        f"{skill_name}/examples/usage.md 缺少“{label}”等价语义",
                    )

    def test_usage_doc_local_links_exist_and_stay_within_skill(self) -> None:
        for skill_dir in self.skill_dirs:
            skill_name = skill_dir.name
            usage_path = skill_dir / "examples" / "usage.md"
            targets = markdown_link_targets(usage_path.read_text(encoding="utf-8"))
            for target in targets:
                with self.subTest(skill=skill_name, target=target):
                    resolved = local_link_path(usage_path, target)
                    if resolved is None:
                        continue
                    try:
                        resolved.relative_to(skill_dir.resolve())
                    except ValueError:
                        self.fail(
                            f"{skill_name}/examples/usage.md 的本地链接逃逸 Skill：{target}"
                        )
                    self.assertTrue(
                        resolved.is_file(),
                        f"{skill_name}/examples/usage.md 的本地链接目标不存在：{target}",
                    )

    def test_readme_links_to_each_usage_doc(self) -> None:
        self.assertIn("## 快速使用", self.readme_text, "README.md 缺少快速使用入口")
        for skill_dir in self.skill_dirs:
            skill_name = skill_dir.name
            target = f".agents/skills/{skill_name}/examples/usage.md"
            with self.subTest(skill=skill_name):
                self.assertIn(
                    target,
                    self.readme_targets,
                    f"README.md 缺少 {skill_name} 的详细使用示例链接",
                )
                self.assertTrue(
                    (ROOT / target).is_file(),
                    f"README.md 中 {skill_name} 的使用示例链接目标不存在",
                )


if __name__ == "__main__":
    unittest.main()
