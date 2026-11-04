"""Duração de um projeto sem trechos de vídeo: quem a dá são os itens de áudio.

Num projeto de vídeo, o último trecho decide o fim e o áudio que passa dele é cortado. Sem trechos (a saída é um
arquivo de som), o fim é o do item de áudio que termina por último: narração, voz gravada e a janela de música
com fim declarado. A música sem janela (que se repete para cobrir o vídeo) não decide nada quando há voz; sozinha,
vale uma passada dela inteira, porque repetir para sempre não é uma duração.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..domain.audio_effects import chain_duration
from ..domain.spec import Project
from .context import Prober
from .voicefiles import voice_file_playtimes
from .voiceover import estimate_narration_duration

NOTHING_TO_PLAY = (
    "o projeto não tem trechos de vídeo nem nenhum áudio que dê duração: ponha uma narração (audio.narration), "
    "uma voz gravada (audio.voiceover) ou uma música (audio.music) para ele ter o que tocar"
)


def audio_extent(project: Project, prober: Prober, narration_durations: Sequence[float | None] = ()) -> float:
    """Até onde vai o som do projeto, em segundos (0 se não há nada que toque).

    `narration_durations` traz a duração real das narrações já sintetizadas (uma por narração, `None` ou ausente =
    a estimativa pelo texto); o arquivo de voz gravada é medido pelo `prober`."""
    audio = project.audio
    ends: list[float] = []
    for index, narration in enumerate(audio.narration):
        if narration.volume <= 0:
            continue
        known = narration_durations[index] if index < len(narration_durations) else None
        duration = known if known is not None else estimate_narration_duration(project, narration)
        ends.append(narration.start + duration)
    for clip, playtime in zip(audio.voiceover, voice_file_playtimes(project, prober), strict=True):
        if clip.volume > 0 and playtime:
            ends.append(clip.start + playtime)
    music = audio.music
    if music is not None and music.volume > 0:
        ends.extend(span.end for span in music.spans if span.end is not None and not span.from_end)
    if ends:
        return max(ends)
    return _music_alone(project, prober)


def _music_alone(project: Project, prober: Prober) -> float:
    """Uma passada pela música quando ela é o único som: do ponto em que entra (`start_at`) até o fim do arquivo."""
    music = project.audio.music
    if music is None or music.volume <= 0:
        return 0.0
    path = project.resolve(music.src)
    if not path.exists():
        return 0.0
    first = music.spans[0].start_at if music.spans else music.start_at
    # o arquivo depois dos efeitos que mudam o tempo (o Mudar Andamento o encurta, o Paulstretch o alonga)
    return max(chain_duration(music.effects, prober(path).duration) - first, 0.0)
