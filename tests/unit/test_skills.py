from __future__ import annotations

from pathlib import Path

from coding_agent.skills.frontmatter import parse_frontmatter
from coding_agent.skills.registry import SkillRegistry


def test_parse_frontmatter_no_marker():
    meta, body = parse_frontmatter("hello world")
    assert meta == {}
    assert body == "hello world"


def test_parse_frontmatter_valid_yaml():
    text = "---\nname: test-skill\ndescription: A test\n---\n\nSkill body"
    meta, body = parse_frontmatter(text)
    assert meta.get("name") == "test-skill"
    assert meta.get("description") == "A test"
    assert "Skill body" in body


def test_parse_frontmatter_malformed_yaml():
    text = "---\nname: test\n: broken\n---\n\nBody"
    meta, body = parse_frontmatter(text)
    # Should not crash; returns empty or partial meta
    assert body == "Body"


def test_parse_frontmatter_incomplete_marker():
    text = "---\nname: test"
    meta, body = parse_frontmatter(text)
    assert meta == {}
    assert body == text


def test_skill_registry_scan_empty_dir(tmp_path: Path):
    reg = SkillRegistry(skills_dir=tmp_path)
    reg.scan()
    assert "(no skills found)" in reg.list_skills()


def test_skill_registry_scan_with_skill(tmp_path: Path):
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: My test skill\n---\n\nContent here",
        encoding="utf-8",
    )
    reg = SkillRegistry(skills_dir=tmp_path)
    reg.scan()
    assert "my-skill" in reg.list_skills()
    assert "My test skill" in reg.list_skills()


def test_skill_registry_load_skill(tmp_path: Path):
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test-skill\n---\n\nFull content here",
        encoding="utf-8",
    )
    reg = SkillRegistry(skills_dir=tmp_path)
    reg.scan()
    content = reg.load_skill("test-skill")
    assert content is not None
    assert "Full content here" in content


def test_skill_registry_load_unknown():
    reg = SkillRegistry(skills_dir=Path("nonexistent"))
    reg.scan()
    assert reg.load_skill("nonexistent") is None


def test_skill_registry_inject_catalog(tmp_path: Path):
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: My skill\n---\n\nBody",
        encoding="utf-8",
    )
    reg = SkillRegistry(skills_dir=tmp_path)
    reg.scan()
    result = reg.inject_catalog("Base prompt")
    assert "Base prompt" in result
    assert "Skills catalog" in result
    assert "my-skill" in result
