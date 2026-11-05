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
    pan: float = 0.0


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


def level_tracks(
    resolved: Sequence[tuple[SfxItem, Path]],
    reference_db: float | None,
    bus_gain_db: float = 0.0,
    bus_pan: float = 0.0,
) -> list[SfxTrack]:
    """Efeitos com o ganho que os põe abaixo do pico de referência da voz. Sem voz medida (simulação, vídeo
    sem fala), vale um pico de voz típico, o que mantém o nível dos efeitos previsível. O ganho e o pan do
    barramento dos efeitos (a trilha SFX) entram por cima do nível já acertado contra a voz."""
    reference = FALLBACK_VOICE_PEAK_DB if reference_db is None else reference_db
    return [
        SfxTrack(path, item.at, sfx_gain_db(item.volume, reference) + bus_gain_db, item.origin, bus_pan)
        for item, path in resolved
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
    generated = _generated(ctx)
    items = plan_sfx(ctx.project, spans)
    if not items:
        return generated
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
    return _tracks(ctx, generated, resolved, reference)


def unleveled_effects(ctx: RenderContext, spans) -> list[SfxTrack]:
    """Os mesmos efeitos de `leveled_effects`, sem medir a voz: com o volume da spec e o pico de voz típico que vale sem
    voz medida. Serve ao Auto Duck cuja chave são os efeitos e cujo fundo é uma faixa externa, que precisa da curva antes
    dos mezaninos, e a voz só se mede depois deles."""
    items = plan_sfx(ctx.project, spans)
    resolved = resolve_files(ctx.project, items) if items else []
    return _tracks(ctx, _generated(ctx), resolved, None)


def _generated(ctx: RenderContext) -> list[SfxTrack]:
    from .generated_sounds import generated_tracks  # import tardio: o módulo importa `SfxTrack` daqui

    return generated_tracks(ctx)


def _tracks(
    ctx: RenderContext, generated: list[SfxTrack], resolved, reference: float | None
) -> list[SfxTrack]:
    """Os efeitos do projeto com o nível acertado contra `reference` (None: o pico de voz típico), mais os sons gerados."""
    leveled = level_tracks(resolved, reference, ctx.project.audio.sfx_gain_db, ctx.project.audio.sfx_pan)
    return sorted([*leveled, *generated], key=lambda track: track.at) if generated else leveled
