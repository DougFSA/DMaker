"""Comparar antes e depois de um efeito de áudio: um trecho curto do item, com o efeito desligado e ligado, sem gravar nada.

Serve à Redução de ruído (e a qualquer efeito): a interface toca os dois arquivos um depois do outro para a pessoa ouvir o
que o efeito faz antes de aceitá-lo. Os dois trechos passam pelo mesmo `EffectProcessor` do render, com a cadeia inteira do
item (só o efeito escolhido muda de um para o outro), então o que se ouve é o que o render vai fazer. Os arquivos ficam
no cache de efeitos, pela chave de sempre, e não tocam a spec.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..domain.audio_effects import EffectBase, active_effects, rebase_effects
from ..domain.audio_effects.basic import Amplify
from ..domain.edits import EditError
from ..domain.spec import ClipSegment, Project, VideoOverlay
from ..media.ffmpeg import FFmpegRunner
from .audio_effects import AudioItem, EffectProcessor
from .context import Prober
from .noise_profiles import ProfileLocator, locate_target_audio

MAX_COMPARE_SECONDS = 30.0  # o trecho comparado é um pedaço, não o item: mais que isto é uma prévia inteira


@dataclass(frozen=True)
class Comparison:
    """Os dois arquivos prontos e quanto cada um dura."""

    before: Path
    after: Path
    duration: float
    # o que o antes e depois não representa (vazio quando representa tudo)
    warning: str = ""


def loose_item_warning(chain: list[EffectBase]) -> str:
    """O aviso de que o item é tocado solto, fora da linha do tempo: o Vocoder cuja portadora é outra trilha do projeto soa aqui com a
    portadora gerada, porque a comparação não monta o projeto inteiro. Vazio sem Vocoder ligado a uma trilha."""
    tracks = sorted({track for _, effect in active_effects(chain) if (track := effect.carrier_track_id())})
    if not tracks:
        return ""
    return (
        f"O antes e depois toca o item solto e usa a portadora gerada do Vocoder, não a da trilha {', '.join(tracks)}; "
        "o render e a prévia da linha do tempo usam a trilha."
    )


def _chain(project: Project, target: str) -> list[EffectBase]:
    """A cadeia de efeitos do item `target` (a mesma lista que a spec guarda)."""
    from ..domain.audio_targets import parse_target

    kind, index = parse_target(target)
    if kind == "clip":
        segment = project.timeline[index]  # type: ignore[index]
        assert isinstance(segment, ClipSegment)
        return list(segment.effects)
    if kind == "pip":
        overlay = project.overlays[index]  # type: ignore[index]
        assert isinstance(overlay, VideoOverlay)
        return list(overlay.effects)
    if kind == "voiceover":
        return list(project.audio.voiceover[index].effects)  # type: ignore[index]
    if kind == "music":
        return list(project.audio.music.effects) if project.audio.music else []
    if kind == "track":
        return list(project.audio.tracks[index].effects)  # type: ignore[index]
    raise EditError(f"{target}: não há como comparar o som deste item")


def compare_effect(
    project: Project,
    target: str,
    index: int,
    start: float,
    duration: float,
    runner: FFmpegRunner,
    prober: Prober,
    cache_dir: Path | None = None,
    at: float | None = None,
) -> Comparison:
    """O trecho de `duration` segundos do item `target`, a partir de `start` (segundos do item), processado com o efeito
    `index` da cadeia desligado e ligado. Os intervalos dos outros efeitos acompanham o recorte. Com `at` (segundos da
    linha do tempo, como o cursor do editor), o trecho começa ali e `start` é ignorado."""
    from .audio_targets import resolve_audio_target
    from .layout import aggregate_by_origin, project_layout
    from .missing import MissingMedia

    chain = _chain(project, target)
    if not 0 <= index < len(chain):
        raise EditError(f"o item {target} não tem o efeito {index} (cadeia de {len(chain)})")
    if duration <= 0 or duration > MAX_COMPARE_SECONDS:
        raise EditError(f"a duração do trecho precisa ficar entre 0 e {MAX_COMPARE_SECONDS:g} s")
    layout = project_layout(project, prober, None, MissingMedia.scan(project))
    if at is not None:
        start = resolve_audio_target(project, aggregate_by_origin(project, layout), target).item_time(at)
    source = locate_target_audio(project, layout.session, target)
    processor = EffectProcessor(runner, cache_dir, profiles=ProfileLocator(project, layout.session))

    def processed(enabled: bool) -> Path:
        variant = [
            effect.model_copy(update={"enabled": enabled if position == index else effect.enabled})
            for position, effect in enumerate(chain)
        ]
        excerpt = rebase_effects(variant, start, duration)
        # um item sem nenhum efeito ligado não gera arquivo: o ganho de 0 dB faz o trecho sair no mesmo formato
        item = AudioItem(
            source.path, duration, (Amplify(gain_db=0.0), *excerpt), source.file_start + start, source.stream
        )
        done = processor.process(item)
        assert done is not None
        return done.path

    return Comparison(processed(False), processed(True), duration, loose_item_warning(chain))
