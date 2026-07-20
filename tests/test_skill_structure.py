from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / ".agents" / "skills"
REQUIRED_FILES = {
    "SKILL.md",
    "references/source-policy.md",
    "references/scoring-rubric.md",
    "references/deduplication-policy.md",
    "references/company-watchlist.md",
    "examples/good-report.md",
    "examples/bad-report.md",
    "examples/no-major-change-report.md",
    "assets/report-template.md",
    "assets/watchlist.csv",
    "scripts/validate_events.py",
}


class SkillStructureTests(unittest.TestCase):
    def test_expected_skill_files_exist(self) -> None:
        skill_dir = SKILLS_DIR / "global-ai-agent-radar"
        missing = sorted(
            relative_path
            for relative_path in REQUIRED_FILES
            if not (skill_dir / relative_path).is_file()
        )
        self.assertEqual([], missing)

    def test_every_skill_has_skill_md(self) -> None:
        skill_dirs = sorted(path for path in SKILLS_DIR.iterdir() if path.is_dir())
        self.assertTrue(skill_dirs, "expected at least one Skill")
        for skill_dir in skill_dirs:
            with self.subTest(skill=skill_dir.name):
                self.assertTrue((skill_dir / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
