from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

# Antes de importar o dmaker: a pasta de dados da suíte inteira é temporária, então até um caminho que
# algum módulo fixe na importação (ou um subprocesso que herde o ambiente) cai fora dos dados reais.
SESSION_DATA_DIR = Path(tempfile.mkdtemp(prefix="dmaker-testes-"))
os.environ["DMAKER_DATA_DIR"] = str(SESSION_DATA_DIR)
os.environ.setdefault("DMAKER_TEST", "1")
# a marca d'água de voz (AudioSeal) carrega um modelo: os testes usam marcadores falsos, só o smoke usa o real
os.environ["DMAKER_WATERMARK"] = "0"

import pytest  # noqa: E402

from dmaker import config  # noqa: E402
from dmaker.media import ffmpeg  # noqa: E402

from . import guard  # noqa: E402

GUARD = guard.make_guard()
guard.install(GUARD)


def data_paths() -> dict[str, Path]:
    """Os caminhos do config que moram na pasta de dados (cache, saída, projetos, vozes, léxico, layouts)."""
    return {
        name: value
        for name, value in vars(config).items()
        if name.isupper() and isinstance(value, Path) and value != config.DATA_DIR
        if value.is_relative_to(config.DATA_DIR)
    }


@pytest.fixture(autouse=True)
def isolated_data(request, tmp_path_factory, monkeypatch):
    """Cada teste ganha pastas de dados próprias, vazias, e nenhum estado de processo vaza para o próximo.

    Sem isso, o que um teste (ou uma dublagem real rodando ao lado) deixa em cache/ e output/ muda o
    resultado do seguinte, e a suíte passa ou falha conforme a hora.
    """
    GUARD.current_test = request.node.nodeid
    data = tmp_path_factory.mktemp("dados")
    redirected = {name: data / path.relative_to(config.DATA_DIR) for name, path in data_paths().items()}
    if os.environ.get("DMAKER_VOICE_SMOKE") == "1":  # os testes com modelo real usam os modelos baixados
        redirected["MODELS_DIR"] = config.ROOT / "cache" / "models"
    for name, path in redirected.items():
        monkeypatch.setattr(config, name, path)
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setenv("DMAKER_DATA_DIR", str(data))
    _reset_process_state(monkeypatch)
    yield data
    _reset_process_state(monkeypatch)
    leaked = GUARD.take_violations()
    GUARD.current_test = "<fora de um teste>"
    assert not leaked, "o teste escreveu fora da pasta temporária de dados:\n" + "\n".join(leaked)


def _reset_process_state(monkeypatch) -> None:
    """Zera singletons e travas de módulo; só os que já foram importados, para não carregar nada à toa."""
    for module_name, factory in (
        ("dmaker.pipeline.voices", "shared_synthesizer"),
        ("dmaker.pipeline.isolation", "shared_separator"),
    ):
        module = sys.modules.get(module_name)
        if module is not None:
            # um teste pode ter trocado a fábrica por um dublê sem cache
            getattr(getattr(module, factory), "cache_clear", lambda: None)()
    voice_routes = sys.modules.get("dmaker.ui.voice_routes")
    if voice_routes is not None:
        monkeypatch.setattr(voice_routes, "_synthesis_lock", threading.Lock())


def pytest_sessionfinish(session, exitstatus) -> None:
    leaked = GUARD.take_violations()
    if leaked:
        print("\nEscritas fora da pasta temporária, sem teste ativo:\n" + "\n".join(leaked), file=sys.stderr)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
    shutil.rmtree(SESSION_DATA_DIR, ignore_errors=True)


def ffmpeg_available() -> bool:
    return config.find_tool("ffmpeg") is not None and config.find_tool("ffprobe") is not None


requires_ffmpeg = pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg não instalado (dmaker setup)")


@pytest.fixture(scope="session")
def synthetic_media(tmp_path_factory) -> dict[str, Path]:
    """Dois clipes de teste (padrão de cores + tom), uma imagem, uma música e um SRT."""
    if not ffmpeg_available():
        pytest.skip("ffmpeg não instalado")
    d = tmp_path_factory.mktemp("media")
    clip_a = d / "a.mp4"
    clip_b = d / "b.mp4"
    music = d / "music.wav"
    photo = d / "photo.png"
    srt = d / "falas.srt"
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1280x720:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "3",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(clip_a),
        ],
        quiet=True,
    )
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            "smptebars=size=720x1280:rate=30",
            "-t",
            "3",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(clip_b),
        ],
        quiet=True,
    )
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:sample_rate=48000",
            "-t",
            "20",
            "-c:a",
            "pcm_s16le",
            str(music),
        ],
        quiet=True,
    )
    ffmpeg.run(
        ["-f", "lavfi", "-i", "testsrc=size=1600x900:rate=1", "-frames:v", "1", str(photo)], quiet=True
    )
    srt.write_text(
        "1\n00:00:00,200 --> 00:00:01,600\nOlá, este é um teste\n\n"
        "2\n00:00:01,700 --> 00:00:03,400\nde legendas curtas no DMaker.\n\n"
        "3\n00:00:03,500 --> 00:00:05,000\nFuncionou?\n",
        encoding="utf-8",
    )
    return {"clip_a": clip_a, "clip_b": clip_b, "music": music, "photo": photo, "srt": srt, "dir": d}
