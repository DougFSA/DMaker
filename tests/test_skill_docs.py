"""A skill `dmaker` precisa ficar enxuta (carregada inteira a cada /dmaker); a referência detalhada vive
no guia servido pelo MCP (`dmaker://guide` / `dmaker_guide`), lido só quando necessário."""

from __future__ import annotations

from dmaker import config

SKILL_PATH = config.ROOT / ".claude" / "skills" / "dmaker" / "SKILL.md"
GUIDE_PATH = config.PACKAGE_DIR / "resources" / "guide.md"


def test_skill_is_short_and_dash_free():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert len(text.encode("utf-8")) < 6_000
    assert "—" not in text and "–" not in text


def test_skill_mentions_new_tools_and_guide_resource():
    text = SKILL_PATH.read_text(encoding="utf-8")
    for keyword in ("new_from_template", "qa_report", "edit_project", "dmaker://guide"):
        assert keyword in text


def test_guide_exists_and_is_dash_free():
    assert GUIDE_PATH.exists()
    text = GUIDE_PATH.read_text(encoding="utf-8")
    assert "—" not in text and "–" not in text


def test_guide_covers_reference_topics():
    text = GUIDE_PATH.read_text(encoding="utf-8").lower()
    for topic in ("spec", "presets", "multicâmera", "picture-in-picture"):
        assert topic in text


def test_guide_is_package_data_for_wheel_installs():
    pyproject = (config.ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "resources/*.md" in pyproject
