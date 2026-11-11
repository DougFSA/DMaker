"""O modo instalado do `config` (DMK-71): o marcador `instalacao.json` manda na raiz e nos dados."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dmaker import config


def make_install(tmp_path: Path, data: Path | None = None, windows: bool = True) -> tuple[Path, Path]:
    """Uma árvore falsa de programa instalado; devolve a raiz e a pasta do pacote."""
    root = tmp_path / "programa"
    site = root / "python" / ("Lib" if windows else "lib/python3.13") / "site-packages"
    package = site / "dmaker"
    package.mkdir(parents=True)
    marker = {"versao": "2.0.0", "dados": str(data or tmp_path / "dados")}
    (root / config.INSTALL_MARKER_NAME).write_text(json.dumps(marker), encoding="utf-8")
    return root, package


def test_finds_marker_from_windows_and_linux_layouts(tmp_path):
    root, package = make_install(tmp_path / "w")
    assert config.find_install_root(package) == root
    root, package = make_install(tmp_path / "l", windows=False)
    assert config.find_install_root(package) == root


def test_editable_clone_never_uses_a_marker_above_it(tmp_path):
    (tmp_path / config.INSTALL_MARKER_NAME).write_text("{}", encoding="utf-8")
    package = tmp_path / "clone" / "src" / "dmaker"
    package.mkdir(parents=True)
    assert config.find_install_root(package) is None


def test_reads_marker_and_ignores_a_broken_one(tmp_path):
    root, _ = make_install(tmp_path)
    info = config.read_install_info(root)
    assert info and info.version == "2.0.0" and info.data_dir == (tmp_path / "dados").resolve()
    (root / config.INSTALL_MARKER_NAME).write_text("{", encoding="utf-8")
    assert config.read_install_info(root) is None
    (root / config.INSTALL_MARKER_NAME).write_text('{"versao": "1"}', encoding="utf-8")
    assert config.read_install_info(root) is None


def test_marker_with_bom_is_read(tmp_path):
    root, _ = make_install(tmp_path)
    text = (root / config.INSTALL_MARKER_NAME).read_text(encoding="utf-8")
    (root / config.INSTALL_MARKER_NAME).write_text(text, encoding="utf-8-sig")
    assert config.read_install_info(root) is not None


def test_root_precedence_env_then_marker_then_clone_then_cwd(tmp_path):
    root, package = make_install(tmp_path)
    info = config.read_install_info(root)
    clone = tmp_path / "clone"
    (clone / "src" / "dmaker").mkdir(parents=True)
    (clone / "pyproject.toml").write_text("", encoding="utf-8")
    clone_package = clone / "src" / "dmaker"
    other = tmp_path / "outra"
    assert config.resolve_root(str(other), info, package, tmp_path) == other.resolve()
    assert config.resolve_root(None, info, package, tmp_path) == root.resolve()
    assert config.resolve_root(None, None, clone_package, tmp_path) == clone
    assert config.resolve_root(None, None, tmp_path / "x" / "y" / "dmaker", tmp_path) == tmp_path


def test_data_dir_precedence_env_then_marker_then_root(tmp_path):
    root, _ = make_install(tmp_path, data=tmp_path / "meus-dados")
    info = config.read_install_info(root)
    env = tmp_path / "env-dados"
    assert config.resolve_data_dir(str(env), info, root) == env.resolve()
    assert config.resolve_data_dir(None, info, root) == (tmp_path / "meus-dados").resolve()
    assert config.resolve_data_dir(None, None, root) == root.resolve()


def test_clone_in_tests_is_not_in_installed_mode():
    assert config.INSTALL is None
    assert os.environ.get("DMAKER_DATA_DIR")  # os testes sempre apontam os dados para uma pasta temporária
