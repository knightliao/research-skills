"""用户访谈人物配图工作流的契约测试。"""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = ROOT / ".agents" / "skills" / "subtitle-to-wechat-article"


class InterviewPortraitContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        cls.package = (SKILL_DIR / "references" / "wechat-package.md").read_text(
            encoding="utf-8"
        )
        cls.quality = (SKILL_DIR / "references" / "quality-checklist.md").read_text(
            encoding="utf-8"
        )
        cls.usage = (SKILL_DIR / "examples" / "usage.md").read_text(encoding="utf-8")

    def test_interview_branch_precedes_image_generation(self) -> None:
        workflow = self.skill.split("## 主工作流", 1)[1].split(
            "## 语言与忠实度规则", 1
        )[0]
        interview = workflow.index("**判断用户访谈配图分支**")
        mapping = workflow.index("**提炼内容—视觉映射**")
        image = workflow.index("**生成真实图片**")
        self.assertLess(interview, image)
        self.assertLess(mapping, image)
        for phrase in (
            "确认唯一主人公",
            "不得把主持人、采访者、同名者或推测身份当作主人公",
            "获取可信头像并微修",
            "保持文章包 incomplete",
        ):
            self.assertIn(phrase, workflow)

    def test_content_mapping_is_required_before_image_editing(self) -> None:
        section = self.package.split("## 图片与文章内容适配", 1)[1].split(
            "## 用户访谈的人物配图", 1
        )[0]
        for phrase in (
            "最终标题、导语、各节主旨和结语",
            "core_theme",
            "central_tension",
            "allowed_metaphors",
            "forbidden_inferences",
            "文章线索 → 视觉表达",
            "通用科技蓝背景只属于版式适配",
            "换标题测试",
        ):
            self.assertIn(phrase, section)

    def test_portrait_source_and_edit_boundaries_are_explicit(self) -> None:
        section = self.package.split("## 用户访谈的人物配图", 1)[1].split(
            "## 创建新版本", 1
        )[0]
        for phrase in (
            "主持人、采访者、旁白",
            "人物本人控制的公开主页",
            "不得使用搜索结果缩略图",
            "文章包之外的临时路径",
            "最终交付说明中记录原始页面 URL、图片 URL 和获取日期",
            "支持参考图编辑的图片工具",
            "不能只凭姓名或文字描述重新生成人物",
            "不做人脸替换",
            "不得改用 AI 生成的相似人物冒充本人",
        ):
            self.assertIn(phrase, section)

    def test_online_lookup_exception_cannot_expand_article_facts(self) -> None:
        self.assertIn("检索结果不得反向补入正文", self.skill)
        self.assertIn("只能用于定位和确认配图", self.package)
        self.assertIn("检索结果没有反向进入正文", self.quality)
        self.assertIn("检索结果不会写入正文", self.usage)

    def test_usage_and_quality_gate_cover_interview_portraits(self) -> None:
        for phrase in ("核心受访者姓名", "多人访谈", "内容—视觉映射", "文章视觉简报"):
            self.assertIn(phrase, self.usage)
        for phrase in (
            "视觉简报",
            "文章线索 → 视觉表达",
            "换标题测试",
            "内容—视觉映射缺失",
            "图片未通过换标题测试",
            "唯一确认核心受访者",
            "使用权限",
            "真实头像微修结果",
        ):
            self.assertIn(phrase, self.quality)


if __name__ == "__main__":
    unittest.main()
