"""Parâmetros de codificação por preset, qualidade e encoder."""

from __future__ import annotations

from ..domain.presets import Preset

# medium tem a mesma qualidade do slow no mesmo CRF (medido: PSNR 49.26 vs 49.29 dB) e é 1.5x mais rápido
X264_PRESET = {"max": "slow", "high": "medium", "medium": "fast", "draft": "ultrafast"}
HARDWARE_ENCODERS = ("nvenc", "qsv", "amf")
MEZZANINE_VIDEO = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p"]


def crf_for(preset: Preset, quality: str) -> int:
    return {"max": preset.crf, "high": preset.crf, "medium": preset.crf + 3, "draft": 28}[quality]


def resolve_encoder(requested: str, hardware: str | None) -> str:
    """`auto` usa o encoder de hardware detectado (nvenc > qsv > amf) ou cai no x264."""
    if requested == "auto":
        return hardware or "x264"
    return requested


def _video_encoder_args(preset: Preset, crf: int, quality: str, encoder: str) -> list[str]:
    maxrate = f"{preset.maxrate_k}k"
    bufsize = f"{preset.maxrate_k * 2}k"
    if encoder == "x264":
        return [
            "-c:v",
            "libx264",
            "-preset",
            X264_PRESET[quality],
            "-crf",
            str(crf),
            "-profile:v",
            "high",
            "-level",
            preset.level,
            "-maxrate",
            maxrate,
            "-bufsize",
            bufsize,
            "-bf",
            "2",
            "-coder",
            "1",
            "-sc_threshold",
            "0",
        ]
    if encoder == "nvenc":
        return [
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p6",
            "-tune",
            "hq",
            "-rc",
            "vbr",
            "-cq",
            str(crf + 1),
            "-b:v",
            "0",
            "-maxrate",
            maxrate,
            "-bufsize",
            bufsize,
            "-profile:v",
            "high",
            "-spatial-aq",
            "1",
            "-temporal-aq",
            "1",
            "-bf",
            "2",
        ]
    if encoder == "amf":
        return [
            "-c:v",
            "h264_amf",
            "-quality",
            "quality",
            "-rc",
            "vbr_peak",
            "-b:v",
            f"{int(preset.maxrate_k * 0.7)}k",
            "-maxrate",
            maxrate,
            "-bufsize",
            bufsize,
            "-profile:v",
            "high",
        ]
    if encoder == "qsv":
        return [
            "-c:v",
            "h264_qsv",
            "-preset",
            "slower",
            "-global_quality",
            str(crf + 2),
            "-look_ahead",
            "1",
            "-profile:v",
            "high",
            "-maxrate",
            maxrate,
            "-bufsize",
            bufsize,
        ]
    raise ValueError(f"encoder desconhecido: {encoder}")


def encode_args(preset: Preset, quality: str, encoder: str, fps: float) -> list[str]:
    """Vídeo H.264 High + AAC 48 kHz, GOP de 2 s, cores BT.709 e faststart: o que as plataformas pedem."""
    args = _video_encoder_args(preset, crf_for(preset, quality), quality, encoder)
    args += [
        "-pix_fmt",
        "yuv420p",
        "-r",
        f"{fps:g}",
        "-fps_mode",
        "cfr",
        "-g",
        str(int(round(fps * 2))),
        "-keyint_min",
        str(int(round(fps))),
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-colorspace",
        "bt709",
        "-c:a",
        "aac",
        "-b:a",
        f"{preset.audio_k}k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        "-max_muxing_queue_size",
        "1024",
    ]
    return args


def mezzanine_output_args(fps: float, duration: float, out: str) -> list[str]:
    """Intermediário quase sem perdas: x264 CRF 14 + PCM, duração exata, CFR."""
    return [
        *MEZZANINE_VIDEO,
        "-r",
        f"{fps:g}",
        "-fps_mode",
        "cfr",
        "-c:a",
        "pcm_s16le",
        "-t",
        f"{duration:.3f}",
        out,
    ]
