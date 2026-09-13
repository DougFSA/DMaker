"""Informações de mídia (duração, tamanho, fps, rotação, áudio) via ffprobe."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

from .ffmpeg import probe_json

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}


@dataclass(frozen=True)
class MediaInfo:
    path: Path
    duration: float
    width: int
    height: int
    fps: float
    has_video: bool
    has_audio: bool
    is_image: bool
    rotation: int = 0
    video_codec: str | None = None
    audio_codec: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    size_bytes: int = 0

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 0.0

    @property
    def orientation(self) -> str:
        if not self.width or not self.height:
            return "?"
        if abs(self.aspect - 1) < 0.02:
            return "quadrado"
        return "vertical" if self.aspect < 1 else "horizontal"

    def summary(self) -> str:
        parts = [f"{self.width}x{self.height}", f"{self.duration:.2f}s"]
        if self.has_video and not self.is_image:
            parts.append(f"{self.fps:.3g}fps")
        parts.append("com áudio" if self.has_audio else "sem áudio")
        if self.rotation:
            parts.append(f"rotação {self.rotation} graus")
        return " | ".join(parts)


def _parse_rate(value: str | None) -> float:
    if not value or value in ("0/0", "N/A"):
        return 0.0
    try:
        return float(Fraction(value))
    except (ValueError, ZeroDivisionError):
        return 0.0


def _rotation(stream: dict) -> int:
    rot = 0
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            try:
                rot = int(round(float(sd["rotation"])))
            except (TypeError, ValueError):
                pass
    tag = (stream.get("tags") or {}).get("rotate")
    if tag:
        try:
            rot = int(tag)
        except ValueError:
            pass
    return rot % 360


@lru_cache(maxsize=256)
def _probe_cached(path_str: str, mtime_ns: int, size: int) -> MediaInfo:
    path = Path(path_str)
    data = probe_json(path)
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    is_image = path.suffix.lower() in IMAGE_EXTS
    if v and not is_image and (v.get("disposition") or {}).get("attached_pic"):
        # capa embutida em mp3/m4a aparece como stream de vídeo
        v = None
    duration = 0.0
    for cand in (fmt.get("duration"), (v or {}).get("duration"), (a or {}).get("duration")):
        try:
            duration = float(cand)
            break
        except (TypeError, ValueError):
            continue
    if is_image:
        duration = 0.0
    width = int((v or {}).get("width") or 0)
    height = int((v or {}).get("height") or 0)
    rotation = _rotation(v) if v else 0
    if rotation in (90, 270):
        width, height = height, width
    fps = _parse_rate((v or {}).get("avg_frame_rate")) or _parse_rate((v or {}).get("r_frame_rate"))
    return MediaInfo(
        path=path,
        duration=duration,
        width=width,
        height=height,
        fps=fps if not is_image else 0.0,
        has_video=v is not None,
        has_audio=a is not None,
        is_image=is_image,
        rotation=rotation,
        video_codec=(v or {}).get("codec_name"),
        audio_codec=(a or {}).get("codec_name"),
        sample_rate=int(a["sample_rate"]) if a and a.get("sample_rate") else None,
        channels=int(a["channels"]) if a and a.get("channels") else None,
        size_bytes=size,
    )


def probe(path: Path | str) -> MediaInfo:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {p}")
    st = p.stat()
    return _probe_cached(str(p.resolve()), st.st_mtime_ns, st.st_size)
