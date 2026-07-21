"""单个 Skill 打包工具及端到端冒烟流程测试。"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path, PurePosixPath

from skill_framework import packaging as package_tool
from tests.repository_fixture import copy_repository_fixture

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_TOOL_PATH = ROOT / "tools" / "package_skill.py"
EVENT_VALIDATOR_PATH = (
    ROOT
    / ".agents"
    / "skills"
    / "global-ai-agent-radar"
    / "scripts"
    / "validate_events.py"
)


VALID_SKILL = """---
name: sample-skill
description: 用于测试 ZIP 打包流程的虚构 Skill。
---

# 示例 Skill

## 目标

验证打包行为。

## 适用场景

用于自动化测试。

## 不适用场景

不用于真实研究。

## 输入与默认值

使用虚构输入。

## 需要按需读取的参考文件

读取[虚构规则](references/rule.md)。

## 执行工作流

执行确定性测试步骤。

## 输出要求

输出虚构结果。

## 硬性工作规范

不访问网络。

## 完成前质量检查

检查 ZIP 内容。
"""


class TemporaryPackageRepository:
    """创建带有完整目录类型的最小合法 Skill 仓库。"""

    def __init__(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.skill_name = "sample-skill"
        self.skill_dir = self.root / ".agents" / "skills" / self.skill_name
        self.output_dir = self.root / "package-output"
        self.skill_dir.mkdir(parents=True)
        (self.skill_dir / "SKILL.md").write_text(VALID_SKILL, encoding="utf-8")

        files = {
            "references/rule.md": "# 虚构规则\n\n仅用于自动化测试。\n",
            "examples/example.md": "# 虚构示例\n\n不是当前新闻。\n",
            "assets/template.md": "# 虚构模板\n",
            "scripts/check.py": "import json\n\nprint(json.dumps({'ok': True}))\n",
        }
        for relative_path, content in files.items():
            path = self.skill_dir / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    @property
    def output_path(self) -> Path:
        return self.output_dir / f"{self.skill_name}.zip"

    def package(self):
        return package_tool.create_skill_archive(
            self.skill_name,
            repository_root=self.root,
            output_dir=self.output_dir,
        )

    def close(self) -> None:
        self.temporary_directory.cleanup()


class PackageSkillTests(unittest.TestCase):
    repository: TemporaryPackageRepository

    def setUp(self) -> None:
        self.repository = TemporaryPackageRepository()

    def tearDown(self) -> None:
        self.repository.close()

    def archive_names(self) -> list[str]:
        with zipfile.ZipFile(self.repository.output_path) as archive:
            return archive.namelist()

    def source_snapshot(self) -> dict[str, str]:
        snapshot: dict[str, str] = {}
        for path in sorted(self.repository.skill_dir.rglob("*")):
            if path.is_file() and not path.is_symlink():
                relative = path.relative_to(self.repository.skill_dir).as_posix()
                snapshot[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        return snapshot

    def test_valid_skill_can_be_packaged(self) -> None:
        result = self.repository.package()
        self.assertEqual(self.repository.output_path.resolve(), result.output_path)
        self.assertTrue(result.output_path.is_file())
        self.assertGreater(result.size_bytes, 0)
        self.assertEqual(5, result.file_count)

    def test_archive_has_only_one_top_level_directory(self) -> None:
        self.repository.package()
        top_levels = {PurePosixPath(name).parts[0] for name in self.archive_names()}
        self.assertEqual({self.repository.skill_name}, top_levels)

    def test_archive_top_level_matches_skill_name(self) -> None:
        self.repository.package()
        for name in self.archive_names():
            self.assertTrue(name.startswith(f"{self.repository.skill_name}/"), name)

    def test_archive_contains_skill_entry_file(self) -> None:
        self.repository.package()
        self.assertIn("sample-skill/SKILL.md", self.archive_names())

    def test_archive_contains_all_supported_directories(self) -> None:
        self.repository.package()
        names = set(self.archive_names())
        self.assertTrue(
            {
                "sample-skill/references/rule.md",
                "sample-skill/examples/example.md",
                "sample-skill/assets/template.md",
                "sample-skill/scripts/check.py",
            }.issubset(names)
        )

    def test_ds_store_is_excluded(self) -> None:
        (self.repository.skill_dir / ".DS_Store").write_bytes(b"test metadata")
        self.repository.package()
        self.assertFalse(any(name.endswith(".DS_Store") for name in self.archive_names()))

    def test_python_cache_and_pyc_are_excluded(self) -> None:
        cache_dir = self.repository.skill_dir / "scripts" / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "check.cpython-311.pyc").write_bytes(b"test bytecode placeholder")
        (self.repository.skill_dir / "scripts" / "legacy.pyc").write_bytes(
            b"test bytecode placeholder"
        )
        self.repository.package()
        names = self.archive_names()
        self.assertFalse(any("__pycache__" in name or name.endswith(".pyc") for name in names))

    def test_missing_skill_file_prevents_archive(self) -> None:
        (self.repository.skill_dir / "SKILL.md").unlink()
        with self.assertRaises(package_tool.PackageError):
            self.repository.package()
        self.assertFalse(self.repository.output_path.exists())

    def test_validation_failure_prevents_archive(self) -> None:
        skill_file = self.repository.skill_dir / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8").replace(
            "name: sample-skill",
            "name: wrong-skill",
        )
        skill_file.write_text(content, encoding="utf-8")
        with self.assertRaisesRegex(package_tool.PackageError, "Skill 校验失败"):
            self.repository.package()
        self.assertFalse(self.repository.output_path.exists())

    def test_missing_skill_name_returns_nonzero(self) -> None:
        process = subprocess.run(
            [
                sys.executable,
                str(PACKAGE_TOOL_PATH),
                "missing-skill",
                "--repository",
                str(self.repository.root),
                "--output-dir",
                str(self.repository.output_dir),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(0, process.returncode)
        self.assertIn("Skill 不存在", process.stderr)

    def test_skill_option_form_can_package(self) -> None:
        process = subprocess.run(
            [
                sys.executable,
                str(PACKAGE_TOOL_PATH),
                "--skill",
                self.repository.skill_name,
                "--repository",
                str(self.repository.root),
                "--output-dir",
                str(self.repository.output_dir),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertTrue(self.repository.output_path.exists())
        self.assertIn("文件数量：5", process.stdout)

    def test_archive_can_be_read_by_zipfile(self) -> None:
        self.repository.package()
        with zipfile.ZipFile(self.repository.output_path) as archive:
            self.assertIsNone(archive.testzip())

    def test_packaging_does_not_modify_source_skill(self) -> None:
        before = self.source_snapshot()
        self.repository.package()
        after = self.source_snapshot()
        self.assertEqual(before, after)

    def test_unrelated_broken_plugin_does_not_block_target_package(self) -> None:
        plugins = self.repository.root / "plugins"
        plugins.mkdir()
        (plugins / "unrelated_skill.py").write_text(
            "raise RuntimeError('TEST UNRELATED BROKEN PLUGIN')\n",
            encoding="utf-8",
        )
        result = self.repository.package()
        self.assertTrue(result.output_path.is_file())

    def test_target_plugin_failure_prevents_archive(self) -> None:
        plugins = self.repository.root / "plugins"
        plugins.mkdir()
        (plugins / "sample_skill.py").write_text(
            """from skill_framework.models import Issue, ValidationResult
PLUGIN_API_VERSION = 1
SKILL_NAME = "sample-skill"
def validate(context):
    return ValidationResult(errors=(Issue("sample.failure", "SKILL.md", "测试失败"),))
""",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(package_tool.PackageError, "sample.failure"):
            self.repository.package()
        self.assertFalse(self.repository.output_path.exists())

    def test_package_cli_runs_from_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as other_directory:
            process = subprocess.run(
                [
                    sys.executable,
                    str(PACKAGE_TOOL_PATH),
                    self.repository.skill_name,
                    "--repository",
                    str(self.repository.root),
                    "--output-dir",
                    str(self.repository.output_dir),
                ],
                cwd=other_directory,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertTrue(self.repository.output_path.is_file())

    @unittest.skipUnless(hasattr(os, "symlink"), "平台不支持符号链接")
    def test_external_symlink_prevents_archive(self) -> None:
        outside = self.repository.root / "outside.md"
        outside.write_text("Skill 目录外的测试文件", encoding="utf-8")
        os.symlink(outside, self.repository.skill_dir / "references" / "outside.md")
        with self.assertRaisesRegex(package_tool.PackageError, "Skill 校验失败"):
            self.repository.package()
        self.assertFalse(self.repository.output_path.exists())


class EndToEndSmokeTests(unittest.TestCase):
    def test_all_repository_skills_can_be_discovered_and_packaged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory) / "repository"
            copy_repository_fixture(ROOT, repository_root)
            skill_dirs = sorted(
                path for path in (repository_root / ".agents" / "skills").iterdir() if path.is_dir()
            )
            self.assertTrue(skill_dirs)
            output_dir = Path(temporary_directory) / "dist"
            for skill_dir in skill_dirs:
                result = package_tool.package_skill(
                    skill_dir.name,
                    repository_root=repository_root,
                    output_dir=output_dir,
                )
                with zipfile.ZipFile(result.output_path) as archive:
                    self.assertIsNone(archive.testzip())
                    self.assertIn(f"{skill_dir.name}/SKILL.md", archive.namelist())

    def test_validate_cli_runs_from_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            repository_root = temporary_path / "repository"
            other_directory = temporary_path / "outside"
            other_directory.mkdir()
            copy_repository_fixture(ROOT, repository_root)
            process = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "validate_all_skills.py"),
                    str(repository_root),
                ],
                cwd=other_directory,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertIn("校验通过", process.stdout)

    def test_global_radar_validation_and_packaging_smoke(self) -> None:
        valid_event = {
            "title": "ExampleAI 虚构 Agent 工作流更新",
            "event_date": "2026-01-10",
            "publication_date": "2026-01-10",
            "source_url": "https://example.invalid/exampleai/fictional-release",
            "source_type": "official",
            "facts": ["这是端到端测试使用的虚构事实。"],
            "inference": "这是端到端测试使用的虚构推断。",
            "scores": {
                "novelty": 4,
                "product_impact": 4,
                "engineering_impact": 4,
                "commercialization_impact": 3,
                "ecosystem_impact": 3,
                "credibility": 5,
            },
            "total_score": 23,
            "confidence": "high",
            "follow_up_signals": ["检查虚构产品后续公开文档。"],
        }
        invalid_event = dict(valid_event)
        invalid_event["title"] = "ExampleAI 虚构非法事件"
        invalid_event["event_date"] = "2026-02-30"

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            repository_root = temporary_path / "repository"
            copy_repository_fixture(ROOT, repository_root)
            valid_path = temporary_path / "valid-events.json"
            invalid_path = temporary_path / "invalid-events.json"
            valid_path.write_text(json.dumps(valid_event, ensure_ascii=False), encoding="utf-8")
            invalid_path.write_text(json.dumps(invalid_event, ensure_ascii=False), encoding="utf-8")

            valid_process = subprocess.run(
                [sys.executable, str(EVENT_VALIDATOR_PATH), str(valid_path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            invalid_process = subprocess.run(
                [sys.executable, str(EVENT_VALIDATOR_PATH), str(invalid_path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            repository_process = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "validate_all_skills.py"),
                    str(repository_root),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            package_result = package_tool.create_skill_archive(
                "global-ai-agent-radar",
                repository_root=repository_root,
                output_dir=temporary_path / "dist",
            )

            self.assertEqual(0, valid_process.returncode, valid_process.stderr)
            self.assertNotEqual(0, invalid_process.returncode)
            self.assertEqual(0, repository_process.returncode, repository_process.stderr)
            with zipfile.ZipFile(package_result.output_path) as archive:
                self.assertIsNone(archive.testzip())
                self.assertIn("global-ai-agent-radar/SKILL.md", archive.namelist())


if __name__ == "__main__":
    unittest.main()
