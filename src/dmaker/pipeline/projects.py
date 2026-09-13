"""Serviços de projeto usados pela CLI e pelo servidor MCP: criar, carregar, validar, editar rápido."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import PROJECTS_DIR
from ..domain.brand import Theme, load_theme
from ..domain.presets import Preset, get_preset
from ..domain.spec import (
    AudioSettings,
    Captions,
    ClipSegment,
    ImageOverlay,
    ImageSegment,
    Music,
    Output,
    ProgressBar,
    Project,
    Reframe,
    TextOverlay,
    Transition,
)
from ..domain.timeline import segment_duration, timeline_total, transitions_of
from ..media.ffmpeg import SubprocessRunner
from ..media.probe import probe
from .context import Prober
from .lint import lint
from .sources import resolve_session, resolve_sources
from .sync import OffsetFinder, SyncResolver, ffmpeg_offset_finder


def project_path(name_or_path: str | Path) -> Path:
    """Aceita o caminho de uma spec.json ou o nome de um projeto em projects/."""
    p = Path(name_or_path)
    if p.suffix == ".json":
        return p
    return PROJECTS_DIR / str(name_or_path) / "spec.json"


def parse_segments(value: str | None) -> tuple[int, int] | None:
    """ "3-6" -> (3, 6); "4" -> (4, 4)."""
    if not value:
        return None
    first, _, last = value.partition("-")
    return int(first), int(last or first)


def load_project(name_or_path: str | Path) -> Project:
    path = project_path(name_or_path)
    if not path.exists():
        raise FileNotFoundError(f"Spec não encontrada: {path}")
    return Project.load(path)


def save_project(project: Project, folder: Path | None = None) -> Path:
    folder = folder or PROJECTS_DIR / project.name
    path = project.save(folder / "spec.json")
    project.base_dir = folder.resolve()
    return path


@dataclass
class SegmentSummary:
    index: int
    type: str
    duration: float
    label: str


@dataclass
class ProjectSummary:
    name: str
    preset: Preset
    theme: Theme
    total: float
    segments: list[SegmentSummary] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    offsets: dict[str, float] = field(
        default_factory=dict
    )  # fontes sincronizadas: início no relógio da sessão


def summarize(
    project: Project, prober: Prober = probe, offset_finder: OffsetFinder | None = None
) -> ProjectSummary:
    """Confere arquivos, calcula a duração final e reúne avisos (o que `dmaker validate` mostra).
    Fontes com `sync: "auto"` são sincronizadas aqui (e o resultado fica em cache no projeto)."""
    theme = load_theme(project.brand, project.theme)
    preset = get_preset(project.output.preset)
    finder = offset_finder or ffmpeg_offset_finder(SubprocessRunner(quiet=True))
    store = (project.base_dir / "sync.json") if project.base_dir else None
    offsets = SyncResolver(finder).resolve(project, store)
    session = resolve_session(project, prober, offsets)
    sources = resolve_sources(project, prober, session)
    infos = [s.info for s in sources]
    durations = [
        segment_duration(seg, s.info, s.offset) for seg, s in zip(project.timeline, sources, strict=True)
    ]
    total = timeline_total(durations, transitions_of(project.timeline))
    warnings = lint(project, theme, preset, total, durations, infos, [s.offset for s in sources])
    segments = []
    for i, (seg, d) in enumerate(zip(project.timeline, durations, strict=True)):
        label = getattr(seg, "label", None) or getattr(seg, "src", None) or getattr(seg, "source", None)
        label = label or getattr(seg, "title", "")
        segments.append(SegmentSummary(i, seg.type, d, str(label)))
    return ProjectSummary(project.name, preset, theme, total, segments, warnings, offsets)


def scaffold_project(
    name: str,
    preset: str = "instagram/reels",
    sources: list[Path] | None = None,
    brand: str | None = None,
    captions: bool = True,
    logo: bool = False,
    prober: Prober = probe,
) -> Project:
    """Projeto inicial a partir dos arquivos fonte, na ordem, com transições suaves."""
    get_preset(preset)
    timeline: list = []
    for i, src in enumerate(sources or []):
        if not src.exists():
            raise FileNotFoundError(f"Fonte não encontrada: {src}")
        info = prober(src)
        transition = Transition(type="fade", duration=0.4) if i > 0 else None
        if info.is_image:
            timeline.append(ImageSegment(src=str(src.resolve()), duration=3, transition=transition))
        else:
            timeline.append(ClipSegment(src=str(src.resolve()), transition=transition, label=src.stem))
    if not timeline:
        timeline.append(ClipSegment(src="COLOQUE_O_CAMINHO_DO_VIDEO.mp4"))
    overlays: list = [ProgressBar()]
    if logo:
        overlays.insert(0, ImageOverlay(src="logo", position="top-right", width=0.22))
    return Project(
        name=name,
        output=Output(preset=preset),
        brand=brand,
        timeline=timeline,
        overlays=overlays,
        captions=Captions(source="auto") if captions else None,
    )


def quick_project(
    src: Path,
    preset: str = "instagram/reels",
    start: float = 0.0,
    end: float | None = None,
    reframe: str = "auto",
    brand: str | None = None,
    captions: bool = False,
    logo: bool = False,
    hook: str | None = None,
    cta: str | None = None,
    music: Path | None = None,
    prober: Prober = probe,
) -> Project:
    """Um vídeo só: corte + formato + (legenda, logo, gancho, CTA, música)."""
    if not src.exists():
        raise FileNotFoundError(f"Fonte não encontrada: {src}")
    info = prober(src)
    clip_end = end if end is not None else info.duration
    total = clip_end - start
    overlays: list = [ProgressBar()]
    if logo:
        overlays.append(ImageOverlay(src="logo"))
    if hook:
        overlays.append(TextOverlay(text=hook, role="hook", start=0, end=min(3.5, total)))
    if cta:
        overlays.append(TextOverlay(text=cta, role="cta", start=max(total - 4, 0), end=total))
    return Project(
        name=f"quick_{src.stem}",
        output=Output(preset=preset),
        brand=brand,
        timeline=[ClipSegment(src=str(src.resolve()), start=start, end=end, reframe=Reframe(mode=reframe))],
        overlays=overlays,
        captions=Captions(source="auto") if captions else None,
        audio=AudioSettings(music=Music(src=str(music.resolve())) if music else None),
    )
