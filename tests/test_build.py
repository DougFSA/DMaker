"""Identificador de versão do código carregado (pipeline/build.py): usado pelo RenderDispatcher para
perceber quando o servidor da interface está com código antigo (ver pipeline/remote.py)."""

from __future__ import annotations

import os
import time
from pathlib import Path

from dmaker.pipeline.build import build_id


def _make_package(root: Path) -> Path:
    (root / "pkg.py").write_text("x = 1\n", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "mod.py").write_text("y = 2\n", encoding="utf-8")
    static = root / "ui" / "static"
    static.mkdir(parents=True)
    (static / "app.js").write_text("console.log(1);\n", encoding="utf-8")
    resources = root / "resources"
    resources.mkdir()
    (resources / "guide.md").write_text("# guia\n", encoding="utf-8")
    return root


def test_build_id_is_stable_for_the_same_tree(tmp_path):
    root = _make_package(tmp_path)
    assert build_id(root) == build_id(root)


def test_build_id_changes_when_a_python_file_is_touched(tmp_path):
    root = _make_package(tmp_path)
    before = build_id(root)
    target = root / "sub" / "mod.py"
    target.write_text("y = 3\n", encoding="utf-8")
    future = time.time() + 5
    os.utime(target, (future, future))
    assert build_id(root) != before


def test_build_id_changes_when_a_static_file_changes(tmp_path):
    root = _make_package(tmp_path)
    before = build_id(root)
    target = root / "ui" / "static" / "app.js"
    target.write_text("console.log(2);\n", encoding="utf-8")
    future = time.time() + 5
    os.utime(target, (future, future))
    assert build_id(root) != before


def test_build_id_ignores_files_outside_py_static_and_resources(tmp_path):
    root = _make_package(tmp_path)
    before = build_id(root)
    (root / "readme.txt").write_text("nao deveria contar para o build_id", encoding="utf-8")
    assert build_id(root) == before


def test_build_id_of_the_real_package_is_a_short_hex_string():
    assert build_id() != ""
    value = build_id()
    assert len(value) == 16
    int(value, 16)  # não lança: é hexadecimal
