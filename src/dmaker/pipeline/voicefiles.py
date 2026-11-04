"""Arquivos de áudio gravados como voz do projeto (`audio.voiceover`): onde tocam e quanto duram.

Diferem da narração (`pipeline/voiceover.py`), que sintetiza a fala de um texto: aqui o áudio já existe, e o
projeto só o posiciona. Entram no mesmo barramento de voz (ver `filtergraph/audio.py`), mas não contam como voz
sintetizada: a etiqueta de procedência da narração não os marca.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..domain.audio_effects import active_effects, chain_duration, chain_refusal
from ..domain.music_tempo import music_chain
from ..domain.spec import Project, VoiceoverClip
from .audio_effects import AudioItem, EffectProcessor
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
    pan: float = 0.0  # equilíbrio esquerda/direita (`VoiceoverClip.pan`)

    @property
    def end(self) -> float:
        return self.start + self.duration


def play_length(clip: VoiceoverClip, file_duration: float) -> float:
    """Quanto do arquivo toca: de `offset` até `end` (ou até o fim do arquivo), nunca negativo."""
    last = file_duration if clip.end is None else min(clip.end, file_duration)
    return max(last - clip.offset, 0.0)


def prepare_voice_files(
    project: Project, prober: Prober, processor: EffectProcessor | None = None
) -> list[PreparedVoiceFile]:
    """Localiza e mede cada arquivo de `audio.voiceover`. Falha, dizendo o campo, se o arquivo não existe
    ou não tem áudio. Com `processor`, o trecho de um arquivo que tem efeito ligado já vem processado: o
    arquivo é o processado, o ponto de entrada passa a ser 0 e a duração é a depois da cadeia (que o Repetir
    aumenta)."""
    prepared = []
    for index, clip in enumerate(project.audio.voiceover):
        path = project.resolve(clip.src)
        if not path.exists():
            raise FileNotFoundError(f"Áudio de voz não encontrado: {clip.src} (audio.voiceover[{index}].src)")
        info = prober(path)
        if not info.has_audio:
            raise ValueError(f"audio.voiceover[{index}].src: o arquivo {clip.src!r} não tem áudio")
        length = play_length(clip, info.duration)
        done = (
            processor.process(AudioItem(path, length, tuple(clip.effects), clip.offset))
            if processor
            else None
        )
        if done is not None:
            prepared.append(
                PreparedVoiceFile(done.path, clip.start, 0.0, done.duration, clip.volume, clip.src, clip.pan)
            )
        else:
            prepared.append(
                PreparedVoiceFile(path, clip.start, clip.offset, length, clip.volume, clip.src, clip.pan)
            )
    return prepared


def voice_file_playtimes(project: Project, prober: Prober) -> list[float | None]:
    """Quanto toca de cada arquivo (None = ausente ou ilegível), para o lint, sem falhar por um arquivo ruim.
    É a duração depois dos efeitos do arquivo (o Repetir a aumenta), calculada sem processar nada."""
    playtimes: list[float | None] = []
    for clip in project.audio.voiceover:
        path = project.resolve(clip.src)
        try:
            length = play_length(clip, prober(path).duration) if path.exists() else None
        except (OSError, ValueError, RuntimeError):
            length = None
        playtimes.append(None if length is None else chain_duration(clip.effects, length))
    return playtimes


def music_file_playtime(project: Project, prober: Prober) -> float | None:
    """Quanto dura o arquivo da música depois dos efeitos dela (o Mudar Andamento e o Paulstretch a alongam ou encurtam),
    ou None sem música, sem arquivo ou ilegível. A música inteira é o item: as janelas e o loop recortam o resultado."""
    music = project.audio.music
    if music is None:
        return None
    length = _file_length(project.resolve(music.src), prober)
    return None if length is None else chain_duration(music_chain(project.audio), length)


def _file_length(path: Path, prober: Prober) -> float | None:
    """A duração do arquivo, ou None quando ele não existe ou não dá para ler (o aviso não falha por um arquivo ruim)."""
    try:
        return prober(path).duration if path.exists() else None
    except (OSError, ValueError, RuntimeError):
        return None


def effect_refusal_warnings(project: Project, prober: Prober) -> list[str]:
    """O que um efeito recusa neste item (o Paulstretch com saída acima do teto): o render pararia nele, então o
    `validate` avisa antes. Cobre a voz gravada e a música, onde um efeito que muda a duração é aceito."""
    warnings = []
    for index, clip in enumerate(project.audio.voiceover):
        length = _file_length(project.resolve(clip.src), prober) if active_effects(clip.effects) else None
        reason = None if length is None else chain_refusal(clip.effects, play_length(clip, length))
        if reason:
            warnings.append(f"audio.voiceover[{index}]: {reason}")
    music = project.audio.music
    if music is not None and active_effects(music_chain(project.audio)):
        length = _file_length(project.resolve(music.src), prober)
        reason = None if length is None else chain_refusal(music_chain(project.audio), length)
        if reason:
            warnings.append(f"audio.music: {reason}")
    return warnings


def music_playtime_warnings(project: Project, prober: Prober) -> list[str]:
    """O aviso de que os efeitos mudaram quanto dura a música. Só olha o arquivo (e só o sonda) quando a música tem um
    efeito que muda a duração; sem ele a música segue como sempre."""
    music = project.audio.music
    if music is None or not any(
        effect.alters_duration() for _, effect in active_effects(music_chain(project.audio))
    ):
        return []
    playtime = music_file_playtime(project, prober)
    if playtime is None:
        return []
    return [f"audio.music: com os efeitos, o arquivo da música toca por {playtime:.1f}s."]


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
        if any(effect.alters_duration() for _, effect in active_effects(clip.effects)):
            warnings.append(
                f"{where}: com os efeitos, o áudio toca por {playtime:.1f}s (um efeito de tempo muda a duração)."
            )
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
