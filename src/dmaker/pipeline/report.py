"""Relatório de QA automático, em texto: tudo que dá para conferir sem olhar imagem.

Checagens estáticas (`STATIC_CHECKS`) olham só a spec, sem rodar nada: reaproveitam o `lint`, estimam
onde o texto cai (zona segura, contraste) com as mesmas contas do ASS (`text/overlays.py`), e avisam
sobre ritmo de leitura, sobreposições e legendas. `OutputInspector` faz as checagens que só dá para
saber olhando o arquivo pronto (duração, resolução, quadros pretos, silêncio, loudness), sempre por um
`FFmpegRunner` injetado. `build_report` junta as duas pontas; a IA só chama `contact_sheet`/`frames`
quando este relatório aponta algo.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..domain.brand import Theme
from ..domain.presets import Preset
from ..domain.spec import CardSegment, ClipSegment, ImageSegment, Project, TextOverlay
from ..domain.timeline import tone_for
from ..filtergraph.reframe import resolve_reframe_mode
from ..media import fonts
from ..media.ffmpeg import FFmpegRunner, SubprocessRunner
from ..media.probe import probe
from ..text.captions import from_json, suspicious_cues
from ..text.overlays import ROLE_DEFAULTS, Canvas, effective_style, wrap_lines
from .context import Prober
from .layout import ProjectLayout, project_layout
from .lint import lint
from .sync import OffsetFinder

WORDS_PER_SECOND_LIMIT = 3.5
CARD_TITLE_CHAR_LIMIT = 60
MIN_CUE_DURATION = 0.3
MAX_CUE_DURATION = 7.0
SPEECH_GAP_LIMIT = 2.0
IMAGE_UPSCALE_LIMIT = 1.5
MIN_CONTRAST = 3.0
BLACK_MIN_DURATION = 0.5
SILENCE_MIN_DURATION = 3.0
DURATION_TOLERANCE = 0.5
LOUDNESS_TOLERANCE_LU = 1.5
TRUE_PEAK_LIMIT = -1.0

Level = Literal["erro", "aviso", "info"]
_LEVEL_ORDER = {"erro": 0, "aviso": 1, "info": 2}


@dataclass
class Finding:
    level: Level
    where: str
    message: str
    at: float | None = None


@dataclass
class QAReport:
    project: str
    total: float
    findings: list[Finding]
    checks: list[str] = field(default_factory=list)
    preset: str = ""

    def to_text(self) -> str:
        """Cabeçalho com duração/preset, contagem por nível, uma linha por achado e as checagens feitas."""
        counts = {"erro": 0, "aviso": 0, "info": 0}
        for f in self.findings:
            counts[f.level] = counts.get(f.level, 0) + 1
        header = (
            f"QA {self.project} ({self.preset or '?'}, {_mmss(self.total)}): "
            f"{counts['erro']} erro(s), {counts['aviso']} aviso(s), {counts['info']} info(s)"
        )
        lines = [header]
        ordered = sorted(
            self.findings, key=lambda f: (_LEVEL_ORDER.get(f.level, 9), f.at if f.at is not None else -1.0)
        )
        for f in ordered:
            prefix = f"[{_mmss(f.at)}] " if f.at is not None else ""
            lines.append(f"{prefix}{f.level}: {f.where}: {f.message}")
        lines.append("Checagens feitas: " + "; ".join(self.checks))
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "project": self.project,
            "preset": self.preset,
            "total": self.total,
            "findings": [
                {"level": f.level, "where": f.where, "message": f.message, "at": f.at} for f in self.findings
            ],
            "checks": self.checks,
        }


def _mmss(seconds: float | None) -> str:
    seconds = max(seconds or 0.0, 0.0)
    m, s = divmod(int(round(seconds)), 60)
    return f"{m:02d}:{s:02d}"


# ---------- contraste (WCAG) ----------


def _linearize(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return 0.2126 * _linearize(r) + 0.7152 * _linearize(g) + 0.0722 * _linearize(b)


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    """Contraste WCAG entre duas cores #RRGGBB; 21 = preto sobre branco (o máximo)."""
    la, lb = _luminance(hex_a), _luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


# ---------- ajudantes de spec ----------


def _segment_tone(seg, info, theme: Theme, preset: Preset) -> str | None:
    """Tom (light/dark) do fundo gerado pelo tema atrás do trecho; None para vídeo/foto de verdade."""
    if isinstance(seg, CardSegment):
        return seg.variant or theme.style.get("card_variant", "light")
    if isinstance(seg, (ClipSegment, ImageSegment)) and info and info.width and info.height:
        mode = resolve_reframe_mode(
            seg.reframe.mode, info.width, info.height, preset.width, preset.height, theme.key != "default"
        )
        if mode == "brand":
            return seg.reframe.variant or theme.style.get("card_variant", "light")
    return None


def _segment_tones(project: Project, layout: ProjectLayout) -> list[str | None]:
    return [
        _segment_tone(seg, src.info, layout.theme, layout.preset)
        for seg, src in zip(project.timeline, layout.sources, strict=True)
    ]


def _text_geometry(ov: TextOverlay, theme: Theme, canvas: Canvas, tone: str | None):
    """Reproduz a conta de posição/tamanho de `add_text_overlay`, sem desenhar nada."""
    st = effective_style(ov, theme, tone)
    s = canvas.scale
    W, H, safe = canvas.width, canvas.height, canvas.safe
    ref = fonts.resolve(st["font"] or theme.font_family, st["weight"])
    size = st["size"] * s
    spacing = st["spacing"] * s
    text = ov.text.upper() if st["uppercase"] else ov.text
    max_w = W * st["max_width"] - 2 * st["box_padding"] * s
    lines = wrap_lines(text, ref, size, max_w, spacing)
    line_widths = [fonts.measure(ln, ref, size, spacing)[0] for ln in lines]
    block_w = max(line_widths) if line_widths else 0.0
    block_h = size * len(lines) * 1.2
    if st["box"]:
        pad = st["box_padding"] * s
        block_w += 2 * pad
        block_h += 2 * pad
    align = st["align"]
    if ov.x is not None:
        cx = ov.x * W
    elif align == "left":
        cx = safe.left + canvas.px(st["box_padding"]) + canvas.px(28)
    elif align == "right":
        cx = W - safe.right - canvas.px(st["box_padding"]) - canvas.px(28)
    else:
        cx = W / 2
    if ov.y is not None:
        cy = ov.y * H
    else:
        position = st["position"]
        if position == "top":
            cy = safe.top + H * 0.10 + block_h / 2
        elif position == "bottom":
            cy = H - safe.bottom - H * 0.045 - block_h / 2
        else:
            cy = H * 0.5 + H * st.get("offset_y", 0)
    return cx, cy, block_w, block_h, line_widths, max_w, st


# ---------- checagens estáticas ----------


def check_lint(project: Project, layout: ProjectLayout) -> list[Finding]:
    """avisos do lint (duração x preset, travessão, transições, cobertura das fontes)"""
    infos = [s.info for s in layout.sources]
    offsets = [s.offset for s in layout.sources]
    try:
        warnings = lint(project, layout.theme, layout.preset, layout.total, layout.durations, infos, offsets)
    except ValueError as exc:
        return [Finding("erro", "lint", str(exc))]
    return [Finding("aviso", "lint", w) for w in warnings]


def check_text_safe_zone(project: Project, layout: ProjectLayout) -> list[Finding]:
    """texto fora da zona segura ou palavra larga demais para a área"""
    findings: list[Finding] = []
    canvas = Canvas(layout.preset.width, layout.preset.height, layout.preset.safe, layout.theme, layout.total)
    tones = _segment_tones(project, layout)
    W, H, safe = layout.preset.width, layout.preset.height, layout.preset.safe
    for i, ov in enumerate(project.overlays):
        if not isinstance(ov, TextOverlay):
            continue
        end = min(ov.end if ov.end is not None else layout.total, layout.total)
        if end <= ov.start:
            continue
        tone = tone_for(ov.start, end, layout.spans, tones)
        cx, cy, bw, bh, widths, max_w, _st = _text_geometry(ov, layout.theme, canvas, tone)
        left, right = cx - bw / 2, cx + bw / 2
        top, bottom = cy - bh / 2, cy + bh / 2
        if left < safe.left or right > W - safe.right or top < safe.top or bottom > H - safe.bottom:
            findings.append(
                Finding(
                    "aviso",
                    f"overlays[{i}].text",
                    "texto pode invadir a área coberta pela interface do app",
                    ov.start,
                )
            )
        if any(w > max_w + 1 for w in widths):
            findings.append(
                Finding(
                    "aviso",
                    f"overlays[{i}].text",
                    "uma palavra é mais larga que a área de texto e será cortada",
                    ov.start,
                )
            )
    for i, seg in enumerate(project.timeline):
        if isinstance(seg, CardSegment):
            findings.extend(_check_card_text(i, seg, layout))
    return findings


def _check_card_text(index: int, seg: CardSegment, layout: ProjectLayout) -> list[Finding]:
    theme, preset = layout.theme, layout.preset
    W, H, safe = preset.width, preset.height, preset.safe
    base = min(W, H)
    title_ref = fonts.resolve(theme.font_family, theme.weight("title"))
    body_ref = fonts.resolve(theme.font_family, theme.weight("body"))
    title_size = base * 0.085
    sub_size = base * 0.042
    max_w = W * 0.84 - (safe.left + safe.right)
    title_lines = wrap_lines(seg.title, title_ref, title_size, max_w)
    sub_lines = wrap_lines(seg.subtitle, body_ref, sub_size, max_w) if seg.subtitle else []
    block_h = len(title_lines) * title_size * 1.18
    if sub_lines:
        block_h += sub_size * 0.6 + len(sub_lines) * sub_size * 1.35
    findings: list[Finding] = []
    if block_h > (H - safe.top - safe.bottom) * 0.9:
        findings.append(
            Finding(
                "aviso",
                f"timeline[{index}].title",
                "título/subtítulo do cartão pode não caber na altura disponível",
            )
        )
    widest = max((fonts.measure(ln, title_ref, title_size)[0] for ln in title_lines), default=0.0)
    if widest > max_w + 1:
        findings.append(
            Finding(
                "aviso",
                f"timeline[{index}].title",
                "uma palavra do título é mais larga que a área e será cortada",
            )
        )
    return findings


def check_text_pacing(project: Project, layout: ProjectLayout) -> list[Finding]:
    """texto rápido demais para o tempo em tela (gancho, título, CTA) ou título de cartão muito longo"""
    findings: list[Finding] = []
    for i, ov in enumerate(project.overlays):
        if not isinstance(ov, TextOverlay) or ov.role not in ("hook", "title", "cta"):
            continue
        end = min(ov.end if ov.end is not None else layout.total, layout.total)
        dur = end - ov.start
        if dur <= 0:
            continue
        words = len(ov.text.split())
        rate = words / dur
        if rate > WORDS_PER_SECOND_LIMIT:
            findings.append(
                Finding(
                    "aviso",
                    f"overlays[{i}].text",
                    f"{words} palavras em {dur:.1f}s pode ser rápido demais para ler",
                    ov.start,
                )
            )
    for i, seg in enumerate(project.timeline):
        if isinstance(seg, CardSegment) and len(seg.title) > CARD_TITLE_CHAR_LIMIT:
            findings.append(
                Finding(
                    "aviso",
                    f"timeline[{i}].title",
                    f"título com {len(seg.title)} caracteres, considere encurtar",
                )
            )
    return findings


def check_overlap(project: Project, layout: ProjectLayout) -> list[Finding]:
    """sobreposições fora da duração final ou textos no mesmo lugar e no mesmo instante"""
    findings: list[Finding] = []
    total = layout.total
    for i, ov in enumerate(project.overlays):
        start = getattr(ov, "start", None)
        end = getattr(ov, "end", None)
        if start is not None and start >= total:
            findings.append(
                Finding(
                    "aviso",
                    f"overlays[{i}]",
                    f"começa em {start:.1f}s, depois do fim do vídeo ({total:.1f}s)",
                    start,
                )
            )
        elif end is not None and end > total + 0.01:
            findings.append(
                Finding(
                    "aviso",
                    f"overlays[{i}]",
                    f"termina em {end:.1f}s, depois do fim do vídeo ({total:.1f}s)",
                    end,
                )
            )
    texts = [(i, ov) for i, ov in enumerate(project.overlays) if isinstance(ov, TextOverlay)]
    for a in range(len(texts)):
        i, ov1 = texts[a]
        end1 = min(ov1.end if ov1.end is not None else total, total)
        pos1 = ov1.position or ROLE_DEFAULTS[ov1.role]["position"]
        for b in range(a + 1, len(texts)):
            j, ov2 = texts[b]
            end2 = min(ov2.end if ov2.end is not None else total, total)
            pos2 = ov2.position or ROLE_DEFAULTS[ov2.role]["position"]
            overlap = min(end1, end2) - max(ov1.start, ov2.start)
            if overlap > 0.05 and ov1.role == ov2.role and pos1 == pos2:
                findings.append(
                    Finding(
                        "aviso",
                        f"overlays[{i}]/overlays[{j}]",
                        "dois textos no mesmo lugar e no mesmo tempo podem se sobrepor",
                        max(ov1.start, ov2.start),
                    )
                )
    return findings


def check_contrast(project: Project, layout: ProjectLayout) -> list[Finding]:
    """contraste baixo entre texto e fundo (cartão ou reenquadramento em modo marca)"""
    findings: list[Finding] = []
    theme = layout.theme
    tones = _segment_tones(project, layout)
    for i, ov in enumerate(project.overlays):
        if not isinstance(ov, TextOverlay):
            continue
        end = min(ov.end if ov.end is not None else layout.total, layout.total)
        if end <= ov.start:
            continue
        tone = tone_for(ov.start, end, layout.spans, tones)
        st = effective_style(ov, theme, tone)
        if st["box"]:
            ratio, place = contrast_ratio(st["color"], st["box_color"]), "a caixa"
        elif tone is not None:
            bg = theme.colors["bg_dark"] if tone == "dark" else theme.colors["bg"]
            ratio, place = contrast_ratio(st["color"], bg), "o fundo"
        else:
            continue
        if ratio < MIN_CONTRAST:
            findings.append(
                Finding(
                    "aviso",
                    f"overlays[{i}].text",
                    f"contraste baixo entre o texto e {place} ({ratio:.1f}:1)",
                    ov.start,
                )
            )
    for i, seg in enumerate(project.timeline):
        if not isinstance(seg, CardSegment):
            continue
        variant = seg.variant or theme.style.get("card_variant", "light")
        dark = variant == "dark"
        bg = (
            theme.color(seg.background)
            if seg.background
            else (theme.colors["bg_dark"] if dark else theme.colors["bg"])
        )
        fg = (
            theme.colors["text"]
            if theme.key == "default"
            else ("#FFFFFF" if dark else theme.colors["primary"])
        )
        ratio = contrast_ratio(fg, bg)
        if ratio < MIN_CONTRAST:
            findings.append(
                Finding(
                    "aviso",
                    f"timeline[{i}].title",
                    f"contraste baixo entre o título e o fundo do cartão ({ratio:.1f}:1)",
                )
            )
    return findings


def check_captions(project: Project, layout: ProjectLayout) -> list[Finding]:
    """legendas suspeitas (baixa confiança, longas/curtas, termo da marca, substituição pendente) e buracos de fala"""
    findings: list[Finding] = []
    captions = project.captions
    if not captions or not captions.enabled or not project.base_dir:
        return findings
    store = project.base_dir / "captions.auto.json"
    if not store.exists():
        return findings
    try:
        data = json.loads(store.read_text(encoding="utf-8"))
        cues = from_json(json.dumps(data))
    except (OSError, json.JSONDecodeError, ValueError, KeyError):
        return findings
    style = captions.style
    vocabulary = list(layout.theme.captions.get("vocabulary", [])) + list(captions.vocabulary)
    replacements = {**layout.theme.captions.get("replacements", {}), **captions.replacements}
    for issue in suspicious_cues(
        cues,
        vocabulary,
        replacements,
        max_chars=style.max_chars * 2,
        max_duration=MAX_CUE_DURATION,
        min_duration=MIN_CUE_DURATION,
    ):
        for reason in issue.reasons:
            findings.append(Finding("aviso", f"legendas[{issue.index}]", reason, issue.start))
    clip_spans = [
        span for seg, span in zip(project.timeline, layout.spans, strict=True) if isinstance(seg, ClipSegment)
    ]
    if clip_spans and cues:
        covered = sorted((c.start, c.end) for c in cues)
        for a, b in clip_spans:
            cursor = a
            for cs, ce in covered:
                if ce <= a or cs >= b:
                    continue
                if cs - cursor > SPEECH_GAP_LIMIT:
                    findings.append(
                        Finding(
                            "info", "legendas", f"trecho de {cs - cursor:.1f}s sem legenda em fala", cursor
                        )
                    )
                cursor = max(cursor, ce)
            if b - cursor > SPEECH_GAP_LIMIT:
                findings.append(
                    Finding("info", "legendas", f"trecho de {b - cursor:.1f}s sem legenda em fala", cursor)
                )
    return findings


def check_sources(project: Project, layout: ProjectLayout) -> list[Finding]:
    """clipe sem nenhum áudio no projeto todo e imagens que precisam ampliar demais"""
    findings: list[Finding] = []
    has_clips = any(isinstance(seg, ClipSegment) for seg in project.timeline)
    has_live_audio = any(
        isinstance(seg, ClipSegment) and src.info and src.info.has_audio and not seg.mute and seg.volume > 0
        for seg, src in zip(project.timeline, layout.sources, strict=True)
    )
    if has_clips and not has_live_audio and not project.audio.music and not project.audio.tracks:
        findings.append(
            Finding("aviso", "audio", "o vídeo fica sem áudio (clipes mudos, sem música e sem faixa externa)")
        )
    W, H = layout.preset.width, layout.preset.height
    for i, (seg, src) in enumerate(zip(project.timeline, layout.sources, strict=True)):
        if not isinstance(seg, ImageSegment) or not src.info or not src.info.width or not src.info.height:
            continue
        factor = max(W / src.info.width, H / src.info.height)
        if factor > IMAGE_UPSCALE_LIMIT:
            findings.append(
                Finding(
                    "aviso",
                    f"timeline[{i}]",
                    f"imagem {src.info.width}x{src.info.height} precisa ampliar {factor:.1f}x para {W}x{H}; pode ficar borrada",
                )
            )
    return findings


STATIC_CHECKS = [
    check_lint,
    check_text_safe_zone,
    check_text_pacing,
    check_overlap,
    check_contrast,
    check_captions,
    check_sources,
]


# ---------- checagens sobre a saída renderizada ----------


def parse_blackdetect(stderr: str) -> list[tuple[float, float]]:
    """[(início, fim), ...] dos trechos de quadros pretos no stderr do filtro `blackdetect`."""
    return [
        (float(a), float(b))
        for a, b in re.findall(r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)", stderr)
    ]


def parse_silencedetect(stderr: str) -> list[tuple[float, float]]:
    """[(início, fim), ...] dos trechos de silêncio no stderr do filtro `silencedetect`."""
    starts = [float(v) for v in re.findall(r"silence_start:\s*(-?[\d.]+)", stderr)]
    ends = [float(v) for v in re.findall(r"silence_end:\s*(-?[\d.]+)", stderr)]
    return list(zip(starts, ends, strict=False))


def parse_loudnorm_json(stderr: str) -> dict:
    """O bloco JSON que o filtro `loudnorm` (print_format=json) imprime no stderr."""
    blocks = re.findall(r"\{[^{}]*\}", stderr)
    if not blocks:
        return {}
    try:
        return json.loads(blocks[-1])
    except json.JSONDecodeError:
        return {}


def _finite(value: object) -> float | None:
    try:
        f = float(str(value))
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


class OutputInspector:
    """Checagens sobre o arquivo já renderizado: só o que precisa rodar ffmpeg de verdade, via `runner`."""

    def __init__(self, runner: FFmpegRunner, prober: Prober = probe):
        self.runner = runner
        self.prober = prober

    def inspect(
        self, video: Path, expected_total: float, preset: Preset, target_lufs: float
    ) -> list[Finding]:
        findings: list[Finding] = []
        info = self.prober(video)
        if abs(info.duration - expected_total) > DURATION_TOLERANCE:
            findings.append(
                Finding(
                    "erro",
                    "saída",
                    f"duração {info.duration:.1f}s difere do esperado ({expected_total:.1f}s)",
                )
            )
        if info.width and info.height and (info.width, info.height) != (preset.width, preset.height):
            findings.append(
                Finding(
                    "erro",
                    "saída",
                    f"resolução {info.width}x{info.height} diferente do preset ({preset.width}x{preset.height})",
                )
            )
        if preset.fps and info.fps and abs(info.fps - preset.fps) > 0.5:
            findings.append(
                Finding("aviso", "saída", f"fps {info.fps:.2f} diferente do preset ({preset.fps:.0f})")
            )

        black_stderr = self.runner.capture(
            [
                "-i",
                str(video),
                "-vf",
                f"blackdetect=d={BLACK_MIN_DURATION}:pic_th=0.98",
                "-an",
                "-f",
                "null",
                "-",
            ],
            label="detecção de quadros pretos",
        )
        for start, end in parse_blackdetect(black_stderr):
            findings.append(Finding("aviso", "saída", f"quadros pretos de {start:.1f}s a {end:.1f}s", start))

        silence_stderr = self.runner.capture(
            [
                "-i",
                str(video),
                "-af",
                f"silencedetect=n=-50dB:d={SILENCE_MIN_DURATION}",
                "-vn",
                "-f",
                "null",
                "-",
            ],
            label="detecção de silêncio",
        )
        for start, end in parse_silencedetect(silence_stderr):
            findings.append(Finding("info", "saída", f"silêncio de {start:.1f}s a {end:.1f}s", start))

        loud_stderr = self.runner.capture(
            ["-i", str(video), "-af", f"loudnorm=I={target_lufs}:print_format=json", "-f", "null", "-"],
            label="medição de loudness da saída",
        )
        loud = parse_loudnorm_json(loud_stderr)
        integrated = _finite(loud.get("input_i")) if loud else None
        true_peak = _finite(loud.get("input_tp")) if loud else None
        if integrated is not None and abs(integrated - target_lufs) > LOUDNESS_TOLERANCE_LU:
            findings.append(
                Finding(
                    "aviso", "saída", f"loudness integrado {integrated:.1f} LUFS, alvo {target_lufs:.1f} LUFS"
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


# ---------- montagem do relatório ----------


def build_report(
    project: Project,
    *,
    prober: Prober = probe,
    offset_finder: OffsetFinder | None = None,
    output: Path | None = None,
    runner: FFmpegRunner | None = None,
) -> QAReport:
    """Roda as checagens estáticas sempre; as da saída renderizada só quando `output` é informado."""
    layout = project_layout(project, prober, offset_finder)
    findings: list[Finding] = []
    checks: list[str] = []
    for check in STATIC_CHECKS:
        findings.extend(check(project, layout))
        doc = (check.__doc__ or check.__name__).strip().splitlines()[0]
        checks.append(doc)
    if output is not None:
        inspector = OutputInspector(runner or SubprocessRunner(quiet=True), prober)
        findings.extend(inspector.inspect(output, layout.total, layout.preset, project.audio.target_lufs))
        checks.append("saída renderizada (duração, resolução, quadros pretos, silêncio, loudness)")
    return QAReport(project.name, layout.total, findings, checks, preset=layout.preset.id)
