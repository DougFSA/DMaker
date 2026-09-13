import json
from pathlib import Path

import pytest

from dmaker.config import TEMPLATES_DIR
from dmaker.domain.spec import Project

TEMPLATES = sorted(TEMPLATES_DIR.glob("*.json"))


@pytest.mark.parametrize("path", TEMPLATES, ids=[p.stem for p in TEMPLATES])
def test_template_is_valid_spec(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    project = Project.model_validate(data)
    assert project.timeline
    # sem travessão nos textos de marca
    if project.brand == "medlycare":
        for where, text in project.texts():
            assert "—" not in text and "–" not in text, where


def test_templates_exist():
    assert len(TEMPLATES) >= 4
