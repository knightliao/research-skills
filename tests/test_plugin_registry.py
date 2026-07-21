"""插件 Registry 和 radar 插件边界测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from plugins import global_ai_agent_radar as radar_plugin
from skill_framework import codes
from skill_framework.models import SkillContext, ValidationResult
from skill_framework.registry import discover_plugins, load_plugin_for_skill, run_plugin


VALID_PLUGIN = """from skill_framework.models import ValidationResult
PLUGIN_API_VERSION = 1
SKILL_NAME = {skill_name!r}
def validate(context):
    return ValidationResult()
"""


class PluginRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.plugin_dir = self.root / "plugins"
        self.plugin_dir.mkdir()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_plugin(self, filename: str, content: str) -> Path:
        path = self.plugin_dir / filename
        path.write_text(content, encoding="utf-8")
        return path

    def test_discovery_order_is_stable(self) -> None:
        self.write_plugin("zeta.py", VALID_PLUGIN.format(skill_name="zeta"))
        self.write_plugin("alpha.py", VALID_PLUGIN.format(skill_name="alpha"))
        result = discover_plugins(self.plugin_dir)
        self.assertTrue(result.result.is_valid)
        self.assertEqual(("alpha", "zeta"), tuple(plugin.skill_name for plugin in result.plugins))

    def test_target_load_does_not_import_unrelated_broken_plugin(self) -> None:
        self.write_plugin("target_skill.py", VALID_PLUGIN.format(skill_name="target-skill"))
        self.write_plugin("broken_skill.py", "raise RuntimeError('TEST BROKEN PLUGIN')\n")
        loaded = load_plugin_for_skill(self.plugin_dir, "target-skill")
        self.assertTrue(loaded.result.is_valid)
        self.assertEqual("target-skill", loaded.plugin.skill_name if loaded.plugin else None)

    def test_missing_plugin_is_valid(self) -> None:
        loaded = load_plugin_for_skill(self.plugin_dir, "no-plugin")
        self.assertIsNone(loaded.plugin)
        self.assertTrue(loaded.result.is_valid)

    def test_unsupported_api_version_has_stable_code(self) -> None:
        content = VALID_PLUGIN.format(skill_name="sample-skill").replace(
            "PLUGIN_API_VERSION = 1", "PLUGIN_API_VERSION = 2"
        )
        self.write_plugin("sample_skill.py", content)
        loaded = load_plugin_for_skill(self.plugin_dir, "sample-skill")
        self.assertIn(codes.PLUGIN_API_VERSION_UNSUPPORTED, {issue.code for issue in loaded.result.errors})

    def test_filename_and_declared_name_mismatch_fails(self) -> None:
        self.write_plugin("sample_skill.py", VALID_PLUGIN.format(skill_name="other-skill"))
        loaded = load_plugin_for_skill(self.plugin_dir, "sample-skill")
        self.assertIn(codes.PLUGIN_NAME_MISMATCH, {issue.code for issue in loaded.result.errors})

    def test_duplicate_claims_are_reported(self) -> None:
        self.write_plugin("sample_skill.py", VALID_PLUGIN.format(skill_name="sample-skill"))
        self.write_plugin("alias.py", VALID_PLUGIN.format(skill_name="sample-skill"))
        discovered = discover_plugins(self.plugin_dir)
        codes_found = [issue.code for issue in discovered.result.errors]
        self.assertIn(codes.PLUGIN_NAME_MISMATCH, codes_found)
        self.assertIn(codes.PLUGIN_DUPLICATE, codes_found)

    def test_import_exception_is_isolated(self) -> None:
        self.write_plugin("broken.py", "raise RuntimeError('TEST IMPORT FAILURE')\n")
        discovered = discover_plugins(self.plugin_dir)
        self.assertIn(codes.PLUGIN_IMPORT_FAILED, {issue.code for issue in discovered.result.errors})

    def test_invalid_plugin_return_type_fails(self) -> None:
        content = VALID_PLUGIN.format(skill_name="sample-skill").replace(
            "return ValidationResult()", "return None"
        )
        self.write_plugin("sample_skill.py", content)
        loaded = load_plugin_for_skill(self.plugin_dir, "sample-skill")
        assert loaded.plugin is not None
        context = SkillContext(self.root, self.root / "sample-skill", "sample-skill")
        result = run_plugin(loaded.plugin, context)
        self.assertIn(codes.PLUGIN_INVALID_RESULT, {issue.code for issue in result.errors})

    def test_plugin_result_is_independent(self) -> None:
        context = SkillContext(
            ROOT,
            ROOT / ".agents" / "skills" / "global-ai-agent-radar",
            "global-ai-agent-radar",
        )
        first = radar_plugin.validate(context)
        second = radar_plugin.validate(context)
        self.assertIsInstance(first, ValidationResult)
        self.assertIsNot(first, second)
        self.assertTrue(first.is_valid, [issue.render() for issue in first.errors])


ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    unittest.main()
