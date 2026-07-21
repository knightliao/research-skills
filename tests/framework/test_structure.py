"""仓库级 Skill 校验工具的自动化测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from skill_framework.repository import validate_repository
from skill_framework.security import scan_sensitive_information
from tests.repository_fixture import copy_repository_fixture

ROOT = Path(__file__).resolve().parents[2]

VALID_SKILL = """---
name: sample-skill
description: 用于自动化测试的示例 Skill。
---

# 示例 Skill

## 目标

验证结构。

## 适用场景

用于测试。

## 不适用场景

不用于生产。

## 输入与默认值

使用默认输入。

## 需要按需读取的参考文件

按需读取。

## 执行工作流

执行确定性步骤。

## 输出要求

输出测试结果。

## 硬性工作规范

不得访问网络。

## 完成前质量检查

运行测试。
"""

class TemporarySkillRepository:
    """为每个测试创建隔离且可重复的最小 Skill 仓库。"""

    def __init__(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.skill_dir = self.root / ".agents" / "skills" / "sample-skill"
        self.skill_dir.mkdir(parents=True)
        self.skill_file = self.skill_dir / "SKILL.md"
        self.skill_file.write_text(VALID_SKILL, encoding="utf-8")

    def close(self) -> None:
        self.temporary_directory.cleanup()

class RepositoryTestCase(unittest.TestCase):
    """提供临时仓库生命周期和常用断言。"""

    repository: TemporarySkillRepository

    def setUp(self) -> None:
        self.repository = TemporarySkillRepository()

    def tearDown(self) -> None:
        self.repository.close()

    def validate(self):
        return validate_repository(self.repository.root)

    def assert_has_error(self, report, fragment: str) -> None:
        messages = "\n".join(issue.render() for issue in report.errors)
        self.assertIn(fragment, messages, messages)


class SkillStructureTests(RepositoryTestCase):
    def test_current_repository_sources_pass_in_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            copied_root = Path(temporary_directory)
            copy_repository_fixture(ROOT, copied_root)
            report = validate_repository(copied_root)
        self.assertTrue(
            report.is_valid,
            "\n".join(issue.render() for issue in report.errors),
        )

    def test_ds_store_fails_validation(self) -> None:
        (self.repository.root / ".DS_Store").write_bytes(b"test macOS metadata placeholder")
        report = self.validate()
        self.assertIn("path.ds_store", {issue.code for issue in report.errors})

    def test_missing_skill_file_fails(self) -> None:
        self.repository.skill_file.unlink()
        report = self.validate()
        self.assert_has_error(report, "缺少入口文件 SKILL.md")

    def test_empty_skill_file_fails(self) -> None:
        self.repository.skill_file.write_text("", encoding="utf-8")
        report = self.validate()
        self.assert_has_error(report, "Markdown 文件不得为空")

    def test_frontmatter_without_name_fails(self) -> None:
        content = VALID_SKILL.replace("name: sample-skill\n", "")
        self.repository.skill_file.write_text(content, encoding="utf-8")
        report = self.validate()
        self.assert_has_error(report, "缺少非空字段 name")

    def test_frontmatter_without_description_fails(self) -> None:
        content = VALID_SKILL.replace("description: 用于自动化测试的示例 Skill。\n", "")
        self.repository.skill_file.write_text(content, encoding="utf-8")
        report = self.validate()
        self.assert_has_error(report, "缺少非空字段 description")

    def test_frontmatter_name_mismatch_fails(self) -> None:
        content = VALID_SKILL.replace("name: sample-skill", "name: another-skill")
        self.repository.skill_file.write_text(content, encoding="utf-8")
        report = self.validate()
        self.assert_has_error(report, "与目录名 sample-skill 不一致")

    def test_missing_local_reference_fails(self) -> None:
        content = VALID_SKILL + "\n[缺失规则](references/missing.md)\n"
        self.repository.skill_file.write_text(content, encoding="utf-8")
        report = self.validate()
        self.assert_has_error(report, "本地引用不存在")

    def test_parent_reference_escaping_skill_fails(self) -> None:
        outside = self.repository.root / ".agents" / "outside.md"
        outside.write_text("测试文件", encoding="utf-8")
        content = VALID_SKILL + "\n[越界文件](../../outside.md)\n"
        self.repository.skill_file.write_text(content, encoding="utf-8")
        report = self.validate()
        self.assert_has_error(report, "本地引用逃逸 Skill 目录")

    def test_remote_url_and_page_anchor_are_ignored(self) -> None:
        content = VALID_SKILL + "\n[官网](https://example.com/docs) [章节](#目标)\n"
        self.repository.skill_file.write_text(content, encoding="utf-8")
        report = self.validate()
        self.assertTrue(report.is_valid, "\n".join(issue.render() for issue in report.errors))

    def test_gitignored_python_caches_do_not_fail_validation(self) -> None:
        (self.repository.root / ".gitignore").write_text(
            "__pycache__/\n*.py[cod]\n",
            encoding="utf-8",
        )
        for parent in (
            self.repository.root / "tools",
            self.repository.root / "tests",
            self.repository.skill_dir / "scripts",
        ):
            cache_dir = parent / "__pycache__"
            cache_dir.mkdir(parents=True)
            (cache_dir / "module.cpython-311.pyc").write_bytes(b"test bytecode placeholder")
        report = self.validate()
        self.assertTrue(report.is_valid, "\n".join(issue.render() for issue in report.errors))

    def test_unignored_python_cache_fails_validation(self) -> None:
        cache_dir = self.repository.root / "tools" / "__pycache__"
        cache_dir.mkdir(parents=True)
        (cache_dir / "module.cpython-311.pyc").write_bytes(b"test bytecode placeholder")
        report = self.validate()
        self.assert_has_error(report, "未被 .gitignore 排除的 __pycache__")


class SensitiveInformationTests(RepositoryTestCase):
    def test_ordinary_text_does_not_trigger_secret_scan(self) -> None:
        (self.repository.root / "README.md").write_text(
            "文档可以讨论 API Key，但这里没有任何凭据值。",
            encoding="utf-8",
        )
        report = scan_sensitive_information(self.repository.root)
        self.assertFalse(report.errors)

    def test_high_confidence_credential_pattern_is_detected(self) -> None:
        fake_test_key = "AKIA" + "Z" * 16
        (self.repository.root / "credential-test-data.txt").write_text(
            f"仅用于自动化测试，不是真实凭据：{fake_test_key}\n",
            encoding="utf-8",
        )
        report = scan_sensitive_information(self.repository.root)
        self.assertTrue(report.errors)
        self.assertIn("AWS access key", report.errors[0].message)

    def test_secret_output_is_redacted(self) -> None:
        fake_test_key = "AKIA" + "Y" * 16
        (self.repository.root / "credential-test-data.txt").write_text(
            f"TEST DATA ONLY: {fake_test_key}\n",
            encoding="utf-8",
        )
        report = scan_sensitive_information(self.repository.root)
        output = "\n".join(issue.render() for issue in report.errors)
        self.assertNotIn(fake_test_key, output)
        self.assertIn("…", output)

    def test_git_and_cache_directories_are_ignored_by_secret_scan(self) -> None:
        fake_test_key = "AKIA" + "X" * 16
        git_dir = self.repository.root / ".git"
        cache_dir = self.repository.root / "__pycache__"
        git_dir.mkdir()
        cache_dir.mkdir()
        (git_dir / "secret.txt").write_text(fake_test_key, encoding="utf-8")
        (cache_dir / "secret.txt").write_text(fake_test_key, encoding="utf-8")
        report = scan_sensitive_information(self.repository.root)
        self.assertFalse(report.errors)


if __name__ == "__main__":
    unittest.main()
