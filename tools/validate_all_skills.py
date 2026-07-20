#!/usr/bin/env python3
"""Validate the required structure of every repository Skill."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / ".agents" / "skills"


def validate_skill(skill_dir: Path) -> list[str]:
    """Return structural errors for one Skill directory."""
    errors: list[str] = []
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        errors.append(f"{skill_dir.relative_to(ROOT)}: missing SKILL.md")
    return errors


def main() -> int:
    if not SKILLS_DIR.is_dir():
        print(".agents/skills: directory is missing")
        return 1

    skill_dirs = sorted(path for path in SKILLS_DIR.iterdir() if path.is_dir())
    if not skill_dirs:
        print(".agents/skills: no Skills found")
        return 1

    errors = [error for skill_dir in skill_dirs for error in validate_skill(skill_dir)]
    if errors:
        print("\n".join(errors))
        return 1

    print(f"Validated {len(skill_dirs)} Skill(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
