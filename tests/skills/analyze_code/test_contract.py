"""analyze-code Skill 的结构与行为契约测试。"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = ROOT / ".agents" / "skills" / "analyze-code"
SKILL_PATH = SKILL_DIR / "SKILL.md"
OUTPUT_CONTRACT_PATH = SKILL_DIR / "references" / "output-contract.md"
GUIDELINES_PATH = SKILL_DIR / "references" / "analysis-guidelines.md"
OPENAI_YAML_PATH = SKILL_DIR / "agents" / "openai.yaml"
GOOD_EXAMPLE_PATH = SKILL_DIR / "examples" / "good-analysis.md"

HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
FRONTMATTER_RE = re.compile(r"\A---\n(?P<body>.*?)\n---", re.DOTALL)
PYTHON_FENCE_RE = re.compile(r"```python\n(?P<code>.*?)\n```", re.DOTALL)
CORE_FLOW_RE = re.compile(
    r"^# 核心流程\n\n(?P<body>.*?)(?=\n# 代码详细分析$)",
    re.DOTALL | re.MULTILINE,
)
SUMMARIZED_STEP_RE = re.compile(r"^\d+\. \*\*[^*：]{2,16}\*\*：\S.+[。！？]$")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def headings(path: Path) -> tuple[str, ...]:
    return tuple(HEADING_RE.findall(read(path)))


class AnalyzeCodeContractTests(unittest.TestCase):
    def test_required_skill_resources_exist(self) -> None:
        required_paths = (
            SKILL_PATH,
            OPENAI_YAML_PATH,
            OUTPUT_CONTRACT_PATH,
            GUIDELINES_PATH,
            SKILL_DIR / "examples" / "usage.md",
            GOOD_EXAMPLE_PATH,
            SKILL_DIR / "examples" / "bad-analysis.md",
        )
        for path in required_paths:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertTrue(path.is_file())

    def test_frontmatter_requires_explicit_invocation(self) -> None:
        match = FRONTMATTER_RE.match(read(SKILL_PATH))
        self.assertIsNotNone(match)
        assert match is not None
        frontmatter = match.group("body")
        self.assertIsNotNone(re.search(r"^name:\s*analyze-code$", frontmatter, re.MULTILINE))
        self.assertIn("显式", frontmatter)
        self.assertIn("$analyze-code", frontmatter)
        self.assertTrue(any(term in frontmatter for term in ("不得调用", "禁止隐式")))
        self.assertIn("只粘贴代码", frontmatter)
        for competing_intent in ("修改", "调试", "Review", "安全", "性能", "重构", "测试"):
            with self.subTest(competing_intent=competing_intent):
                self.assertIn(competing_intent, read(SKILL_PATH))

    def test_output_phases_are_declared_in_public_order(self) -> None:
        contract_headings = headings(OUTPUT_CONTRACT_PATH)
        public_phases = ("一句话说明", "核心流程", "代码详细分析")
        positions = tuple(contract_headings.index(phase) for phase in public_phases)
        self.assertEqual(tuple(sorted(positions)), positions)

    def test_behavior_contracts_have_independent_sections(self) -> None:
        skill_headings = set(headings(SKILL_PATH))
        self.assertTrue(
            {
                "信息密度原则",
                "原始行号与覆盖",
                "长代码与输出预算",
                "静态分析边界",
            }.issubset(
                skill_headings
            )
        )
        guideline_headings = set(headings(GUIDELINES_PATH))
        self.assertTrue(
            {
                "事实、范围与未知",
                "入口与执行顺序",
                "选择主要解释视角",
                "长代码分配策略",
            }.issubset(guideline_headings)
        )

    def test_skill_routes_each_progressive_resource(self) -> None:
        skill_text = read(SKILL_PATH)
        for relative_path in (
            "examples/usage.md",
            "references/output-contract.md",
            "references/analysis-guidelines.md",
            "examples/good-analysis.md",
            "examples/bad-analysis.md",
        ):
            with self.subTest(relative_path=relative_path):
                self.assertIn(f"]({relative_path})", skill_text)

    def test_multiline_call_is_one_semantic_unit(self) -> None:
        contract = read(OUTPUT_CONTRACT_PATH)
        self.assertIn("response = await client.post(\n", contract)
        self.assertIn("### L10-L14", contract)
        self.assertIn("多行调用必须整体解释", contract)
        self.assertTrue(any(term in contract for term in ("不得拆成", "机械段落")))

    def test_long_code_contract_preserves_global_coverage(self) -> None:
        skill_text = read(SKILL_PATH)
        self.assertIn("整体目的和主执行路径必须完整", skill_text)
        self.assertIn("结构地图必须覆盖整个输入", skill_text)
        contract = read(OUTPUT_CONTRACT_PATH)
        for status in ("已展开", "部分展开", "未展开"):
            self.assertIn(status, contract)
        self.assertIn("结构地图", contract)
        self.assertIn("主路径", contract)

    def test_contract_adapts_map_and_explanation_lens(self) -> None:
        contract = read(OUTPUT_CONTRACT_PATH)
        for map_kind in ("逻辑阶段地图", "职责与方法地图", "文件模块地图", "入口与处理链地图"):
            with self.subTest(map_kind=map_kind):
                self.assertIn(map_kind, contract)
        for lens in ("调用链", "数据流", "状态迁移", "分支结果表", "生命周期"):
            with self.subTest(lens=lens):
                self.assertIn(lens, contract)
        self.assertIn("默认最多补充一种关系视图", contract)

    def test_contract_assigns_information_once_with_variable_depth(self) -> None:
        skill_text = read(SKILL_PATH)
        self.assertIn("同一事实默认只完整解释一次", skill_text)
        self.assertIn("完整语义覆盖不等于平均篇幅", skill_text)
        contract = read(OUTPUT_CONTRACT_PATH)
        self.assertIn("同一事实只完整解释一次", contract)
        self.assertIn("不要求相同篇幅", contract)

    def test_openai_metadata_disables_implicit_invocation(self) -> None:
        metadata = read(OPENAI_YAML_PATH)
        self.assertIn('display_name: "代码分析"', metadata)
        self.assertRegex(metadata, r'default_prompt:\s*"[^"\n]*\$analyze-code[^"\n]*"')
        self.assertRegex(metadata, r"allow_implicit_invocation:\s*false")

    def test_good_example_is_compact_and_has_layered_output(self) -> None:
        example = read(GOOD_EXAMPLE_PATH)
        code_match = PYTHON_FENCE_RE.search(example)
        self.assertIsNotNone(code_match)
        assert code_match is not None
        code_line_count = len(code_match.group("code").splitlines())
        self.assertGreaterEqual(code_line_count, 20)
        self.assertLessEqual(code_line_count, 40)
        for phase in ("# 一句话说明", "# 核心流程", "# 代码详细分析"):
            self.assertIn(phase, example)
        module_count = len(re.findall(r"^## 模块[一二三四五六七八九十]+：", example, re.MULTILINE))
        self.assertGreaterEqual(module_count, 2)
        self.assertLessEqual(module_count, 3)
        self.assertLessEqual(len(example.splitlines()), 135)
        self.assertIn("## 文件模块地图", example)
        self.assertNotIn("| 展开状态 |", example)

    def test_good_example_core_steps_have_scannable_summaries(self) -> None:
        example = read(GOOD_EXAMPLE_PATH)
        flow_match = CORE_FLOW_RE.search(example)
        self.assertIsNotNone(flow_match)
        assert flow_match is not None
        steps = tuple(
            line
            for line in flow_match.group("body").splitlines()
            if re.match(r"^\d+\. ", line)
        )
        self.assertGreaterEqual(len(steps), 3)
        self.assertLessEqual(len(steps), 8)
        for step in steps:
            with self.subTest(step=step):
                self.assertRegex(step, SUMMARIZED_STEP_RE)

    def test_v1_has_no_runtime_script_asset_or_plugin(self) -> None:
        self.assertFalse((SKILL_DIR / "scripts").exists())
        self.assertFalse((SKILL_DIR / "assets").exists())
        self.assertFalse((ROOT / "plugins" / "analyze_code.py").exists())

    def test_runtime_instructions_remain_context_efficient(self) -> None:
        self.assertLessEqual(len(read(SKILL_PATH).splitlines()), 100)
        self.assertLessEqual(len(read(OUTPUT_CONTRACT_PATH).splitlines()), 130)
        self.assertLessEqual(len(read(GUIDELINES_PATH).splitlines()), 100)


if __name__ == "__main__":
    unittest.main()
