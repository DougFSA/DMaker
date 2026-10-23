"""Isolamento vocal de um arquivo ou de um trecho dele, com cache em disco.

Separar a voz custa vários minutos de CPU, então o resultado de cada trecho de cada arquivo fica em
`cache/stems/<chave>/`. A chave nasce do arquivo (caminho, tamanho e data), do trecho, da faixa de áudio,
do modelo e da versão da receita: mudou qualquer um, separa de novo; senão, devolve o que já existe.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Literal

from ..config import STEMS_DIR
from ..filtergraph.stems import convert_stem, extract_for_separation
from ..media.ffmpeg import FFmpegRunner
from ..media.separation import DemucsSeparator, ProgressCallback, Stems, VocalSeparator

RECIPE_VERSION = "i1"  # muda quando a extração ou a montagem dos stems mudam (invalida o cache)
AudioFormat = Literal["wav", "mp3"]
EXPORT_ROLES = (("voz", "vocals"), ("fundo", "background"))
PROGRESS_STEP = 20  # percentual entre uma linha de progresso e a seguinte no log do render


def _time_part(seconds: float | None) -> str | None:
    """Tempo em milissegundos inteiros: 12 e 12.0004 são o mesmo trecho para o cache."""
    return None if seconds is None else f"{seconds:.3f}"


def progress_logger(log: Callable[[str], None], label: str, step: int = PROGRESS_STEP) -> ProgressCallback:
    """Callback de progresso que escreve uma linha a cada `step` por cento (e nunca repete a mesma)."""
    last = -1

    def report(done: int, total: int) -> None:
        nonlocal last
        percent = int(100 * done / max(total, 1)) // step * step
        if percent != last:
            last = percent
            log(f"{label}: {done} de {total} blocos ({percent}%)")

    return report


class IsolationService:
    """Extrai o áudio (ffmpeg, pelo runner) e o entrega ao separador, guardando o resultado em cache."""

    def __init__(
        self,
        separator: VocalSeparator,
        runner: FFmpegRunner,
        cache_dir: Path | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.separator = separator
        self.runner = runner
        self.cache_dir = cache_dir or STEMS_DIR
        self.log = log or (lambda message: None)
        self._lock = threading.Lock()  # separar é pesado e o modelo é um só: um trecho por vez

    # -- cache --

    def key(self, src: Path, start: float | None, end: float | None, audio_stream: int = 0) -> str:
        """Chave estável do trecho: não separa nada, só lê o arquivo (tamanho e data)."""
        stat = src.stat()
        parts = [
            RECIPE_VERSION,
            self.separator.model_id,
            str(src.resolve()),
            stat.st_size,
            stat.st_mtime_ns,
            _time_part(start),
            _time_part(end),
            audio_stream,
        ]
        return hashlib.sha256(json.dumps(parts).encode("utf-8")).hexdigest()[:20]

    def stems_for(self, src: Path, start: float | None, end: float | None, audio_stream: int = 0) -> Stems:
        """Onde os stems do trecho ficam (ou ficarão): serve ao dry-run e à chave de cache do mezanino."""
        return Stems.in_directory(self.cache_dir / self.key(src, start, end, audio_stream))

    # -- separação --

    def isolate(
        self,
        src: Path,
        start: float | None = None,
        end: float | None = None,
        audio_stream: int = 0,
        on_progress: ProgressCallback | None = None,
    ) -> Stems:
        """Voz e fundo de `src` entre `start` e `end` (segundos no arquivo; sem eles, o arquivo todo)."""
        if not src.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {src}")
        if start is not None and start < 0:
            raise ValueError(f"start ({start}) não pode ser negativo")
        if start is not None and end is not None and end <= start:
            raise ValueError(f"end ({end}) precisa ser maior que start ({start})")
        with self._lock:
            final = self.stems_for(src, start, end, audio_stream)
            if final.exist():
                return final
            return self._separate(src, start, end, audio_stream, final, on_progress)

    def _separate(
        self,
        src: Path,
        start: float | None,
        end: float | None,
        audio_stream: int,
        final: Stems,
        on_progress: ProgressCallback | None,
    ) -> Stems:
        """Trabalha numa pasta temporária e a renomeia no fim: uma separação interrompida não deixa meia
        entrada no cache."""
        target = final.vocals.parent
        work = target.with_name(target.name + ".tmp")
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        try:
            extracted = work / "input.wav"
            self.runner.run(extract_for_separation(src, extracted, start, end, audio_stream))
            self.separator.separate(extracted, work, on_progress)
            extracted.unlink(missing_ok=True)
            shutil.rmtree(target, ignore_errors=True)
            work.replace(target)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        return final

    # -- exportação --

    def export(
        self,
        src: Path,
        out_dir: Path,
        audio_format: AudioFormat = "wav",
        start: float | None = None,
        end: float | None = None,
        audio_stream: int = 0,
        on_progress: ProgressCallback | None = None,
    ) -> Stems:
        """Grava a voz e o fundo em `out_dir` (`<nome>_voz` e `<nome>_fundo`) e devolve os caminhos."""
        stems = self.isolate(src, start, end, audio_stream, on_progress)
        out_dir.mkdir(parents=True, exist_ok=True)
        written = {}
        for role, attribute in EXPORT_ROLES:
            source = getattr(stems, attribute)
            target = out_dir / export_name(src, role, audio_format, start, end)
            if audio_format == "wav":
                shutil.copyfile(source, target)
            else:
                self.runner.run(convert_stem(source, target, label=f"{role} em {audio_format}"))
            written[attribute] = target
        return Stems(written["vocals"], written["background"])


def export_name(
    src: Path, role: str, audio_format: str, start: float | None = None, end: float | None = None
) -> str:
    """Nome do arquivo exportado: o trecho entra no nome para dois recortes do mesmo arquivo não se sobrescreverem."""
    window = ""
    if start is not None or end is not None:
        finish = "fim" if end is None else f"{end:g}"
        window = f"_{start or 0:g}-{finish}s"
    return f"{src.stem}{window}_{role}.{audio_format}"


@lru_cache(maxsize=1)
def shared_separator() -> DemucsSeparator:
    """Um separador por processo: o modelo (30 s para carregar) fica na memória entre separações."""
    return DemucsSeparator()


def default_isolation_service(
    runner: FFmpegRunner, log: Callable[[str], None] | None = None
) -> IsolationService:
    """Serviço de produção: Demucs htdemucs (o modelo só carrega na primeira separação)."""
    return IsolationService(shared_separator(), runner, log=log)
