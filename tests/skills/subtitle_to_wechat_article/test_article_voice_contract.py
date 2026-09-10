"""独立成文、实名归因与身份降级策略的契约测试。"""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = ROOT / ".agents" / "skills" / "subtitle-to-wechat-article"


def target_article(example: str) -> str:
    return example.split("## 目标文章", 1)[1]


class ArticleVoiceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        cls.processing = (SKILL_DIR / "references" / "subtitle-processing.md").read_text(
            encoding="utf-8"
        )
        cls.guide = (SKILL_DIR / "references" / "article-writing-guide.md").read_text(
            encoding="utf-8"
        )
        cls.quality = (SKILL_DIR / "references" / "quality-checklist.md").read_text(
            encoding="utf-8"
        )
        chinese = (SKILL_DIR / "examples" / "chinese-example.md").read_text(
            encoding="utf-8"
        )
        english = (SKILL_DIR / "examples" / "english-example.md").read_text(
            encoding="utf-8"
        )
        cls.chinese_article = target_article(chinese)
        cls.english_article = target_article(english)
        cls.bad_example = (SKILL_DIR / "examples" / "bad-example.md").read_text(
            encoding="utf-8"
        )
        cls.usage = (SKILL_DIR / "examples" / "usage.md").read_text(encoding="utf-8")

    def test_positive_examples_read_as_independent_articles(self) -> None:
        source_traces = (
            "这期领读",
            "本期节目",
            "这场访谈",
            "分享嘉宾",
            "分享中",
            "根据字幕",
            "字幕显示",
            "字幕明确",
            "讲者",
        )
        for article in (self.chinese_article, self.english_article):
            for phrase in source_traces:
                self.assertNotIn(phrase, article)

    def test_known_speaker_is_named_directly(self) -> None:
        self.assertIn("林舟认为", self.chinese_article)
        self.assertIn("Maya 认为", self.english_article)
        self.assertIn("Maya 提到", self.english_article)
        self.assertNotIn("嘉宾", self.english_article)
        for phrase in (
            "姓名可靠时直接使用姓名",
            "孙雨涛认为",
            "不得用“分享嘉宾认为”",
        ):
            self.assertIn(phrase, self.guide)

    def test_unknown_identity_uses_specific_role_before_generic_attribution(self) -> None:
        self.assertIn("内部讲者映射", self.processing)
        self.assertIn("姓名、角色、原始标签", self.processing)
        self.assertIn("转写变体", self.processing)
        specific_role = self.guide.index("研究团队”“作者”“主持人”“受访者")
        generic_speaker = self.guide.index("角色也无法确认、但观点又必须归因时")
        self.assertLess(specific_role, generic_speaker)
        self.assertIn("不得猜测或静默选取", self.processing)

    def test_removing_source_traces_preserves_attribution_and_fidelity(self) -> None:
        for phrase in (
            "不能为了删除来源痕迹而隐去必要归因",
            "第一人称亲历",
            "不把任何一方观点写成客观事实",
        ):
            self.assertIn(phrase, self.guide)
        for phrase in (
            "没有隐去必要归因",
            "把个人判断改成客观事实",
            "第一人称亲历",
        ):
            self.assertIn(phrase, self.quality)

    def test_bad_example_covers_both_failure_modes(self) -> None:
        self.assertIn("**暴露加工来源**", self.bad_example)
        self.assertIn("**模糊代称**", self.bad_example)
        self.assertIn("林然认为", self.bad_example)
        self.assertIn("可独立阅读的文章", self.usage)


if __name__ == "__main__":
    unittest.main()
