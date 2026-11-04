"""As conferências de áudio do QA: som estourado (clipping) na saída final e em cada item, e o contraste entre a voz e a
música. Usam os analisadores de `dmaker.analysis`, os mesmos de `dmaker audio analyze`.

- **Clipping na saída final** é erro: o arquivo que vai ser publicado distorce, e o instante vem no achado.
- **Clipping num item** é aviso: a fonte (ou o item depois dos efeitos e do ganho) já chega estourada, ainda que a
  normalização final esconda isso no arquivo pronto.
- **Contraste** é aviso, nunca erro: abaixo de 20 dB entre a fala e a música (WCAG 1.4.7) quem ouve mal perde a fala.
  Mede-se nas trilhas da mixagem (a música já abaixada pelo ducking), só nos trechos com fala, e o pior bloco de 1 s dá
  o valor e o instante. Projeto sem música não confere.

Roda só com a saída renderizada (`build_report(output=...)`): decodificar e remixar leva segundos e não cabe na conferência
estática da spec.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np

from ..analysis import AnalysisResult, parse_analyzer
from ..analysis.analyzers.contrast import WCAG_CONTRAST_DB, speech_contrast
from ..domain.spec import ClipSegment, Project, VideoOverlay
from ..media.ffmpeg import FFmpegError, FFmpegRunner
from .analysis_items import TargetError
from .audio_analysis import AnalysisRequest, AudioAnalysisService
from .audio_render import AudioRenderPipeline
from .audio_stems import SPEECH_STEMS, render_stem_levels
from .context import Prober, RenderOptions
from .report import Finding
from .sync import OffsetFinder

# Quantos trechos estourados viram um achado cada: o resto entra num achado só (um áudio muito estourado teria centenas)
MAX_CLIPPING_FINDINGS = 6


def _mmss(seconds: float) -> str:
    minutes, rest = divmod(int(round(max(seconds, 0.0))), 60)
    return f"{minutes:02d}:{rest:02d}"


def clipping_findings(
    result: AnalysisResult, where: str, level: str, to_project: Callable[[float], float] | None = None
) -> list[Finding]:
    """Um achado por trecho estourado (até `MAX_CLIPPING_FINDINGS`, e um último resumindo o resto). Os canais que
    estouram juntos são um trecho só. `to_project` leva o tempo da análise para o do vídeo."""
    markers = result.markers()
    findings = []
    for marker in markers[:MAX_CLIPPING_FINDINGS]:
        start = to_project(marker.start) if to_project else marker.start
        end = to_project(marker.end if marker.end is not None else marker.start) if to_project else marker.end
        # um estouro de poucas amostras dura frações de milissegundo: "de 0.90 s a 0.90 s" não diria nada
        short = end is None or end - start < 0.01
        span = f"em {start:.2f} s" if short else f"de {start:.2f} s a {end:.2f} s"
        findings.append(Finding(level, where, f"som estourado no teto (clipping) {span}", start))  # type: ignore[arg-type]
    if len(markers) > MAX_CLIPPING_FINDINGS:
        findings.append(
            Finding(
                level,
                where,
                f"e mais {len(markers) - MAX_CLIPPING_FINDINGS} trecho(s) estourado(s) além destes",
            )  # type: ignore[arg-type]
        )
    return findings


def output_clipping_findings(output: Path, service: AudioAnalysisService) -> list[Finding]:
    """O som estourado na saída final já renderizada: erro, com o instante de cada trecho."""
    try:
        loaded = service.load_file(output, AnalysisRequest("clipping"))
    except TargetError as exc:
        return [Finding("info", "saída", f"clipping não conferido: {exc}")]
    except FileNotFoundError:
        return []  # num ensaio (RecordingRunner) o ffmpeg não decodifica nada: não há o que conferir
    result = parse_analyzer("clipping", {}).analyze(loaded.signal)
    return clipping_findings(result, "saída", "erro")


def _item_targets(project: Project) -> list[tuple[str, str]]:
    """Os itens com som que o projeto tem: (alvo da análise, como o QA os chama)."""
    targets = [
        (f"timeline.{index}", f"timeline[{index}]")
        for index, segment in enumerate(project.timeline)
        if isinstance(segment, ClipSegment)
    ]
    targets += [
        (f"overlays.{index}", f"overlays[{index}]")
        for index, overlay in enumerate(project.overlays)
        if isinstance(overlay, VideoOverlay) and overlay.volume > 0
    ]
    targets += [
        (f"audio.voiceover.{index}", f"audio.voiceover[{index}]")
        for index in range(len(project.audio.voiceover))
    ]
    targets += [
        (f"audio.narration.{index}", f"audio.narration[{index}]")
        for index in range(len(project.audio.narration))
    ]
    if project.audio.music is not None:
        targets.append(("audio.music", "audio.music"))
    targets += [
        (f"audio.tracks.{index}", f"audio.tracks[{index}]") for index in range(len(project.audio.tracks))
    ]
    return targets


def item_clipping_findings(project: Project, service: AudioAnalysisService) -> list[Finding]:
    """O som estourado em cada item do projeto, como ele soa (com os efeitos e o ganho do item): aviso."""
    findings: list[Finding] = []
    layout = service.layout(project)
    for target, where in _item_targets(project):
        try:
            loaded = service.load(project, AnalysisRequest("clipping", target=target), layout)
        except (TargetError, FileNotFoundError, FFmpegError):
            continue  # item mudo, ausente, longo demais ou narração ainda não sintetizada: não há o que conferir
        result = parse_analyzer("clipping", {}).analyze(loaded.signal)
        clock = loaded.clock
        findings.extend(
            clipping_findings(
                result,
                where,
                "aviso",
                (lambda t, c=clock, o=loaded.offset: c.to_project(o + t)) if clock else None,
            )
        )
    return findings


def voice_contrast_findings(
    project: Project, runner: FFmpegRunner, prober: Prober, offset_finder: OffsetFinder | None
) -> list[Finding]:
    """O contraste entre a voz e a música nos trechos com fala: aviso quando o pior bloco de 1 s fica abaixo de 20 dB."""
    music = project.audio.music
    if music is None or music.volume <= 0:
        return []
    voices = list(SPEECH_STEMS)
    if project.captions is not None and project.captions.enabled and project.timeline:
        voices.append("A1")  # o som do clipe é fala quando o projeto o legenda
    pipeline = AudioRenderPipeline(
        project,
        RenderOptions(quiet=True, preset="audio/wav"),
        runner=runner,
        prober=prober,
        offset_finder=offset_finder,
    )
    try:
        job = pipeline.prepare()
        levels = render_stem_levels(pipeline, job, (*voices, "MUS"))
    except (OSError, ValueError, KeyError, RuntimeError, FFmpegError) as exc:
        return [Finding("info", "áudio", f"contraste entre voz e música não conferido: {exc}")]
    background = levels.get("MUS")
    spoken = [levels[name] for name in voices if name in levels]
    if background is None or not spoken:
        return []
    voice = np.sum(spoken, axis=0)
    measured = speech_contrast(voice, background, 16000, WCAG_CONTRAST_DB)
    if measured is None or measured.passes:
        return []
    return [
        Finding(
            "aviso",
            "áudio",
            f"a fala fica só {measured.worst_db:.1f} dB acima da música por volta de {_mmss(measured.worst_at)} "
            f"(o recomendado é {measured.threshold_db:g} dB ou mais, WCAG 1.4.7); {measured.blocks_below} de "
            f"{measured.blocks} trecho(s) de 1 s com fala ficam abaixo disso",
            measured.worst_at,
        )
    ]


def audio_findings(
    project: Project,
    output: Path | None,
    runner: FFmpegRunner,
    prober: Prober,
    offset_finder: OffsetFinder | None = None,
) -> tuple[list[Finding], list[str]]:
    """Os achados de áudio do QA (clipping na saída e nos itens, contraste voz e música) e o nome de cada conferência
    feita, para a lista "Checagens feitas" do relatório."""
    service = AudioAnalysisService(runner, prober, offset_finder)
    findings: list[Finding] = []
    checks: list[str] = []
    if output is not None:
        findings += output_clipping_findings(output, service)
        checks.append("clipping na saída (som estourado no teto, com o instante)")
    findings += item_clipping_findings(project, service)
    checks.append("clipping em cada item de áudio (como soa, com efeitos e ganho)")
    if project.audio.music is not None:
        findings += voice_contrast_findings(project, runner, prober, offset_finder)
        checks.append("contraste entre voz e música (WCAG 1.4.7, 20 dB) nos trechos com fala")
    return findings, checks


__all__ = ["audio_findings", "clipping_findings"]
