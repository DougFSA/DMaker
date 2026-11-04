"""Gravações do microfone no projeto: o navegador manda o som em pedaços de um segundo, o servidor guarda cada um na hora
e, no fim, junta tudo num WAV. Se a aba fecha no meio, o que chegou até ali já está no disco e pode ser recuperado.

Em disco, em `<projeto>/recordings/<id>/`: um `meta.json` com o formato e o contexto da gravação (onde ela cai na linha
do tempo, se foi um punch-in) e um arquivo por pedaço (`000000.f32`, float32 little-endian intercalado, o que o
navegador captura, sem compressão). O `seq` do pedaço é o nome do arquivo, então mandar o mesmo pedaço duas vezes (a
rede caiu e o cliente repetiu) escreve no mesmo lugar e não duplica nada. O `finish` junta os pedaços em
`gravacao.wav` (float32) e apaga os pedaços; um pedaço que nunca chegou vira silêncio do mesmo tamanho, e a resposta diz
quais faltaram.

Nada aqui conhece HTTP nem a spec: é o miolo das rotas (`ui/recording_routes.py`) e da CLI.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..media.wavio import write_wav_float_stream

RECORDINGS_DIR = "recordings"
META_FILE = "meta.json"
RESULT_FILE = "gravacao.wav"
CHUNK_SUFFIX = ".f32"
CHUNK_NAME = re.compile(r"^(\d{6,})\.f32$")
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

MAX_SEQ = 1_000_000  # um pedaço por segundo: bem mais que o dia inteiro; só barra número inventado
MAX_CHUNK_BYTES = (
    16 * 1024 * 1024
)  # um segundo de 8 canais a 192 kHz em float32 é 6 MB: isto só barra o que não é áudio
SAMPLE_BYTES = 4
MIN_RATE, MAX_RATE = 8000, 192_000
MAX_CHANNELS = 2

# gravar e finalizar mexem nos mesmos arquivos: um trinco por pasta de gravação evita um `finish` correndo com um `put`
_locks_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


def _lock_for(folder: Path) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(str(folder), threading.Lock())


class RecordingError(ValueError):
    """O pedido não faz sentido (formato, número do pedaço, gravação que não existe ou já foi finalizada)."""


class RecordingNotFound(RecordingError):
    pass


@dataclass(frozen=True)
class ChunkReceipt:
    seq: int
    bytes: int
    duplicate: bool  # o pedaço já estava lá (reenvio): nada foi duplicado

    def to_dict(self) -> dict[str, Any]:
        return {"seq": self.seq, "bytes": self.bytes, "duplicate": self.duplicate}


@dataclass(frozen=True)
class RecordingStatus:
    id: str
    state: str  # open | finished
    rate: int
    channels: int
    start: float
    label: str
    created_at: str
    chunks: int
    frames: int
    gaps: tuple[int, ...]
    src: str | None  # o WAV, relativo à pasta do projeto, quando finalizada
    punch: dict[str, Any] | None
    device: str

    @property
    def duration(self) -> float:
        return self.frames / self.rate if self.rate else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "state": self.state,
            "rate": self.rate,
            "channels": self.channels,
            "start": self.start,
            "label": self.label,
            "created_at": self.created_at,
            "chunks": self.chunks,
            "frames": self.frames,
            "duration": round(self.duration, 3),
            "gaps": list(self.gaps),
            "src": self.src,
            "punch": self.punch,
            "device": self.device,
        }


def _chunk_files(folder: Path) -> dict[int, Path]:
    found: dict[int, Path] = {}
    for entry in folder.iterdir():
        match = CHUNK_NAME.match(entry.name)
        if match:
            found[int(match.group(1))] = entry
    return found


def missing_chunks(received: set[int]) -> tuple[int, ...]:
    """Os números de pedaço que faltam entre o primeiro (0) e o último que chegou."""
    if not received:
        return ()
    return tuple(seq for seq in range(max(received) + 1) if seq not in received)


class RecordingStore:
    """As gravações de um projeto, em `<pasta do projeto>/recordings`."""

    def __init__(self, project_dir: Path) -> None:
        self.root = project_dir / RECORDINGS_DIR

    # ---------- abrir, receber, listar ----------

    def create(
        self,
        rate: int,
        channels: int,
        start: float = 0.0,
        label: str = "",
        punch: dict[str, Any] | None = None,
        device: str = "",
    ) -> RecordingStatus:
        if not MIN_RATE <= rate <= MAX_RATE:
            raise RecordingError(f"taxa de amostragem fora da faixa ({MIN_RATE} a {MAX_RATE} Hz): {rate}")
        if not 1 <= channels <= MAX_CHANNELS:
            raise RecordingError("a gravação é mono (1) ou estéreo (2)")
        identifier = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        folder = self.root / identifier
        folder.mkdir(parents=True, exist_ok=False)
        meta = {
            "id": identifier,
            "state": "open",
            "rate": int(rate),
            "channels": int(channels),
            "start": float(start),
            "label": label[:80],
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "punch": punch,
            "device": device[:120],
        }
        self._write_meta(folder, meta)
        return self.status(identifier)

    def put_chunk(self, identifier: str, seq: int, data: bytes) -> ChunkReceipt:
        folder = self._folder(identifier)
        meta = self._read_meta(folder)
        if meta["state"] != "open":
            raise RecordingError("esta gravação já foi finalizada: não recebe mais pedaços")
        if not 0 <= seq <= MAX_SEQ:
            raise RecordingError(f"número de pedaço fora da faixa: {seq}")
        frame = meta["channels"] * SAMPLE_BYTES
        if not data or len(data) % frame:
            raise RecordingError(
                f"o pedaço {seq} não tem quadros inteiros de {meta['channels']} canal(is) float32"
            )
        if len(data) > MAX_CHUNK_BYTES:
            raise RecordingError(f"o pedaço {seq} passa de {MAX_CHUNK_BYTES // 1024 // 1024} MB")
        target = folder / f"{seq:06d}{CHUNK_SUFFIX}"
        with _lock_for(folder):
            duplicate = target.exists() and target.stat().st_size == len(data)
            if not duplicate:
                partial = target.with_name(target.name + ".part")
                partial.write_bytes(data)
                os.replace(
                    partial, target
                )  # só aparece com o nome final inteiro: a queda no meio não deixa pedaço cortado
        return ChunkReceipt(seq, len(data), duplicate)

    def status(self, identifier: str) -> RecordingStatus:
        folder = self._folder(identifier)
        meta = self._read_meta(folder)
        files = _chunk_files(folder)
        frame = meta["channels"] * SAMPLE_BYTES
        frames = sum(path.stat().st_size for path in files.values()) // frame
        finished = meta["state"] == "finished"
        if finished:
            frames = int(meta.get("frames", frames))
        return RecordingStatus(
            id=identifier,
            state=meta["state"],
            rate=meta["rate"],
            channels=meta["channels"],
            start=meta["start"],
            label=meta.get("label", ""),
            created_at=meta.get("created_at", ""),
            chunks=len(files) if not finished else int(meta.get("chunks", 0)),
            frames=frames,
            gaps=tuple(meta.get("gaps", ())) if finished else missing_chunks(set(files)),
            src=f"{RECORDINGS_DIR}/{identifier}/{RESULT_FILE}" if finished else None,
            punch=meta.get("punch"),
            device=meta.get("device", ""),
        )

    def list(self) -> list[RecordingStatus]:
        """Todas as gravações da pasta, as mais novas primeiro."""
        if not self.root.is_dir():
            return []
        found = []
        for folder in sorted(self.root.iterdir(), reverse=True):
            if not (folder / META_FILE).is_file():
                continue
            try:
                found.append(self.status(folder.name))
            except (RecordingError, OSError, KeyError, json.JSONDecodeError):
                continue  # pasta ilegível não derruba a lista
        return found

    def unfinished(self) -> list[RecordingStatus]:
        """As que a aba deixou abertas: o que a interface oferece para recuperar."""
        return [status for status in self.list() if status.state == "open" and status.chunks > 0]

    # ---------- finalizar e descartar ----------

    def finish(
        self,
        identifier: str,
        start: float | None = None,
        label: str | None = None,
        punch: dict[str, Any] | None = None,
    ) -> RecordingStatus:
        """Junta os pedaços que chegaram num WAV float32 e fecha a gravação. Repetir devolve a mesma resposta. `start`,
        `label` e `punch`, se vierem, corrigem o que a abertura guardou (a interface refina o instante e o alvo)."""
        folder = self._folder(identifier)
        with _lock_for(folder):
            meta = self._read_meta(folder)
            if meta["state"] == "finished":
                return self.status(identifier)
            files = _chunk_files(folder)
            if not files:
                raise RecordingError("nenhum pedaço chegou: não há o que finalizar")
            frame = meta["channels"] * SAMPLE_BYTES
            gaps = missing_chunks(set(files))
            nominal = max(path.stat().st_size for path in files.values())  # o tamanho de um pedaço cheio
            total_bytes = sum(path.stat().st_size for path in files.values()) + nominal * len(gaps)
            frames = total_bytes // frame
            write_wav_float_stream(
                folder / RESULT_FILE,
                self._blocks(files, gaps, nominal),
                frames,
                meta["channels"],
                meta["rate"],
            )
            meta.update(
                state="finished",
                frames=frames,
                chunks=len(files),
                gaps=list(gaps),
                finished_at=datetime.now().isoformat(timespec="seconds"),
            )
            if start is not None:
                meta["start"] = float(start)
            if label is not None:
                meta["label"] = label[:80]
            if punch is not None:
                meta["punch"] = punch
            self._write_meta(folder, meta)
            for path in files.values():  # o WAV já tem tudo: os pedaços só ocupariam disco
                path.unlink(missing_ok=True)
        return self.status(identifier)

    @staticmethod
    def _blocks(files: dict[int, Path], gaps: tuple[int, ...], nominal: int) -> Iterator[bytes]:
        silence = bytes(nominal)
        for seq in range(max(files) + 1):
            if seq in files:
                yield files[seq].read_bytes()
            else:
                yield silence

    def discard(self, identifier: str) -> None:
        """Apaga uma gravação aberta (a pessoa desistiu). Uma já finalizada fica: o WAV pode estar na spec."""
        folder = self._folder(identifier)
        if self._read_meta(folder)["state"] == "finished":
            raise RecordingError("esta gravação já foi finalizada e o arquivo pode estar em uso no projeto")
        shutil.rmtree(folder)

    # ---------- disco ----------

    def _folder(self, identifier: str) -> Path:
        if not ID_PATTERN.match(identifier or ""):
            raise RecordingNotFound(f"gravação inválida: {identifier!r}")
        folder = self.root / identifier
        if not (folder / META_FILE).is_file():
            raise RecordingNotFound(f"não há gravação {identifier} neste projeto")
        return folder

    @staticmethod
    def _read_meta(folder: Path) -> dict[str, Any]:
        return json.loads((folder / META_FILE).read_text(encoding="utf-8"))

    @staticmethod
    def _write_meta(folder: Path, meta: dict[str, Any]) -> None:
        partial = folder / (META_FILE + ".part")
        partial.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(partial, folder / META_FILE)


# ---------- a edição que põe a gravação na spec ----------


def edit_for_recording(status: RecordingStatus, recover: bool = False) -> dict[str, Any]:
    """A operação do `edit_project` que põe a gravação finalizada na linha do tempo: um punch-in troca o trecho da voz,
    uma gravação comum vira voz gravada nova. `recover` (a gravação da aba que fechou) sempre vira voz nova, porque o item
    que o punch-in trocaria pode já não estar onde estava."""
    if status.state != "finished" or status.src is None:
        raise RecordingError("a gravação ainda não foi finalizada")
    punch = status.punch
    if punch and not recover:
        return {
            "type": "audio_punch",
            "target": punch["target"],
            "start": punch["start"],
            "end": punch["end"],
            "src": status.src,
            "recorded_at": status.start,
            "duration": round(status.duration, 6),
            "label": status.label,
        }
    return {
        "type": "audio_record_add",
        "src": status.src,
        "start": status.start,
        "duration": round(status.duration, 6),
    }
