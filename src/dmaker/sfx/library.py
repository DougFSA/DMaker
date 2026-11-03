"""A biblioteca de sons em arquivos (`assets/sfx`) e a resolução de um som da spec para um caminho."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np

from .. import config
from ..media.wavio import write_wav_channels
from .synth import PEAK_DBFS, SAMPLE_RATE, library_names, sound_def, synthesize

LICENSES_FILE = "LICENSES"


class SfxNotFound(FileNotFoundError):
    """O som pedido na spec não é da biblioteca nem um arquivo que exista."""


def library_dir() -> Path:
    """Pasta da biblioteca, lida na hora do uso (os testes apontam `config.SFX_DIR` para uma temporária)."""
    return config.SFX_DIR


def library_path(name: str) -> Path:
    return library_dir() / f"{name}.wav"


def resolve_sound(reference: str, resolve_path: Callable[[str], Path]) -> Path:
    """Arquivo de um som da spec: um nome da biblioteca (`whoosh`) ou um caminho (relativo ao projeto).

    O nome da biblioteca vence um caminho de mesmo texto, e nada é baixado: os sons ficam em `assets/sfx`,
    para o render funcionar sem internet.
    """
    if reference in library_names():
        path = library_path(reference)
        if not path.exists():
            raise SfxNotFound(
                f"O som {reference!r} da biblioteca não está em {path.parent}. Rode `dmaker sfx build` para gerá-lo."
            )
        return path
    path = resolve_path(reference)
    if not path.exists():
        raise SfxNotFound(
            f"Som não encontrado: {reference!r}. Use um nome da biblioteca ({', '.join(library_names())}) "
            "ou o caminho de um arquivo de áudio."
        )
    return path


def licenses_text() -> str:
    """Conteúdo do `LICENSES`: origem e licença de cada arquivo, gerado da própria biblioteca para nunca divergir dela."""
    lines = [
        "Biblioteca de efeitos sonoros do DMaker",
        "",
        "Todo arquivo desta pasta é sintetizado pelo próprio DMaker (src/dmaker/sfx/synth.py), por código:",
        "ruído filtrado com envelope e varredura de frequência, tons com queda de afinação e parciais de sino,",
        "com semente fixa (o mesmo código gera sempre os mesmos arquivos). Nenhum som vem de terceiros, de banco",
        "de sons, de obra protegida ou da internet.",
        "",
        "Licença de todos: obra própria do projeto DMaker, sob a mesma licença do repositório (MIT).",
        f"Formato: WAV de {SAMPLE_RATE // 1000} kHz, 16 bits, estéreo (dois canais iguais), pico em {PEAK_DBFS:g} dBFS.",
        "Para gerar de novo: dmaker sfx build",
        "",
    ]
    for name in library_names():
        definition = sound_def(name)
        lines.append(
            f"{name}.wav: {definition.description}. "
            f"Origem: sintetizado pelo DMaker (semente {definition.seed}). Licença: MIT, obra própria."
        )
    return "\n".join(lines) + "\n"


def write_library(directory: Path | None = None) -> list[Path]:
    """Sintetiza todos os sons e grava os WAV (e o `LICENSES`) em `directory`; devolve os WAV gravados.

    Estéreo com dois canais iguais, porque o ffmpeg abre um arquivo mono com -3 dB de menos ao levá-lo para
    estéreo, e o pico de -3 dBFS da biblioteca precisa chegar à mixagem como está.
    """
    target = directory or library_dir()
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for name in library_names():
        sound = synthesize(name)
        frames = np.column_stack([sound.samples, sound.samples])
        written.append(write_wav_channels(target / f"{name}.wav", frames, sound.sample_rate))
    (target / LICENSES_FILE).write_text(licenses_text(), encoding="utf-8", newline="\n")
    return written
