"""Prova que a suíte não toca nos dados reais (cache/, output/, projects/, vozes e léxico de pronúncia).

Sem CI, a suíte é o último portão: ela tem que dar o mesmo resultado com ou sem uma dublagem real rodando ao
lado, e para isso nenhum teste pode ler nem gravar nos dados de quem usa o editor.
"""

from __future__ import annotations

import os

import pytest

from dmaker import config
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.pipeline.isolation import IsolationService
from dmaker.pipeline.narration import NarrationService
from dmaker.ui import server
from dmaker.voice.kokoro import KokoroSynthesizer
from dmaker.voice.lexicon_store import LexiconStore
from dmaker.voice.library import VoiceLibrary
from dmaker.voice.synth import OmniVoiceSynthesizer

from .conftest import GUARD, data_paths

REAL_ROOT = config.ROOT

DATA_NAMES = (
    "CACHE_DIR",
    "MEZ_DIR",
    "PROXY_DIR",
    "WAVEFORM_DIR",
    "VOICE_CACHE_DIR",
    "STEMS_DIR",
    "JOBS_DIR",
    "MODELS_DIR",
    "OUTPUT_DIR",
    "PROJECTS_DIR",
    "VOICES_DIR",
    "LEXICON_DIR",
    "LAYOUTS_FILE",
)

# caminhos reais que não existem de propósito: abrir para escrever aqui falha, mas o gancho já viu a tentativa
REAL_PATHS_THAT_MUST_NOT_BE_WRITTEN = [
    REAL_ROOT / "cache" / "__guarda__" / "x.wav",
    REAL_ROOT / "output" / "__guarda__" / "x.wav",
    REAL_ROOT / "projects" / "__guarda__" / "spec.json",
    REAL_ROOT / "assets" / "voices" / "__guarda__" / "voice.json",
    REAL_ROOT / "assets" / "brands" / "__guarda__" / "pronunciation.json",
]

# arquivos que existem de verdade (ou podem existir): o gancho recebe o evento direto, sem abrir nada
REAL_FILES_THAT_MUST_NOT_BE_WRITTEN = [
    REAL_ROOT / "assets" / "pronunciation.json",
    REAL_ROOT / "layouts.json",
]


@pytest.mark.parametrize("name", DATA_NAMES)
def test_every_data_dir_of_the_config_lives_in_the_temporary_data_folder(name):
    path = getattr(config, name)
    assert path.is_relative_to(config.DATA_DIR), f"{name} não está na pasta de dados do teste"
    assert not GUARD.is_protected(os.path.normcase(os.path.abspath(path))), f"{name} aponta para dado real"


def test_the_data_folder_is_not_the_repository():
    assert config.DATA_DIR != REAL_ROOT and not config.DATA_DIR.is_relative_to(REAL_ROOT)


def test_the_conftest_redirects_every_path_that_lives_in_the_data_folder():
    assert set(DATA_NAMES) <= set(data_paths())


def test_defaults_are_resolved_when_used_not_when_imported():
    data = config.DATA_DIR
    narration = NarrationService(synthesizer=None, runner=RecordingRunner())
    isolation = IsolationService(separator=None, runner=RecordingRunner())
    omnivoice = OmniVoiceSynthesizer()
    for folder in (
        VoiceLibrary().root,
        LexiconStore().root,
        narration.cache_dir,
        isolation.cache_dir,
        omnivoice.prompt_dir,
        omnivoice.models_dir,
        KokoroSynthesizer().models_dir,
        server.layout_store.path,
    ):
        assert folder.is_relative_to(data), f"{folder} não segue a pasta de dados do teste"


@pytest.mark.parametrize(
    "path", REAL_PATHS_THAT_MUST_NOT_BE_WRITTEN, ids=lambda p: p.relative_to(REAL_ROOT).as_posix()
)
def test_the_guard_flags_a_write_to_real_data(path, request):
    with pytest.raises(OSError):
        path.open("w")

    flagged = GUARD.take_violations()
    assert len(flagged) == 1 and request.node.nodeid in flagged[0]


@pytest.mark.parametrize("path", REAL_FILES_THAT_MUST_NOT_BE_WRITTEN, ids=lambda p: p.name)
def test_the_guard_flags_a_write_to_a_real_data_file(path, request):
    GUARD.audit("open", (str(path), "w", 0))
    GUARD.audit("open", (str(path), "r", 0))

    flagged = GUARD.take_violations()
    assert len(flagged) == 1 and request.node.nodeid in flagged[0]


def test_the_guard_ignores_reads_of_real_data_and_writes_to_the_temporary_folder(tmp_path):
    (REAL_ROOT / "pyproject.toml").read_bytes()
    with pytest.raises(OSError):
        (REAL_ROOT / "cache" / "__guarda__" / "x.wav").open("rb")
    (tmp_path / "ok.wav").write_bytes(b"x")
    (config.OUTPUT_DIR / "dublagem").mkdir(parents=True)
    (config.VOICES_DIR / "ana").mkdir(parents=True)

    assert GUARD.take_violations() == []
