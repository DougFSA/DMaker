"""A skill `dmaker` precisa ficar enxuta (carregada inteira a cada /dmaker); a referência detalhada vive
no guia servido pelo MCP (`dmaker://guide` / `dmaker_guide`), lido só quando necessário."""

from __future__ import annotations

from dmaker import config

SKILL_PATH = config.ROOT / ".claude" / "skills" / "dmaker" / "SKILL.md"
GUIDE_PATH = config.PACKAGE_DIR / "resources" / "guide.md"
MANUAL_PATH = config.ROOT / "docs" / "MANUAL.md"

MANUAL_SECTION_TITLES = (
    "O que é o DMaker",
    "Instalação passo a passo no Windows",
    "Conceitos",
    "Usando com o Claude (Claude Code)",
    "Usando com LLM local (Ollama)",
    "Usando pela interface gráfica",
    "Usando pela linha de comando",
    "Marca MedlyCare",
    "Solução de problemas",
    "Anexos",
)


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


def test_guide_and_skill_send_spoken_recordings_to_autocut_instead_of_manual_cutting():
    guide = GUIDE_PATH.read_text(encoding="utf-8")
    skill = SKILL_PATH.read_text(encoding="utf-8")
    for tool in ("autocut", "list_cuts", "undo_cut", "audio_fade"):
        assert tool in guide
    assert "autocut" in skill and "undo_cut" in skill


def test_manual_exists_is_dash_free_and_covers_all_sections():
    assert MANUAL_PATH.exists()
    text = MANUAL_PATH.read_text(encoding="utf-8")
    assert "—" not in text and "–" not in text
    for title in MANUAL_SECTION_TITLES:
        assert title in text


def test_guide_documents_the_motion_transitions_the_curves_and_the_preview_commands():
    from dmaker.domain.curves import CURVES
    from dmaker.domain.transitions import MOTION_TRANSITIONS

    text = GUIDE_PATH.read_text(encoding="utf-8")
    for name in MOTION_TRANSITIONS:
        assert f"`{name}`" in text, f"o guia não descreve a transição {name}"
    for curve in CURVES:
        assert f"`{curve}`" in text, f"o guia não descreve a curva {curve}"
    assert "dmaker transitions sheet" in text and "dmaker transitions list" in text


def test_manual_mentions_the_motion_transitions_and_the_curve():
    from dmaker.domain.transitions import MOTION_TRANSITIONS

    text = MANUAL_PATH.read_text(encoding="utf-8")
    assert all(f"`{name}`" in text for name in MOTION_TRANSITIONS) and "`curve`" in text
