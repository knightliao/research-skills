"""global-ai-agent-radar 资源路由与模式语义测试。"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / ".agents" / "skills" / "global-ai-agent-radar"
SKILL_PATH = SKILL_DIR / "SKILL.md"
TEMPLATE_PATH = SKILL_DIR / "assets" / "report-template.md"

ROUTE_ROW_RE = re.compile(
    r"^\|\s*\[[^\]]+\]\(([^)]+)\)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$",
    re.MULTILINE,
)


def extract_h2_section(markdown: str, title: str) -> str:
    """按二级标题提取正文，供语义断言使用。"""

    match = re.search(
        rf"^##\s+{re.escape(title)}\s*$\n(.*?)(?=^##\s+|\Z)",
        markdown,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"缺少二级章节：{title}")
    return match.group(1)


class GlobalRadarResourceRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill_text = SKILL_PATH.read_text(encoding="utf-8")
        cls.template_text = TEMPLATE_PATH.read_text(encoding="utf-8")
        cls.routes = {
            path: (condition, action)
            for path, condition, action in ROUTE_ROW_RE.findall(cls.skill_text)
        }

    def assert_route_semantics(
        self,
        path: str,
        *,
        condition_fragments: tuple[str, ...],
        action_fragments: tuple[str, ...],
    ) -> None:
        self.assertIn(path, self.routes, f"资源没有定义路由：{path}")
        condition, action = self.routes[path]
        for fragment in condition_fragments:
            self.assertIn(fragment, condition, f"{path} 缺少触发语义：{fragment}")
        for fragment in action_fragments:
            self.assertIn(fragment, action, f"{path} 缺少动作语义：{fragment}")
        self.assertTrue((SKILL_DIR / path).is_file(), f"路由目标不存在：{path}")

    def test_watchlist_and_template_routes_define_modes_and_actions(self) -> None:
        self.assert_route_semantics(
            "assets/watchlist.csv",
            condition_fragments=("完整或全球雷达", "维护模式"),
            action_fragments=("研究模式只读", "维护模式", "开放发现"),
        )
        self.assert_route_semantics(
            "assets/report-template.md",
            condition_fragments=("最终报告",),
            action_fragments=("必须", "模式 A", "无重点事件模式"),
        )

    def test_examples_are_routed_by_report_and_quality_scenarios(self) -> None:
        self.assert_route_semantics(
            "examples/good-report.md",
            condition_fragments=("模式 A",),
            action_fragments=("写作前读取", "事实与推断分离"),
        )
        self.assert_route_semantics(
            "examples/no-major-change-report.md",
            condition_fragments=("无重点事件模式",),
            action_fragments=("写作前读取", "低价值新闻"),
        )
        self.assert_route_semantics(
            "examples/bad-report.md",
            condition_fragments=("质量校准", "修订低质量草稿", "终检"),
            action_fragments=("修正", "不复制错误正文"),
        )

    def test_event_validator_route_limits_scope_to_final_report_entries(self) -> None:
        self.assert_route_semantics(
            "scripts/validate_events.py",
            condition_fragments=("最终准备写入报告",),
            action_fragments=("必须校验临时 JSON", "不校验所有搜索候选"),
        )
        workflow = extract_h2_section(self.skill_text, "执行工作流")
        self.assertIn("只把最终准备写入报告的事件和观察信号", workflow)
        self.assertIn("不校验所有搜索候选", workflow)
        self.assertIn("警告由执行 Agent 复核", workflow)
        self.assertIn("不默认要求用户人工介入", workflow)


class GlobalRadarModeSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill_text = SKILL_PATH.read_text(encoding="utf-8")
        cls.template_text = TEMPLATE_PATH.read_text(encoding="utf-8")

    def test_confidence_threshold_and_report_modes_are_explicit(self) -> None:
        section = extract_h2_section(self.skill_text, "报告模式与可信度门槛")
        self.assertIn("`credibility` 为 3–5 分", section)
        self.assertRegex(section, r"模式 A：有重点事件.*24–30.*credibility.*3 分")
        self.assertRegex(section, r"模式 B：无重点事件模式.*18–23.*credibility.*3 分")
        self.assertIn("今天没有重大突破", section)

    def test_watchlist_research_and_maintenance_modes_have_distinct_write_boundaries(self) -> None:
        section = extract_h2_section(self.skill_text, "观察池工作模式")
        self.assertIn("### 研究模式（默认）", section)
        self.assertIn("只读", section)
        self.assertIn("不得在生成日报或专题研究时自动修改观察池", section)
        self.assertIn("### 维护模式", section)
        self.assertIn("仅当用户明确要求维护或更新观察池时进入", section)
        self.assertIn("只应用证据支持且属于用户要求范围的变更", section)
        self.assertIn("修改后运行仓库校验和测试", section)

    def test_no_priority_event_template_keeps_general_events_separate_from_signals(self) -> None:
        mode_b = extract_h2_section(self.template_text, "模式 B：无重点事件模式")
        general_position = mode_b.index("### 一般重要事件")
        signal_position = mode_b.index("### 未达到收录阈值的观察信号")
        self.assertLess(general_position, signal_position)
        self.assertIn("18–23 分且信息可信度至少 3 分", mode_b)
        self.assertIn("**已确认事实**", mode_b)
        self.assertIn("**证据**", mode_b)
        self.assertIn("**分析推断**", mode_b)
        self.assertIn("**行动建议**", mode_b)


if __name__ == "__main__":
    unittest.main()
