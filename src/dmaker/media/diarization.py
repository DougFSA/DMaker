"""Diarização: descobre quem fala em cada momento de um áudio, na CPU, sem conta nem token.

O contrato é o protocolo `SpeakerDiarizer`: recebe um WAV mono de 16 kHz (a voz, de preferência já isolada) e
devolve os turnos de fala, cada um com o rótulo legível do falante ("Falante 1", "Falante 2"...). O pipeline só
conhece o protocolo; o sherpa-onnx e os modelos ficam dentro do `SherpaDiarizer` e só carregam na primeira vez.

Escolha: sherpa-onnx (Apache-2.0) com a segmentação pyannote-segmentation-3.0 convertida para ONNX (MIT) e os
embeddings de falante CAM++ do 3D-Speaker (Apache-2.0), baixados das releases oficiais do k2-fsa com versão e
hash fixados. O pyannote oficial foi descartado porque exige aceitar termos e usar um token do Hugging Face.
O SpeechBrain ECAPA seria a alternativa, mas pediria agrupamento e detecção de fala próprios, e ficou de reserva.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from ..config import MODELS_DIR
from .cpu import compute_threads
from .downloads import Downloader, RemoteFile, download_file, ensure_archive_member, ensure_file
from .wavio import read_wav

SAMPLE_RATE = 16000  # taxa em que os modelos de segmentação e de embedding foram treinados
SPEAKER_PREFIX = "Falante"
MIN_SPEAKER_SECONDS = (
    1.0  # menos fala que isto num "falante" é ruído que o agrupamento separou, não uma pessoa
)
MAX_EXTRA_CLUSTERS = 2  # tentativas a mais ao forçar o número de falantes (ver `_forced_clusters`)

ProgressCallback = Callable[[int, int], None]  # (blocos prontos, blocos no total)

_RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
# Versões fixadas (releases `speaker-segmentation-models` e `speaker-recongition-models`, a grafia é do k2-fsa).
SEGMENTATION_ARCHIVE = RemoteFile(
    "sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
    f"{_RELEASES}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
    6958444,
    "24615ee884c897d9d2ba09bb4d30da6bb1b15e685065962db5b02e76e4996488",
)
SEGMENTATION_MEMBER = "sherpa-onnx-pyannote-segmentation-3-0/model.onnx"
SEGMENTATION_MODEL = RemoteFile(
    "pyannote-segmentation-3.0.onnx",
    SEGMENTATION_ARCHIVE.url,
    5992913,
    "220ad67ca923bef2fa91f2390c786097bf305bceb5e261d4af67b38e938e1079",
)
EMBEDDING_MODEL = RemoteFile(
    "3dspeaker_campplus_zh_en_16k_advanced.onnx",
    f"{_RELEASES}/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx",
    28281164,
    "aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2",
)

# Distância (cosseno) abaixo da qual duas vozes contam como a mesma pessoa. 0,5 é o valor das receitas do
# sherpa-onnx; nas medições deste projeto (duas e três vozes sintéticas) separou as vozes sem inventar falantes.
CLUSTER_THRESHOLD = 0.5
MIN_DURATION_ON = 0.3  # descarta "fala" mais curta que isto (estalo, respiração)
MIN_DURATION_OFF = 0.5  # junta dois turnos do mesmo falante separados por menos que esta pausa


@dataclass(frozen=True)
class SpeakerTurn:
    """Um trecho em que `speaker` fala (segundos no áudio analisado)."""

    start: float
    end: float
    speaker: str

    @property
    def duration(self) -> float:
        return self.end - self.start


class SpeakerDiarizer(Protocol):
    model_id: str  # entra na chave do cache de turnos: outro modelo ou outros parâmetros não reaproveitam

    def diarize(
        self, wav: Path, num_speakers: int | None = None, on_progress: ProgressCallback | None = None
    ) -> list[SpeakerTurn]:
        """Turnos de fala de `wav` (mono, 16 kHz), por ordem de início. `num_speakers` força a quantidade;
        sem ele o próprio áudio decide. Os rótulos seguem a ordem em que cada falante aparece."""


# ---------- contas puras ----------


def speaker_label(number: int) -> str:
    """Rótulo legível do falante de número `number` (1 é o primeiro a falar)."""
    return f"{SPEAKER_PREFIX} {number}"


def label_by_appearance(raw: Sequence[tuple[float, float, int]]) -> list[SpeakerTurn]:
    """Turnos com rótulo "Falante N", numerados na ordem em que cada grupo aparece e ordenados por início.

    O agrupamento devolve números de grupo sem significado (0, 2, 5...); quem lê quer "Falante 1" para quem
    abriu a conversa, e o mesmo áudio tem de dar sempre os mesmos rótulos.
    """
    numbers: dict[int, int] = {}
    turns: list[SpeakerTurn] = []
    for start, end, group in sorted(raw, key=lambda item: (item[0], item[1])):
        if end <= start:
            continue
        number = numbers.setdefault(group, len(numbers) + 1)
        turns.append(SpeakerTurn(start, end, speaker_label(number)))
    return turns


def speaking_seconds(turns: Sequence[SpeakerTurn]) -> dict[str, float]:
    """Quanto cada falante fala no total, na ordem em que aparecem."""
    totals: dict[str, float] = {}
    for turn in turns:
        totals[turn.speaker] = totals.get(turn.speaker, 0.0) + turn.duration
    return totals


def drop_negligible_speakers(
    turns: Sequence[SpeakerTurn], min_seconds: float = MIN_SPEAKER_SECONDS
) -> list[SpeakerTurn]:
    """Tira os falantes com menos de `min_seconds` de fala e renumera os que ficam (sem buracos: 1, 2, 3).

    Pedaço de som que o agrupamento isolou vira um "falante" fantasma, que a tabela mostraria como uma
    pessoa a mais; sem fala suficiente ele também não teria voz para clonar.
    """
    totals = speaking_seconds(turns)
    kept = [turn for turn in turns if totals[turn.speaker] >= min_seconds]
    ids = {name: index for index, name in enumerate(dict.fromkeys(t.speaker for t in kept))}
    return label_by_appearance([(t.start, t.end, ids[t.speaker]) for t in kept])


def forced_cluster_counts(num_speakers: int) -> list[int]:
    """Valores de `num_clusters` a tentar para obter `num_speakers` falantes, do pedido para cima.

    O agrupamento do sherpa-onnx conta como "grupo" também o pedacinho de som atípico que ele isola, então
    pedir N grupos costuma entregar N-1 falantes; subir o pedido até bater é mais barato que reimplementar.
    """
    return [num_speakers + extra for extra in range(MAX_EXTRA_CLUSTERS + 1)]


# ---------- sherpa-onnx ----------

RawTurn = tuple[float, float, int]  # (início, fim, número do grupo)


class DiarizationEngine(Protocol):
    def run(
        self, samples: np.ndarray, num_clusters: int, on_progress: ProgressCallback | None
    ) -> list[RawTurn]:
        """Uma passada completa sobre `samples` (16 kHz) com `num_clusters` grupos (-1: o limiar decide)."""


def ensure_models(models_dir: Path, downloader: Downloader = download_file) -> tuple[Path, Path]:
    """Os dois modelos, íntegros em `models_dir` (baixa o que faltar): (segmentação, embedding)."""
    segmentation = ensure_archive_member(
        models_dir, SEGMENTATION_ARCHIVE, SEGMENTATION_MEMBER, SEGMENTATION_MODEL, downloader
    )
    embedding = ensure_file(models_dir, EMBEDDING_MODEL, downloader)
    return segmentation, embedding


class SherpaEngine:
    """O sherpa-onnx de verdade: segmentação pyannote 3.0, embeddings CAM++ e agrupamento hierárquico."""

    def __init__(self, models_dir: Path, threads: int, threshold: float, downloader: Downloader) -> None:
        try:
            import sherpa_onnx
        except ImportError as exc:  # pragma: no cover - depende do ambiente
            raise RuntimeError(
                "sherpa-onnx não instalado. Rode: .venv\\Scripts\\pip install -e .[voice]"
            ) from exc
        self._sherpa = sherpa_onnx
        self._segmentation, self._embedding = ensure_models(models_dir, downloader)
        self._threads = threads
        self._threshold = threshold
        self._clusters = -1
        self._engine = sherpa_onnx.OfflineSpeakerDiarization(self._config(self._clusters))

    def _config(self, num_clusters: int) -> Any:
        sherpa = self._sherpa
        return sherpa.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(self._segmentation)),
                num_threads=self._threads,
            ),
            embedding=sherpa.SpeakerEmbeddingExtractorConfig(
                model=str(self._embedding), num_threads=self._threads
            ),
            clustering=sherpa.FastClusteringConfig(num_clusters=num_clusters, threshold=self._threshold),
            min_duration_on=MIN_DURATION_ON,
            min_duration_off=MIN_DURATION_OFF,
        )

    def run(
        self, samples: np.ndarray, num_clusters: int, on_progress: ProgressCallback | None
    ) -> list[RawTurn]:
        if num_clusters != self._clusters:
            self._engine.set_config(self._config(num_clusters))
            self._clusters = num_clusters

        def progress(done: int, total: int) -> int:
            if on_progress:
                on_progress(int(done), int(total))
            return 0  # diferente de zero cancelaria

        result = self._engine.process(samples, callback=progress).sort_by_start_time()
        return [(float(turn.start), float(turn.end), int(turn.speaker)) for turn in result]


class SherpaDiarizer:
    """Diarização local: carrega o motor uma única vez, na primeira chamada, e baixa os modelos se faltarem.

    `models_dir` é lido na hora do uso (o config pode mudar entre testes). Entende 16 kHz mono; quem chama
    converte (o pipeline usa o ffmpeg, pelo runner).
    """

    def __init__(
        self,
        models_dir: Path | None = None,
        threads: int | None = None,
        threshold: float = CLUSTER_THRESHOLD,
        downloader: Downloader = download_file,
        engine_loader: Callable[[], DiarizationEngine] | None = None,
    ) -> None:
        self._models_dir = models_dir
        self.threads = threads
        self.threshold = threshold
        self.downloader = downloader
        self.model_id = f"sherpa:pyannote-3.0+campplus-zh-en:thr{threshold:g}:on{MIN_DURATION_ON:g}:off{MIN_DURATION_OFF:g}"
        self._engine_loader = engine_loader or self._load_engine
        self._engine: DiarizationEngine | None = None
        self._lock = threading.Lock()  # o motor guarda estado entre chamadas: uma diarização por vez

    @property
    def models_dir(self) -> Path:
        return self._models_dir or MODELS_DIR / "diarization"

    def _load_engine(self) -> DiarizationEngine:
        return SherpaEngine(
            self.models_dir, self.threads or compute_threads(), self.threshold, self.downloader
        )

    def diarize(
        self, wav: Path, num_speakers: int | None = None, on_progress: ProgressCallback | None = None
    ) -> list[SpeakerTurn]:
        if num_speakers is not None and num_speakers < 1:
            raise ValueError("O número de falantes precisa ser 1 ou mais.")
        samples, rate = read_wav(wav)
        if rate != SAMPLE_RATE:
            raise ValueError(
                f"{wav.name}: a diarização precisa de áudio de {SAMPLE_RATE} Hz (recebi {rate} Hz)."
            )
        audio = np.ascontiguousarray(samples, dtype=np.float32)
        with self._lock:
            if self._engine is None:
                self._engine = self._engine_loader()
            if num_speakers is None:
                return drop_negligible_speakers(label_by_appearance(self._engine.run(audio, -1, on_progress)))
            return self._forced(self._engine, audio, num_speakers, on_progress)

    @staticmethod
    def _forced(
        engine: DiarizationEngine, audio: np.ndarray, num_speakers: int, on_progress: ProgressCallback | None
    ) -> list[SpeakerTurn]:
        """Turnos com exatamente `num_speakers` falantes, se o áudio permitir; senão, a tentativa mais perto."""
        best: tuple[int, list[SpeakerTurn]] | None = None
        for clusters in forced_cluster_counts(num_speakers):
            turns = label_by_appearance(engine.run(audio, clusters, on_progress))
            gap = abs(len(speaking_seconds(turns)) - num_speakers)
            if gap == 0:
                return turns
            if best is None or gap < best[0]:
                best = (gap, turns)
        assert best is not None  # forced_cluster_counts nunca devolve lista vazia
        return best[1]
