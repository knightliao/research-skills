"""插件 Registry 和 radar 插件边界测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from skill_framework import codes
from skill_framework.models import SkillContext, ValidationResult
from skill_framework.registry import discover_plugins, load_plugin_for_skill, run_plugin
from skill_framework.repository import validate_repository


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

    def write_skill(self, skill_name: str) -> Path:
        skill_dir = self.root / ".agents" / "skills" / skill_name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {skill_name}\ndescription: 虚构插件测试 Skill。\n---\n\n# 测试\n",
            encoding="utf-8",
        )
        return skill_dir

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

    def test_missing_validate_hook_fails(self) -> None:
        content = VALID_PLUGIN.format(skill_name="sample-skill").replace(
            "def validate(context):\n    return ValidationResult()\n", ""
        )
        self.write_plugin("sample_skill.py", content)
        loaded = load_plugin_for_skill(self.plugin_dir, "sample-skill")
        self.assertIn(codes.PLUGIN_INVALID_INTERFACE, {issue.code for issue in loaded.result.errors})

    def test_plugin_execution_exception_is_isolated(self) -> None:
        content = VALID_PLUGIN.format(skill_name="sample-skill").replace(
            "return ValidationResult()", "raise RuntimeError('TEST EXECUTION FAILURE')"
        )
        self.write_plugin("sample_skill.py", content)
        loaded = load_plugin_for_skill(self.plugin_dir, "sample-skill")
        assert loaded.plugin is not None
        result = run_plugin(
            loaded.plugin,
            SkillContext(self.root, self.root / "sample-skill", "sample-skill"),
        )
        self.assertIn(codes.PLUGIN_EXECUTION_FAILED, {issue.code for issue in result.errors})

    def test_orphaned_plugin_fails_repository_validation(self) -> None:
        self.write_skill("existing-skill")
        self.write_plugin("orphan_skill.py", VALID_PLUGIN.format(skill_name="orphan-skill"))
        validation = validate_repository(self.root)
        self.assertIn(codes.PLUGIN_ORPHANED, {issue.code for issue in validation.errors})

    def test_one_broken_plugin_does_not_stop_other_plugin_execution(self) -> None:
        self.write_skill("broken-skill")
        self.write_skill("working-skill")
        self.write_plugin("broken_skill.py", "raise RuntimeError('TEST BROKEN IMPORT')\n")
        self.write_plugin(
            "working_skill.py",
            """from skill_framework.models import Issue, ValidationResult
PLUGIN_API_VERSION = 1
SKILL_NAME = "working-skill"
def validate(context):
    return ValidationResult(warnings=(Issue("working.checked", "SKILL.md", "已执行"),))
""",
        )
        validation = validate_repository(self.root)
        self.assertIn(codes.PLUGIN_IMPORT_FAILED, {issue.code for issue in validation.errors})
        self.assertIn("working.checked", {issue.code for issue in validation.warnings})

    def test_plugin_result_is_independent(self) -> None:
        context = SkillContext(
            ROOT,
            ROOT / ".agents" / "skills" / "global-ai-agent-radar",
            "global-ai-agent-radar",
        )
        loaded = load_plugin_for_skill(ROOT / "plugins", "global-ai-agent-radar")
        assert loaded.plugin is not None
        first = run_plugin(loaded.plugin, context)
        second = run_plugin(loaded.plugin, context)
        self.assertIsInstance(first, ValidationResult)
        self.assertIsNot(first, second)
        self.assertTrue(first.is_valid, [issue.render() for issue in first.errors])


ROOT = Path(__file__).resolve().parents[2]


if __name__ == "__main__":
    unittest.main()
