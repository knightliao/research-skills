"""skill_framework 通用内核的首阶段测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from skill_framework import codes
from skill_framework.models import Issue, SkillContext, ValidationResult
from skill_framework.repository import validate_repository_common
from skill_framework.validator import validate_skill


ROOT = Path(__file__).resolve().parents[2]

VALID_SKILL = """---
name: sample-skill
description: 通用框架测试使用的虚构 Skill。
---

# Sample Skill

[本地规则](references/rule.md)
"""


class ValidationResultTests(unittest.TestCase):
    def test_merge_preserves_order_without_mutating_inputs(self) -> None:
        first = ValidationResult(errors=(Issue("first", "a", "A"),))
        second = ValidationResult(warnings=(Issue("second", "b", "B"),))
        merged = ValidationResult.merge(first, second)
        self.assertEqual(("first",), tuple(issue.code for issue in merged.errors))
        self.assertEqual(("second",), tuple(issue.code for issue in merged.warnings))
        self.assertEqual(1, len(first.errors))
        self.assertFalse(first.warnings)

    def test_results_and_issues_are_immutable(self) -> None:
        issue = Issue("test.code", "file", "message")
        result = ValidationResult(errors=(issue,))
        with self.assertRaises(FrozenInstanceError):
            issue.message = "changed"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            result.errors = ()  # type: ignore[misc]

    def test_render_includes_stable_code(self) -> None:
        issue = Issue("test.code", "file.md", "测试问题", line=3)
        self.assertEqual("[test.code] file.md:3：测试问题", issue.render())


class CommonFrameworkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.skill_dir = self.root / ".agents" / "skills" / "sample-skill"
        (self.skill_dir / "references").mkdir(parents=True)
        (self.skill_dir / "SKILL.md").write_text(VALID_SKILL, encoding="utf-8")
        (self.skill_dir / "references" / "rule.md").write_text("# 规则\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_valid_skill_passes_without_domain_sections(self) -> None:
        result = validate_skill(SkillContext(self.root, self.skill_dir, "sample-skill"))
        self.assertTrue(result.is_valid, [issue.render() for issue in result.errors])

    def test_missing_entry_has_stable_code(self) -> None:
        (self.skill_dir / "SKILL.md").unlink()
        result = validate_skill(SkillContext(self.root, self.skill_dir, "sample-skill"))
        self.assertIn(codes.SKILL_MISSING_ENTRY, {issue.code for issue in result.errors})

    def test_missing_reference_has_stable_code(self) -> None:
        (self.skill_dir / "references" / "rule.md").unlink()
        result = validate_skill(SkillContext(self.root, self.skill_dir, "sample-skill"))
        self.assertIn(codes.MARKDOWN_REFERENCE_MISSING, {issue.code for issue in result.errors})

    def test_framework_does_not_depend_on_current_working_directory(self) -> None:
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as other_directory:
            try:
                os.chdir(other_directory)
                validation = validate_repository_common(self.root)
            finally:
                os.chdir(previous)
        self.assertTrue(validation.is_valid, [issue.render() for issue in validation.errors])


if __name__ == "__main__":
    unittest.main()
