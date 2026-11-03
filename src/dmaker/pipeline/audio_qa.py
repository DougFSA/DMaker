"""QA de uma saída só de áudio: duração, formato do arquivo, loudness e pico. Nada de vídeo.

O relatório de vídeo (`pipeline/report.py`) olha zona segura, contraste, quadros pretos e resolução; nada disso existe
num arquivo de som. Aqui entram só as conferências que fazem sentido: o arquivo não tem imagem, tem a taxa e os canais
do preset, dura o que o projeto promete, chega ao alvo de loudness sem estourar o pico e não começa nem termina em
silêncio longo. Usa as mesmas estruturas do relatório de vídeo (`QAReport`, `Finding`), para a CLI, o MCP e a
interface mostrarem os dois do mesmo jeito.
"""

from __future__ import annotations

from pathlib import Path

from ..domain.audio_presets import get_audio_preset
from ..domain.spec import Project
from ..media.ffmpeg import FFmpegRunner, SubprocessRunner
from ..media.probe import probe
from .assembly import LoudnessMeasure, loudnorm_report
from .audio_lint import audio_output_warnings
from .audio_render import encoding_for
from .context import Prober
from .layout import project_layout
from .report import (
    DURATION_TOLERANCE,
    LOUDNESS_TOLERANCE_LU,
    SILENCE_MIN_DURATION,
    TRUE_PEAK_LIMIT,
    Finding,
    QAReport,
    parse_silencedetect,
)
from .sync import OffsetFinder

# o LRA que o `loudnorm` de medição recebe; só a medição do pico e do volume integrado interessa aqui
LOUDNORM_LRA = 11


def _number(value: object) -> float | None:
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def inspect_audio_file(
    runner: FFmpegRunner,
    prober: Prober,
    path: Path,
    *,
    expected_total: float | None,
    sample_rate: int,
    channels: int,
    target_lufs: float,
) -> list[Finding]:
    """As conferências do arquivo de áudio já gravado."""
    findings: list[Finding] = []
    info = prober(path)
    if info.has_video:
        findings.append(Finding("erro", "saída", "o arquivo de áudio tem uma faixa de imagem"))
    if expected_total is not None and abs(info.duration - expected_total) > DURATION_TOLERANCE:
        findings.append(
            Finding(
                "erro", "saída", f"duração {info.duration:.1f}s difere do esperado ({expected_total:.1f}s)"
            )
        )
    if info.sample_rate and info.sample_rate != sample_rate:
        findings.append(
            Finding(
                "aviso", "saída", f"taxa de amostragem {info.sample_rate} Hz, o preset pede {sample_rate} Hz"
            )
        )
    if info.channels and info.channels != channels:
        findings.append(Finding("aviso", "saída", f"{info.channels} canal(is), o preset pede {channels}"))

    silence = runner.capture(
        ["-i", str(path), "-af", f"silencedetect=n=-50dB:d={SILENCE_MIN_DURATION}", "-vn", "-f", "null", "-"],
        label="detecção de silêncio",
    )
    for start, end in parse_silencedetect(silence):
        findings.append(Finding("info", "saída", f"silêncio de {start:.1f}s a {end:.1f}s", start))

    stderr = runner.capture(
        [
            "-i",
            str(path),
            "-af",
            f"loudnorm=I={target_lufs:g}:TP={TRUE_PEAK_LIMIT:g}:LRA={LOUDNORM_LRA}:print_format=json",
            "-vn",
            "-f",
            "null",
            "-",
        ],
        label="medição de loudness",
    )
    report = loudnorm_report(stderr)
    if report is not None and not LoudnessMeasure(report).silent:
        loudness, true_peak = _number(report.get("input_i")), _number(report.get("input_tp"))
        if loudness is not None and abs(loudness - target_lufs) > LOUDNESS_TOLERANCE_LU:
            findings.append(
                Finding(
                    "aviso", "saída", f"loudness integrado {loudness:.1f} LUFS, alvo {target_lufs:.1f} LUFS"
                )
            )
        if true_peak is not None and true_peak > TRUE_PEAK_LIMIT:
            findings.append(
                Finding(
                    "aviso",
                    "saída",
                    f"pico verdadeiro {true_peak:.1f} dBTP acima de {TRUE_PEAK_LIMIT:.0f} dBTP",
                )
            )
    return findings


def build_audio_report(
    project: Project,
    *,
    prober: Prober = probe,
    offset_finder: OffsetFinder | None = None,
    output: Path | None = None,
    runner: FFmpegRunner | None = None,
) -> QAReport:
    """O relatório de QA de um projeto com saída de áudio: os avisos da spec e, com `output`, as conferências do arquivo."""
    layout = project_layout(project, prober, offset_finder)
    preset = get_audio_preset(project.output.preset)
    findings = [
        Finding("aviso", "projeto", message) for message in audio_output_warnings(project, layout.total)
    ]
    checks = ["avisos da saída de áudio (sem imagem, duração, normalização)"]
    if output is not None:
        encoding = encoding_for(project, preset)
        # a duração de uma narração ainda por sintetizar é só uma estimativa pelo texto; comparar o arquivo com ela
        # daria um erro falso, então a duração só é conferida quando todo o som tem duração conhecida
        known = not project.audio.narration or bool(project.timeline)
        findings.extend(
            inspect_audio_file(
                runner or SubprocessRunner(quiet=True),
                prober,
                output,
                expected_total=layout.total if known else None,
                sample_rate=encoding.sample_rate,
                channels=encoding.channels,
                target_lufs=project.audio.target_lufs,
            )
        )
        checks.append("saída gravada (sem imagem, duração, taxa e canais, silêncio, loudness e pico)")
    return QAReport(project.name, layout.total, findings, checks, preset=preset.id)
