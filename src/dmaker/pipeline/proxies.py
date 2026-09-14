"""Proxies 540p H.264 para a prévia ao vivo na interface: geração em segundo plano e status.

A linha do tempo no navegador toca os arquivos originais por `/api/file`, mas o Chrome não decodifica
HEVC/ProRes; por isso cada fonte de vídeo do projeto ganha um proxy leve (`filtergraph/proxy.py`)
guardado em `cache/proxy`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .. import config
from ..domain.spec import ClipSegment, Project, VideoOverlay
from ..filtergraph.proxy import proxy_command
from ..media.ffmpeg import FFmpegRunner, ProgressSink
from ..media.probe import probe
from .context import Prober

PROXY_VERSION = "p1"  # muda quando a receita do proxy muda (invalida o cache; ver filtergraph/proxy.py)
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


def proxy_path(src: Path) -> Path:
    """Nome do proxy no cache: hash do caminho resolvido, data de modificação, tamanho e versão da
    receita, para que uma fonte trocada ou reeditada gere um proxy novo em vez de reaproveitar um velho."""
    resolved = src.resolve()
    st = resolved.stat()
    raw = f"{resolved.as_posix()}|{st.st_mtime_ns}|{st.st_size}|{PROXY_VERSION}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return config.PROXY_DIR / f"{digest}.mp4"


def _origin_path(project: Project, src: str | None, source: str | None) -> str:
    """Caminho (ainda relativo ao projeto) de um clipe ou PiP: `src` direto ou o de uma fonte nomeada."""
    if src:
        return src
    assert source is not None  # garantido pelo validador de ClipSegment/VideoOverlay (um dos dois)
    return project.sources[source].src


def project_video_sources(project: Project) -> list[Path]:
    """Vídeos usados nos clipes e nas sobreposições de PiP da linha do tempo, resolvidos pelo
    `base_dir` do projeto e sem repetir (cartões e imagens não entram)."""
    paths: list[Path] = []
    seen: set[Path] = set()

    def add(raw: str) -> None:
        path = project.resolve(raw)
        if path.suffix.lower() not in VIDEO_EXTS or path in seen:
            return
        seen.add(path)
        paths.append(path)

    for seg in project.timeline:
        if isinstance(seg, ClipSegment):
            add(_origin_path(project, seg.src, seg.source))
    for overlay in project.overlays:
        if isinstance(overlay, VideoOverlay):
            add(_origin_path(project, overlay.src, overlay.source))
    return paths


@dataclass
class ProxyStatus:
    src: Path
    proxy: Path
    ready: bool


class ProxyBuilder:
    """Gera (em segundo plano) e consulta os proxies 540p das fontes de vídeo de um projeto."""

    def __init__(
        self, runner: FFmpegRunner, prober: Prober = probe, log: Callable[[str], None] | None = None
    ):
        self.runner = runner
        self.prober = prober
        self.log = log

    def status(self, project: Project) -> list[ProxyStatus]:
        out = []
        for src in project_video_sources(project):
            proxy = proxy_path(src)
            out.append(ProxyStatus(src, proxy, proxy.exists()))
        return out

    def build(self, project: Project, sink: ProgressSink | None = None) -> list[ProxyStatus]:
        """Gera os proxies que faltam (pula os já prontos). Cada um nasce num arquivo temporário no
        próprio cache e só vira o nome final depois de pronto, para nunca deixar um proxy pela metade
        se o processo for interrompido no meio. Informa o progresso por fonte concluída em `sink`."""
        statuses = self.status(project)
        todo = [item for item in statuses if not item.ready]
        if sink:
            sink.start("proxies de prévia", len(todo))
        for done, item in enumerate(todo):
            if self.log:
                self.log(f"gerando proxy: {item.src.name}")
            info = self.prober(item.src)
            item.proxy.parent.mkdir(parents=True, exist_ok=True)
            tmp = item.proxy.with_name(f"{item.proxy.stem}.tmp{item.proxy.suffix}")
            self.runner.run(proxy_command(item.src, tmp, info))
            tmp.replace(item.proxy)
            item.ready = True
            if sink:
                sink.update(done + 1)
        if sink:
            sink.finish()
        return statuses
