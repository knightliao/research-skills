"""字幕翻译状态、术语簿与语境消歧契约测试。"""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = ROOT / ".agents" / "skills" / "subtitle-to-wechat-article"


class TranslationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        cls.processing = (SKILL_DIR / "references" / "subtitle-processing.md").read_text(
            encoding="utf-8"
        )
        cls.policy = (SKILL_DIR / "references" / "translation-policy.md").read_text(
            encoding="utf-8"
        )
        cls.quality = (SKILL_DIR / "references" / "quality-checklist.md").read_text(
            encoding="utf-8"
        )
        cls.example = (SKILL_DIR / "examples" / "terminology-example.md").read_text(
            encoding="utf-8"
        )
        cls.usage = (SKILL_DIR / "examples" / "usage.md").read_text(encoding="utf-8")

    def test_translation_policy_is_routed_for_translation_like_chinese(self) -> None:
        resource_row = next(
            line for line in self.skill.splitlines() if "references/translation-policy.md" in line
        )
        for phrase in ("疑似机翻或译制中文", "技术术语密集", "内部术语簿"):
            self.assertIn(phrase, resource_row)

        workflow = self.skill.split("## 主工作流", 1)[1].split("## 语言与忠实度规则", 1)[0]
        for phrase in ("表层语言", "文本状态", "表面为中文不等于可以跳过术语校准", "术语簿"):
            self.assertIn(phrase, workflow)
        self.assertIn("第一次泛指此类系统时必须写“AI Agent（智能体）”", workflow)

        self.assertIn("表面为中文不等于无需翻译校准", self.processing)
        self.assertIn("不得自动替换术语", self.processing)

    def test_term_ledger_has_stable_precedence_and_stays_internal(self) -> None:
        ordered_phrases = (
            "用户明确给出的术语要求或术语表",
            "字幕明确给出的官方形式",
            "目标领域稳定且适合默认读者的中文惯例",
            "首次保留英文并补充简短中文解释",
            "上下文仍不能唯一确定",
        )
        positions = [self.policy.index(phrase) for phrase in ordered_phrases]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("术语簿仅作内部语义底稿", self.policy)
        self.assertIn("只有上下文唯一支持的高置信度术语", self.policy)
        self.assertIn("中等或低置信度候选不得静默替换", self.policy)
        self.assertIn("推测候选只能记入歧义备注", self.policy)
        self.assertIn("内部术语簿", self.quality)

    def test_agent_default_and_polysemy_are_context_sensitive(self) -> None:
        for phrase in (
            "禁止对单词执行机械全局替换",
            "AI Agent（智能体）",
            "后文统一使用“智能体”",
            "内部术语簿、语义底稿和处理说明中的出现不计入正文首次出现",
            "Code Agent",
            "固定名称中的 `Agent` 不占用通用 AI Agent 概念的首次解释",
            "网络代理",
            "代理人",
        ):
            self.assertIn(phrase, self.policy)
        self.assertIn("不得改成“智能体”", self.policy)
        self.assertIn("不机械替换同形异义词", self.usage)

    def test_terminology_example_covers_ai_and_non_ai_ambiguity(self) -> None:
        self.assertIn("](examples/terminology-example.md)", self.skill)
        for phrase in (
            "AI Agent（智能体）",
            "Code Agent",
            "代理服务",
            "代理人",
            "机器学习系统",
            "时尚行业从业者",
            "术语簿是内部底稿",
        ):
            self.assertIn(phrase, self.example)

    def test_quality_gate_checks_translation_state_and_global_consistency(self) -> None:
        for phrase in (
            "表层语言和中文文本状态",
            "疑似机翻或译制中文已经过语义和术语校准",
            "没有机械全局替换同形异义词",
            "AI 主题的最终 Markdown 第一次泛指此类系统时写作“AI Agent（智能体）”",
            "没有为字幕未提供年份的日期补写相对年份或绝对年份",
        ):
            self.assertIn(phrase, self.quality)


if __name__ == "__main__":
    unittest.main()
