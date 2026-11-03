"""Arquivos de áudio gravados como voz do projeto (`audio.voiceover`): onde tocam e quanto duram.

Diferem da narração (`pipeline/voiceover.py`), que sintetiza a fala de um texto: aqui o áudio já existe, e o
projeto só o posiciona. Entram no mesmo barramento de voz (ver `filtergraph/audio.py`), mas não contam como voz
sintetizada: a etiqueta de procedência da narração não os marca.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..domain.spec import Project, VoiceoverClip
from .context import Prober

# o arquivo pode passar um pouco do fim do vídeo sem aviso: é o arredondamento de duração do contêiner
OVERRUN_TOLERANCE = 0.05


@dataclass(frozen=True)
class PreparedVoiceFile:
    """Arquivo de áudio já medido e posicionado: o que a mixagem e a transcrição consomem."""

    path: Path
    start: float  # instante do vídeo final em que o trecho começa
    offset: float  # ponto de entrada no arquivo
    duration: float  # quanto do arquivo toca, já aparado por `offset` e `end`
    volume: float
    source: str = ""  # `src` como a spec o escreveu, para a chave de cache e as mensagens

    @property
    def end(self) -> float:
        return self.start + self.duration


def play_length(clip: VoiceoverClip, file_duration: float) -> float:
    """Quanto do arquivo toca: de `offset` até `end` (ou até o fim do arquivo), nunca negativo."""
    last = file_duration if clip.end is None else min(clip.end, file_duration)
    return max(last - clip.offset, 0.0)


def prepare_voice_files(project: Project, prober: Prober) -> list[PreparedVoiceFile]:
    """Localiza e mede cada arquivo de `audio.voiceover`. Falha, dizendo o campo, se o arquivo não existe
    ou não tem áudio."""
    prepared = []
    for index, clip in enumerate(project.audio.voiceover):
        path = project.resolve(clip.src)
        if not path.exists():
            raise FileNotFoundError(f"Áudio de voz não encontrado: {clip.src} (audio.voiceover[{index}].src)")
        info = prober(path)
        if not info.has_audio:
            raise ValueError(f"audio.voiceover[{index}].src: o arquivo {clip.src!r} não tem áudio")
        prepared.append(
            PreparedVoiceFile(
                path, clip.start, clip.offset, play_length(clip, info.duration), clip.volume, clip.src
            )
        )
    return prepared


def voice_file_playtimes(project: Project, prober: Prober) -> list[float | None]:
    """Quanto toca de cada arquivo (None = ausente ou ilegível), para o lint, sem falhar por um arquivo ruim."""
    playtimes: list[float | None] = []
    for clip in project.audio.voiceover:
        path = project.resolve(clip.src)
        try:
            playtimes.append(play_length(clip, prober(path).duration) if path.exists() else None)
        except (OSError, ValueError, RuntimeError):
            playtimes.append(None)
    return playtimes


def voice_file_warnings(project: Project, total: float, playtimes: Sequence[float | None]) -> list[str]:
    """Avisos de `audio.voiceover`: arquivo que não existe, que não tem o que tocar a partir do `offset` e o que
    passa do fim do vídeo (o áudio excedente é cortado). `playtimes` vem de `voice_file_playtimes`; sem ele só
    a existência do arquivo é conferida."""
    warnings = []
    for index, clip in enumerate(project.audio.voiceover):
        where = f"audio.voiceover[{index}]"
        if not project.resolve(clip.src).exists():
            warnings.append(f"{where}.src: arquivo de áudio não encontrado: {clip.src}")
            continue
        if clip.start >= total:
            warnings.append(f"{where}: começa em {clip.start:g}s, depois do fim do vídeo ({total:.1f}s).")
            continue
        playtime = playtimes[index] if index < len(playtimes) else None
        if playtime is None:
            continue
        if playtime <= 0:
            warnings.append(
                f"{where}: o offset ({clip.offset:g}s) passa do fim do arquivo, não há áudio para tocar."
            )
        elif clip.start + playtime > total + OVERRUN_TOLERANCE:
            warnings.append(
                f"{where}: termina em {clip.start + playtime:.1f}s, depois do fim do vídeo ({total:.1f}s); "
                "o final do áudio será cortado. Aumente a `duration` do fundo para a duração do áudio."
            )
    return warnings
