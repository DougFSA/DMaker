"""A música no andamento do projeto: o esticamento derivado, o loop de tempos inteiros e a entrada na batida da grade.

Com `audio.music.stretch_to_tempo`, a música (de `music.bpm`) é esticada, sem mudar o tom, até o andamento do projeto
(`audio.tempo.bpm`). O esticamento NÃO é gravado como efeito do usuário: é um `change_tempo` derivado, posto na frente da
cadeia da música na hora de processar, então mudar o andamento do projeto estica de novo e a lista de efeitos da pessoa fica
como ela deixou. Tudo aqui é conta pura; quem processa é o `EffectProcessor` e quem monta o grafo é `filtergraph.audio`.
"""

from __future__ import annotations

from dataclasses import dataclass

from .audio_effects import AudioEffect
from .audio_effects.pitch_tempo import ChangeTempo
from .spec import AudioSettings, Music

# A emenda do loop de tempos inteiros, quando o arquivo esticado não tem um número inteiro de tempos e precisa ser aparado
# ou completado com silêncio: um fade curto nas duas pontas esconde o salto. Medido num tom de 221,3 Hz cortado fora de
# fase: sem fade o maior salto entre amostras vizinhas na emenda era 0,0270, 19 vezes o passo normal do tom (0,0014), um
# estalo claro; com 3 ms de fade o salto cai a 0,0014, igual ao passo normal, e o tom perde o volume só por esses 3 ms.
SEAM_FADE_SECONDS = 0.003
# Abaixo disto a música já está na batida: atrasar a entrada por menos de 0,5 ms (a resolução do `adelay`) não muda nada
ALIGNED_SECONDS = 0.0005
# Até quanto o arquivo esticado pode diferir de um número inteiro de tempos sem precisar aparar a emenda
SEAM_TOLERANCE_SECONDS = 0.001


@dataclass(frozen=True)
class MusicGrid:
    """O que a mixagem precisa saber de uma música esticada para a grade: `ratio` é a duração nova sobre a antiga,
    `period` o tempo do projeto, `first_beat` o primeiro tempo da música já esticada e `grid_offset` onde cai o tempo 1."""

    ratio: float
    period: float
    first_beat: float
    grid_offset: float

    def loop_length(self, stretched_duration: float) -> float:
        """O comprimento do loop: o arquivo esticado arredondado para um número inteiro de tempos (pelo menos um)."""
        return max(round(stretched_duration / self.period), 1) * self.period

    def needs_seam_fade(self, stretched_duration: float) -> bool:
        """Se o arquivo esticado não fecha um número inteiro de tempos e a emenda do loop foi aparada ou completada."""
        return abs(self.loop_length(stretched_duration) - stretched_duration) > SEAM_TOLERANCE_SECONDS

    def entry_delay(self, window_start: float, start_at: float) -> float:
        """Quanto atrasar a entrada da música para o primeiro tempo dela cair num tempo da grade. A janela entra em
        `window_start` (segundos do vídeo) a partir de `start_at` (segundos do arquivo esticado); a música toca os tempos
        em `window_start + first_beat - start_at + k·período`, e a grade em `grid_offset + k·período`. O atraso é o que
        falta, de 0 até um período."""
        music_phase = (window_start + self.first_beat - start_at) % self.period
        grid_phase = self.grid_offset % self.period
        delay = (grid_phase - music_phase) % self.period
        if delay < ALIGNED_SECONDS or self.period - delay < ALIGNED_SECONDS:
            return 0.0
        return delay


def music_grid(audio: AudioSettings) -> MusicGrid | None:
    """A grade da música, ou None quando ela não é esticada para o andamento: sem música, sem andamento do projeto,
    sem `bpm` na música ou com `stretch_to_tempo` desligado. É o que faz um projeto sem `audio.tempo` seguir como antes."""
    music, tempo = audio.music, audio.tempo
    if music is None or tempo is None or not music.stretch_to_tempo or music.bpm is None:
        return None
    ratio = music.bpm / tempo.bpm
    return MusicGrid(
        ratio=ratio, period=tempo.period, first_beat=music.beat_offset * ratio, grid_offset=tempo.offset
    )


def stretch_effect(audio: AudioSettings) -> ChangeTempo | None:
    """O `change_tempo` derivado que leva a música do andamento dela ao do projeto, ou None se ela não é esticada."""
    music, tempo = audio.music, audio.tempo
    if music_grid(audio) is None or music is None or tempo is None or music.bpm is None:
        return None
    return ChangeTempo.between_bpm(music.bpm, tempo.bpm)


def music_chain(audio: AudioSettings) -> tuple[AudioEffect, ...]:
    """A cadeia que a música realmente toca: o esticamento derivado (se houver) na frente dos efeitos da pessoa."""
    music = audio.music
    if music is None:
        return ()
    derived = stretch_effect(audio)
    return (derived, *music.effects) if derived is not None else tuple(music.effects)


def stretch_problem(music: Music, audio_tempo_bpm: float) -> str | None:
    """Por que o esticamento não cabe (a razão de andamento passa do que o `change_tempo` aceita), ou None se cabe."""
    if music.bpm is None:
        return None
    try:
        ChangeTempo.between_bpm(music.bpm, audio_tempo_bpm)
    except ValueError as exc:
        return str(exc)
    return None


# Até esta razão de andamento (para mais ou para menos) o esticamento ainda soa natural; além dela a música ganha artefatos
GENTLE_RATIO = 1.4


def tempo_warnings(audio: AudioSettings) -> list[str]:
    """Avisos sobre a música no andamento: o esticamento ligado que não tem como valer (o projeto não tem andamento) e o
    esticamento tão grande que a música soa artificial."""
    music, tempo = audio.music, audio.tempo
    if music is None or not music.stretch_to_tempo:
        return []
    if tempo is None:
        return [
            "audio.music: stretch_to_tempo está ligado, mas o projeto não tem andamento (audio.tempo): "
            "a música toca no andamento original"
        ]
    if music.bpm is None:
        return []
    ratio = tempo.bpm / music.bpm
    if ratio > GENTLE_RATIO or ratio < 1 / GENTLE_RATIO:
        return [
            f"audio.music: esticar de {music.bpm:g} para {tempo.bpm:g} BPM muda o andamento em "
            f"{abs(ratio - 1) * 100:.0f}%; acima de uns 40% o som fica artificial (confira se o BPM da música não está "
            "pela metade ou pelo dobro)"
        ]
    return []
