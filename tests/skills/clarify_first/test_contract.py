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

    def test_question_budget_is_bounded_and_can_stop_early(self) -> None:
        skill = read(SKILL_PATH)
        for invariant in (
            "问诊最多提出 6 个问题",
            "深化追问也计入 6 个问题",
            "信息足以形成准确新问题时立即停止问诊",
            "第 6 个问题回答后必须停止问诊",
            "问题预算用完后不再追加诊断问题",
        ):
            with self.subTest(invariant=invariant):
                self.assertIn(invariant, skill)

    def test_each_turn_has_one_update_sentence_and_one_question(self) -> None:
        skill = read(SKILL_PATH)
        for invariant in (
            "每次回复只能提出一个问题",
            "提问前先用一句话说明上一条回答让当前判断更新了什么",
            "随后只问一个简短、中立的问题并停止",
            "更新句必须是自然、可核对的陈述",
        ):
            with self.subTest(invariant=invariant):
                self.assertIn(invariant, skill)

    def test_claims_are_classified_before_interpretation(self) -> None:
        skill = read(SKILL_PATH)
        for claim_type in ("可验证的事实", "对事实的解释", "价值判断", "希望实现的目标"):
            with self.subTest(claim_type=claim_type):
                self.assertIn(claim_type, skill)
        self.assertIn("不能整体当作事实", skill)

    def test_questions_target_only_conclusion_changing_uncertainty(self) -> None:
        skill = read(SKILL_PATH)
        for dimension in (
            "澄清关键词",
            "识别默认前提",
            "追溯证据来源",
            "寻找相反解释",
            "检验结论影响",
            "明确真实目标",
        ):
            with self.subTest(dimension=dimension):
                self.assertIn(dimension, skill)
        self.assertIn("不同答案必须可能改变问题定义、证据强度、关键变量或后续判断", skill)

    def test_diagnostic_summary_has_exact_six_outputs(self) -> None:
        skill = read(SKILL_PATH)
        for output in (
            "我最开始问的问题",
            "我真正想解决的问题",
            "已经确认的事实",
            "仍未验证的假设",
            "最可能改变结论的关键变量",
            "一个准确、具体、可以继续行动的新问题",
        ):
            with self.subTest(output=output):
                self.assertIn(output, skill)
        self.assertIn("只选一个最具区分度的变量", skill)

    def test_answer_is_gated_by_new_question_confirmation(self) -> None:
        skill = read(SKILL_PATH)
        for invariant in (
            "用户确认最终新问题前，严格禁止",
            "只有用户明确确认第六项的新问题后",
            "判断、理由和下一步行动",
            "请回复“确认”，或指出这个新问题需要修改的一个地方",
        ):
            with self.subTest(invariant=invariant):
                self.assertIn(invariant, skill)
        self.assertNotIn("确认需求摘要后", skill)

    def test_usage_documents_the_full_diagnostic_protocol(self) -> None:
        usage = read(USAGE_PATH)
        for invariant in (
            "发生了什么",
            "怎么理解",
            "卡在哪里",
            "最多 6 个",
            "上一条回答让它更新了什么判断",
            "明确确认第六项的新问题后",
        ):
            with self.subTest(invariant=invariant):
                self.assertIn(invariant, usage)
        self.assertIn("如果 6 个问题用完后仍有不确定信息", usage)

    def test_metadata_preserves_explicit_invocation(self) -> None:
        metadata = read(OPENAI_YAML_PATH)
        self.assertIn('display_name: "苏格拉底式问诊"', metadata)
        self.assertRegex(metadata, r'default_prompt:\s*"[^"\n]*\$clarify-first[^"\n]*"')
        self.assertRegex(metadata, r"allow_implicit_invocation:\s*false")

    def test_v1_remains_instruction_only(self) -> None:
        self.assertFalse((SKILL_DIR / "scripts").exists())
        self.assertFalse((SKILL_DIR / "references").exists())
        self.assertFalse((SKILL_DIR / "assets").exists())
        self.assertFalse((ROOT / "plugins" / "clarify_first.py").exists())


if __name__ == "__main__":
    unittest.main()
