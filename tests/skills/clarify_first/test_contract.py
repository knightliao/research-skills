"""clarify-first Skill 的静态行为契约测试。"""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = ROOT / ".agents" / "skills" / "clarify-first"
SKILL_PATH = SKILL_DIR / "SKILL.md"
USAGE_PATH = SKILL_DIR / "examples" / "usage.md"
OPENAI_YAML_PATH = SKILL_DIR / "agents" / "openai.yaml"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class ClarifyFirstContractTests(unittest.TestCase):
    def test_required_resources_exist(self) -> None:
        for path in (SKILL_PATH, USAGE_PATH, OPENAI_YAML_PATH):
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertTrue(path.is_file())

    def test_clarification_turn_has_exactly_one_question_contract(self) -> None:
        skill = read(SKILL_PATH)
        for invariant in (
            "每次回复只能提出一个问题",
            "等待用户回答",
            "继续围绕同一问题追问",
            "不提前跳到其他维度",
        ):
            with self.subTest(invariant=invariant):
                self.assertIn(invariant, skill)
        self.assertNotIn("每轮问 1–4 个", skill)

    def test_solution_is_gated_by_explicit_summary_confirmation(self) -> None:
        skill = read(SKILL_PATH)
        for invariant in (
            "明确确认需求摘要前，严格禁止",
            "不得在同一条回复中同时提交首次需求摘要并给出方案",
            "下一次回复才可以提供方案",
            "沉默、转移话题、回答新的细节或“差不多”不视为明确确认",
        ):
            with self.subTest(invariant=invariant):
                self.assertIn(invariant, skill)
        self.assertNotIn("可以给出临时方案", skill)

    def test_socratic_questions_are_neutral_and_non_leading(self) -> None:
        skill = read(SKILL_PATH)
        for dimension in ("检验动机", "检验假设", "检验证据", "检验矛盾", "检验取舍"):
            with self.subTest(dimension=dimension):
                self.assertIn(dimension, skill)
        for invariant in ("简短、中立、自然", "不暗示哪种回答更正确", "不在问题中预设结论"):
            with self.subTest(invariant=invariant):
                self.assertIn(invariant, skill)

    def test_usage_documents_the_turn_by_turn_gate(self) -> None:
        usage = read(USAGE_PATH)
        for invariant in (
            "每轮只问一个",
            "继续澄清同一问题",
            "明确确认需求摘要",
            "不会在同一条回复中附带方案",
        ):
            with self.subTest(invariant=invariant):
                self.assertIn(invariant, usage)
        self.assertNotIn("先问最关键的三个问题", usage)
        self.assertNotIn("推荐默认值", usage)

    def test_metadata_preserves_explicit_invocation(self) -> None:
        metadata = read(OPENAI_YAML_PATH)
        self.assertRegex(metadata, r'default_prompt:\s*"[^"\n]*\$clarify-first[^"\n]*"')
        self.assertRegex(metadata, r"allow_implicit_invocation:\s*false")

    def test_v1_remains_instruction_only(self) -> None:
        self.assertFalse((SKILL_DIR / "scripts").exists())
        self.assertFalse((SKILL_DIR / "references").exists())
        self.assertFalse((SKILL_DIR / "assets").exists())
        self.assertFalse((ROOT / "plugins" / "clarify_first.py").exists())


if __name__ == "__main__":
    unittest.main()
