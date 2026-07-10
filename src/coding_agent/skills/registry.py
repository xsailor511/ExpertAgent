from __future__ import annotations

from pathlib import Path
from typing import Any

from coding_agent.skills.frontmatter import parse_frontmatter

SKILLS_DIR = Path("skills")


class SkillRegistry:
    def __init__(self, skills_dir: Path = SKILLS_DIR):
        self.skills_dir = skills_dir
        self._skills: dict[str, dict[str, Any]] = {}

    def scan(self) -> None:
        self._skills.clear()
        if not self.skills_dir.exists():
            return
        for directory in sorted(self.skills_dir.iterdir()):
            if not directory.is_dir():
                continue
            manifest = directory / "SKILL.md"
            if not manifest.exists():
                continue
            raw = manifest.read_text("utf-8")
            meta, body = parse_frontmatter(raw)
            name = meta.get("name", directory.name)
            desc = meta.get("description", body.split("\n")[0].lstrip("#").strip())
            self._skills[name] = {
                "name": name,
                "description": desc,
                "content": raw,
            }

    def list_skills(self) -> str:
        if not self._skills:
            return "(no skills found)"
        return "\n".join(
            f"- {info['name']}: {info['description']}"
            for info in self._skills.values()
        )

    def available_skills(self) -> str:
        return ", ".join(self._skills.keys()) or "(none)"

    def load_skill(self, name: str) -> str | None:
        skill = self._skills.get(name)
        return skill["content"] if skill else None

    def inject_catalog(self, system_prompt: str) -> str:
        catalog = self.list_skills()
        if "no skills found" in catalog:
            return system_prompt
        return system_prompt + (
            "\n\nSkills catalog:\n" + catalog +
            "\nUse load_skill(name) when a skill is relevant."
        )
