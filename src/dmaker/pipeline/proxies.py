"""Proxies 540p H.264 para a prévia ao vivo na interface: geração em segundo plano e status.

A linha do tempo no navegador toca os arquivos originais por `/api/file`, mas o Chrome não decodifica
HEVC/ProRes; por isso cada fonte de vídeo do projeto ganha um proxy leve (`filtergraph/proxy.py`)
guardado em `cache/proxy`.
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .. import config
from ..domain.spec import ClipSegment, Project, VideoOverlay
from ..filtergraph.proxy import proxy_command
from ..media.ffmpeg import FFmpegRunner, ProgressSink
from ..media.probe import VIDEO_EXTS, probe
from .context import Prober

PROXY_VERSION = "p1"  # muda quando a receita do proxy muda (invalida o cache; ver filtergraph/proxy.py)

# tentativas de troca do tmp pelo proxy final antes de desistir; no Windows o ffmpeg às vezes ainda
# segura o handle do arquivo por um instante depois de o processo sair (PermissionError WinError 32)
REPLACE_ATTEMPTS = 3
REPLACE_RETRY_DELAY_S = 0.3


def proxy_path(src: Path) -> Path:
    """Nome do proxy no cache: hash do caminho resolvido, data de modificação, tamanho e versão da
    receita, para que uma fonte trocada ou reeditada gere um proxy novo em vez de reaproveitar um velho."""
    resolved = src.resolve()
    st = resolved.stat()
    raw = f"{resolved.as_posix()}|{st.st_mtime_ns}|{st.st_size}|{PROXY_VERSION}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return config.PROXY_DIR / f"{digest}.mp4"


def _origin_paths(project: Project, src: str | None, source: str | None) -> list[str]:
    """Caminhos (ainda relativos ao projeto) de um clipe ou PiP: `src` direto ou todos os arquivos de
    uma fonte nomeada. Fonte com `parts` entra por inteiro, porque o trecho pode cair em qualquer
    parte e a prévia toca a que grava aquele instante."""
    if src:
        return [src]
    assert source is not None  # garantido pelo validador de ClipSegment/VideoOverlay (um dos dois)
    return project.sources[source].files


def project_video_sources(project: Project) -> list[Path]:
    """Vídeos usados nos clipes e nas sobreposições de PiP da linha do tempo, resolvidos pelo
    `base_dir` do projeto e sem repetir (cartões e imagens não entram). Fonte com `parts` traz todas
    as partes."""
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
            for raw in _origin_paths(project, seg.src, seg.source):
                add(raw)
    for overlay in project.overlays:
        if isinstance(overlay, VideoOverlay):
            for raw in _origin_paths(project, overlay.src, overlay.source):
                add(raw)
    return paths


@dataclass
class ProxyStatus:
    src: Path
    proxy: Path | None  # None quando o original sumiu: o nome do proxy depende da data e do tamanho dele
    ready: bool
    missing: bool = False  # o original não está no disco: não há o que gerar, e a prévia o marca


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
            if not src.exists():
                out.append(ProxyStatus(src, None, False, missing=True))
                continue
            proxy = proxy_path(src)
            out.append(ProxyStatus(src, proxy, proxy.exists()))
        return out

    def build(self, project: Project, sink: ProgressSink | None = None) -> list[ProxyStatus]:
        """Gera os proxies que faltam (pula os já prontos). Cada um nasce num arquivo temporário
        exclusivo desta execução e só vira o nome final depois de pronto, para nunca deixar um proxy
        pela metade nem colidir com outro job de proxies gerando a mesma fonte ao mesmo tempo.
        Informa o progresso por fonte concluída em `sink`."""
        statuses = self.status(project)
        todo = [item for item in statuses if not item.ready and not item.missing]
        if sink:
            sink.start("proxies de prévia", len(todo))
        for done, item in enumerate(todo):
            if self.log:
                self.log(f"gerando proxy: {item.src.name}")
            self._build_one(item)
            if sink:
                sink.update(done + 1)
        if sink:
            sink.finish()
        return statuses

    def _build_one(self, item: ProxyStatus) -> None:
        """Gera um proxy num `.tmp` só desta execução (pid + id aleatório, nunca reaproveitado entre
        chamadas); se o proxy final já existir quando terminar (outro processo terminou antes), o
        nosso tmp é descartado em vez de sobrescrevê-lo. Nunca deixa um `.tmp` para trás, mesmo com
        erro no meio (finally)."""
        assert item.proxy is not None  # só se gera o que existe (ver `build`)
        info = self.prober(item.src)
        item.proxy.parent.mkdir(parents=True, exist_ok=True)
        tmp = item.proxy.with_name(
            f"{item.proxy.stem}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}{item.proxy.suffix}"
        )
        try:
            self.runner.run(proxy_command(item.src, tmp, info))
            if item.proxy.exists():
                pass  # outro processo já terminou este mesmo proxy; o nosso tmp é redundante
            else:
                self._replace_with_retry(tmp, item.proxy)
        finally:
            tmp.unlink(missing_ok=True)
        item.ready = True

    def _replace_with_retry(self, tmp: Path, proxy: Path) -> None:
        """Poucas tentativas curtas absorvem o caso comum no Windows de o arquivo ainda estar em uso
        por um instante depois do ffmpeg sair, sem mascarar um `PermissionError` persistente."""
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                tmp.replace(proxy)
                return
            except PermissionError:
                if attempt == REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(REPLACE_RETRY_DELAY_S)
