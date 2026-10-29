"""Efeitos sonoros do render: achar o arquivo de cada um e acertar o nível contra a voz medida."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..domain.sfx import SfxItem, plan_sfx
from ..domain.spec import Project
from ..filtergraph.sfx import FALLBACK_VOICE_PEAK_DB, sfx_gain_db, voice_reference_db
from ..sfx import SfxNotFound, resolve_sound
from .context import RenderContext


@dataclass(frozen=True)
class SfxTrack:
    """Efeito pronto para a mixagem: o arquivo, o instante e o ganho final (nível contra a voz já aplicado)."""

    path: Path
    at: float
    gain_db: float
    origin: str = ""


def resolve_files(project: Project, items: Sequence[SfxItem]) -> list[tuple[SfxItem, Path]]:
    """O arquivo de cada efeito (biblioteca ou caminho do projeto). Falha com a origem do pedido na mensagem,
    para quem lê saber qual `sound` da spec corrigir."""
    resolved = []
    for item in items:
        try:
            resolved.append((item, resolve_sound(item.sound, project.resolve)))
        except SfxNotFound as exc:
            raise SfxNotFound(f"{item.origin}: {exc}") from exc
    return resolved


def level_tracks(resolved: Sequence[tuple[SfxItem, Path]], reference_db: float | None) -> list[SfxTrack]:
    """Efeitos com o ganho que os põe abaixo do pico de referência da voz. Sem voz medida (simulação, vídeo
    sem fala), vale um pico de voz típico, o que mantém o nível dos efeitos previsível."""
    reference = FALLBACK_VOICE_PEAK_DB if reference_db is None else reference_db
    return [
        SfxTrack(path, item.at, sfx_gain_db(item.volume, reference), item.origin) for item, path in resolved
    ]


def leveled_effects(
    ctx: RenderContext,
    voice_level_meter,
    prepared,
    transitions,
    spans,
    total: float,
    voiceovers,
    video_overlays=(),
    voice_files=(),
) -> list[SfxTrack]:
    """Efeitos sonoros do projeto (`audio.sfx` e os de entrada), com o nível acertado contra a voz.

    A voz é medida sozinha (barato, só áudio) e só quando há efeitos; na simulação não se mede nada. É a mesma
    conta para o render e para a prévia da linha do tempo.
    """
    items = plan_sfx(ctx.project, spans)
    if not items:
        return []
    resolved = resolve_files(ctx.project, items)
    reference = None
    if not ctx.options.dry_run:
        voice = voice_level_meter.measure(
            ctx, prepared, transitions, total, voiceovers, video_overlays, voice_files
        )
        if voice is not None:
            audio = ctx.project.audio
            target = None if audio.normalize == "off" else audio.target_lufs
            reference = voice_reference_db(voice.loudness, voice.true_peak, target)
    ctx.log(
        f"efeitos sonoros: {len(items)}"
        + (
            f" (pico de referência da voz {reference:.1f} dBFS)"
            if reference is not None
            else " (sem voz medida)"
        )
    )
    return level_tracks(resolved, reference)
