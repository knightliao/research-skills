"""global-ai-agent-radar 插件专属规则测试。"""

from __future__ import annotations

import csv
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

from skill_framework.models import SkillContext


ROOT = Path(__file__).resolve().parents[2]
PLUGIN_PATH = ROOT / "plugins" / "global_ai_agent_radar.py"


def load_radar_plugin():
    spec = importlib.util.spec_from_file_location("_radar_plugin_under_test", PLUGIN_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 global_ai_agent_radar 插件")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


radar_plugin = load_radar_plugin()

VALID_SKILL = """---
name: sample-skill
description: 虚构测试 Skill。
---

# 示例

## 目标
## 适用场景
## 不适用场景
## 输入与默认值
## 需要按需读取的参考文件
## 执行工作流
## 输出要求
## 硬性工作规范
## 完成前质量检查
"""

WATCHLIST_ROW = (
    "sample-project", "Sample Project", "project", "开源新项目", "全球",
    "用于测试观察池校验", "https://example.com/sample", "primary", "medium",
    "active", "", "明确的测试数据",
)


class RadarPluginTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.skill_dir = self.root / ".agents" / "skills" / "sample-skill"
        self.skill_dir.mkdir(parents=True)
        self.skill_file = self.skill_dir / "SKILL.md"
        self.skill_file.write_text(VALID_SKILL, encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_watchlist(
        self,
        rows: list[tuple[str, ...]],
        *,
        header: tuple[str, ...] | None = None,
    ) -> Path:
        path = self.skill_dir / "assets" / "watchlist.csv"
        path.parent.mkdir(exist_ok=True)
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(header or radar_plugin.WATCHLIST_HEADER)
        writer.writerows(rows)
        path.write_text(buffer.getvalue(), encoding="utf-8")
        return path

    def validate_watchlist(self):
        return radar_plugin.validate_watchlist(
            self.skill_dir / "assets" / "watchlist.csv",
            self.root,
        )

    def assert_error_contains(self, result, fragment: str) -> None:
        rendered = "\n".join(issue.render() for issue in result.errors)
        self.assertIn(fragment, rendered, rendered)


class RadarSemanticTests(RadarPluginTestCase):
    def test_missing_required_section_fails(self) -> None:
        self.skill_file.write_text(VALID_SKILL.replace("## 目标", "## 概览"), encoding="utf-8")
        result = radar_plugin.validate_skill_semantics(
            SkillContext(self.root, self.skill_dir, "sample-skill")
        )
        self.assert_error_contains(result, "缺少必需语义章节：目标")


class WatchlistTests(RadarPluginTestCase):
    def test_valid_watchlist_passes(self) -> None:
        self.write_watchlist([WATCHLIST_ROW])
        self.assertTrue(self.validate_watchlist().is_valid)

    def test_wrong_header_fails(self) -> None:
        self.write_watchlist([WATCHLIST_ROW[:-1]], header=radar_plugin.WATCHLIST_HEADER[:-1])
        self.assert_error_contains(self.validate_watchlist(), "CSV 表头")

    def test_duplicate_entity_id_fails(self) -> None:
        second = list(WATCHLIST_ROW)
        second[1] = "Another Project"
        self.write_watchlist([WATCHLIST_ROW, tuple(second)])
        self.assert_error_contains(self.validate_watchlist(), "entity_id 重复")

    def test_invalid_entity_type_fails(self) -> None:
        row = list(WATCHLIST_ROW)
        row[2] = "service"
        self.write_watchlist([tuple(row)])
        self.assert_error_contains(self.validate_watchlist(), "entity_type 枚举值无效")

    def test_invalid_tracking_priority_fails(self) -> None:
        row = list(WATCHLIST_ROW)
        row[8] = "urgent"
        self.write_watchlist([tuple(row)])
        self.assert_error_contains(self.validate_watchlist(), "tracking_priority 枚举值无效")

    def test_invalid_status_fails(self) -> None:
        row = list(WATCHLIST_ROW)
        row[9] = "archived"
        self.write_watchlist([tuple(row)])
        self.assert_error_contains(self.validate_watchlist(), "status 枚举值无效")

    def test_invalid_url_fails(self) -> None:
        row = list(WATCHLIST_ROW)
        row[6] = "ftp://example.com/sample"
        self.write_watchlist([tuple(row)])
        self.assert_error_contains(self.validate_watchlist(), "official_url")

    def test_invalid_last_reviewed_fails(self) -> None:
        row = list(WATCHLIST_ROW)
        row[10] = "2026-02-30"
        self.write_watchlist([tuple(row)])
        self.assert_error_contains(self.validate_watchlist(), "last_reviewed")

    def test_removed_without_notes_warns(self) -> None:
        row = list(WATCHLIST_ROW)
        row[9] = "removed"
        row[11] = ""
        self.write_watchlist([tuple(row)])
        result = self.validate_watchlist()
        self.assertTrue(result.is_valid)
        self.assertIn("removed 状态条目的 notes", "\n".join(i.render() for i in result.warnings))


if __name__ == "__main__":
    unittest.main()
