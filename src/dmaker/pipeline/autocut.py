"""Serviço `autocut`: de uma gravação falada a um projeto com as pausas, os vícios e as frases repetidas
já cortados, mais a lista do que saiu para o usuário conferir antes de renderizar.

Transcrição, leitura de mídia e ffmpeg entram por protocolo (`Transcriber`, `Prober`, `FFmpegRunner`); a
decisão de onde cortar é a função pura de `voice/cut_plan.py`. O corte vira clipes da mesma gravação na
linha do tempo (a spec não ganha nenhum "modo de corte"), e a lista fica ao lado do projeto
(`autocut.json`) para desfazer um corte depois: `restore_gap` devolve o trecho e as legendas são refeitas.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .. import config
from ..domain.edits import restore_gap
from ..domain.presets import get_preset
from ..domain.spec import Captions, ClipSegment, Output, Project
from ..media.ffmpeg import FFmpegRunner, SubprocessRunner
from ..media.probe import probe
from ..media.wavio import read_wav
from ..text.captions import Cue, Word, flatten_words, from_json, remap_to_ranges, to_json
from ..text.transcribe import Transcriber, WhisperTranscriber, extract_audio_wav
from ..voice.cut_plan import REASON_LABELS, CutOptions, CutPlan, plan_cuts
from .context import Prober
from .projects import load_project, project_path, save_project

REPORT_FILE = "autocut.json"
TRANSCRIPT_FILE = "autocut.transcript.json"  # as palavras com o tempo ajustado, para refazer as legendas
CAPTIONS_FILE = "captions.cut.json"
REPORT_VERSION = 1

# 10 ms: o bastante para o som zerar no corte (sem estalo) e curto demais para se ouvir como queda de volume;
# o corte já cai no vale de energia, então o fade só fecha o que sobra
CUT_FADE_SECONDS = 0.01
# o Whisper omite "hã" e "é..." por padrão; um texto de exemplo com os vícios faz ele transcrevê-los
DISFLUENCY_PROMPT = "Hã... é... tipo, né? Hum, então, éé, a gente vai ver, né."

Reporter = Callable[[str, float], None]  # (etapa, fração de 0 a 1)


@dataclass
class CutRecord:
    """Um trecho removido, como aparece na lista para o usuário conferir."""

    id: int
    start: float  # segundos na gravação original
    end: float
    reason: str
    text: str = ""
    undone: bool = False

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "start_s": round(self.start, 3),
            "end_s": round(self.end, 3),
            "duration_s": round(self.duration, 3),
            "reason": self.reason,
            "reason_label": REASON_LABELS.get(self.reason, self.reason),
            "text": self.text,
            "undone": self.undone,
        }


@dataclass
class CutReport:
    source: str
    duration: float  # da gravação original
    intensity: str
    min_pause: float
    breath: float
    cuts: list[CutRecord] = field(default_factory=list)

    @property
    def applied(self) -> list[CutRecord]:
        return [cut for cut in self.cuts if not cut.undone]

    @property
    def removed_seconds(self) -> float:
        return sum(cut.duration for cut in self.applied)

    @property
    def duration_after(self) -> float:
        return self.duration - self.removed_seconds

    def counts(self) -> dict[str, int]:
        found: dict[str, int] = {}
        for cut in self.applied:
            found[cut.reason] = found.get(cut.reason, 0) + 1
        return found

    def find(self, cut_id: int) -> CutRecord:
        for cut in self.cuts:
            if cut.id == cut_id:
                return cut
        known = ", ".join(str(cut.id) for cut in self.cuts) or "nenhum"
        raise ValueError(f"não há o corte {cut_id} (cortes: {known})")

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "intensity": self.intensity,
            "min_pause_s": self.min_pause,
            "breath_s": self.breath,
            "duration_before_s": round(self.duration, 2),
            "duration_after_s": round(self.duration_after, 2),
            "removed_s": round(self.removed_seconds, 2),
            "removed_percent": round(100 * self.removed_seconds / self.duration, 1) if self.duration else 0.0,
            "counts": self.counts(),
            "cuts": [cut.to_dict() for cut in self.cuts],
        }

    def to_file_dict(self) -> dict:
        return {
            "version": REPORT_VERSION,
            "source": self.source,
            "duration": self.duration,
            "intensity": self.intensity,
            "min_pause": self.min_pause,
            "breath": self.breath,
            "cuts": [
                {
                    "id": c.id,
                    "start": c.start,
                    "end": c.end,
                    "reason": c.reason,
                    "text": c.text,
                    "undone": c.undone,
                }
                for c in self.cuts
            ],
        }

    @classmethod
    def from_file_dict(cls, data: dict) -> CutReport:
        return cls(
            source=str(data["source"]),
            duration=float(data["duration"]),
            intensity=str(data["intensity"]),
            min_pause=float(data["min_pause"]),
            breath=float(data["breath"]),
            cuts=[
                CutRecord(
                    int(c["id"]),
                    float(c["start"]),
                    float(c["end"]),
                    str(c["reason"]),
                    str(c.get("text", "")),
                    bool(c.get("undone", False)),
                )
                for c in data.get("cuts", [])
            ],
        )


def load_cut_report(folder: Path) -> CutReport | None:
    """A lista de cortes salva ao lado do projeto; None se o projeto não nasceu de um `autocut`."""
    path = folder / REPORT_FILE
    if not path.exists():
        return None
    try:
        return CutReport.from_file_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        raise ValueError(f"{path.name} ilegível: {exc}") from exc


def save_cut_report(folder: Path, report: CutReport) -> Path:
    path = folder / REPORT_FILE
    path.write_text(json.dumps(report.to_file_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    return path


# ---------- peças puras ----------


def clips_from_ranges(source: Path, keep: list[tuple[float, float]]) -> list[ClipSegment]:
    """Um clipe da gravação por trecho que fica. O fim é sempre explícito, o do último também: o áudio medido
    pode ser mais curto que o vídeo, e o corte não deve levar a sobra de imagem sem som."""
    return [
        ClipSegment(src=str(source), start=start, end=end, audio_fade=CUT_FADE_SECONDS) for start, end in keep
    ]


def with_refined_words(cues: list[Cue], words: list[Word]) -> list[Cue]:
    """As cues originais com as palavras de `words` (os mesmos tempos ajustados pelo plano, na mesma ordem)."""
    refined: list[Cue] = []
    cursor = 0
    for cue in cues:
        count = len(cue.words or flatten_words([cue]))
        chunk = words[cursor : cursor + count]
        cursor += count
        if chunk:
            refined.append(Cue(chunk[0].start, chunk[-1].end, cue.text, chunk))
    return refined


def cut_records(plan: CutPlan) -> list[CutRecord]:
    return [CutRecord(i, c.start, c.end, c.reason, c.text) for i, c in enumerate(plan.cuts, start=1)]


def kept_ranges(project: Project, source: str, duration: float) -> list[tuple[float, float]]:
    """Os trechos da gravação que o projeto usa agora, na ordem da linha do tempo."""
    return [
        (clip.start, duration if clip.end is None else clip.end)
        for clip in project.timeline
        if isinstance(clip, ClipSegment) and clip.origin == source
    ]


def write_cut_captions(
    folder: Path, cues: list[Cue], ranges: list[tuple[float, float]], language: str
) -> Path:
    """Legendas na linha do tempo cortada: as palavras já transcritas, sem as cortadas, nos tempos novos."""
    path = folder / CAPTIONS_FILE
    path.write_text(to_json(remap_to_ranges(cues, ranges), language), encoding="utf-8")
    return path


# ---------- pedido, resultado e serviço ----------


@dataclass(frozen=True)
class AutoCutRequest:
    source: Path
    name: str
    options: CutOptions = CutOptions()
    preset: str = "instagram/reels"
    brand: str | None = None
    captions: bool = True
    language: str = "pt"
    model: str = "small"
    device: Literal["cpu", "cuda"] = "cpu"
    overwrite: bool = False


@dataclass
class AutoCutResult:
    project: Project
    spec_path: Path
    report: CutReport
    warnings: list[str] = field(default_factory=list)


def _transcript_key(source: Path, model: str, language: str) -> str:
    stat = source.stat()
    raw = f"{source}|{stat.st_mtime_ns}|{stat.st_size}|{model}|{language}|{DISFLUENCY_PROMPT}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


class AutoCutService:
    """Orquestra a transcrição, a medição de energia, o plano e a montagem do projeto."""

    def __init__(
        self,
        runner: FFmpegRunner | None = None,
        prober: Prober = probe,
        transcriber: Transcriber | None = None,
        log: Callable[[str], None] = lambda message: None,
        cache_dir: Path | None = None,
    ) -> None:
        self.runner = runner or SubprocessRunner(quiet=True)
        self.prober = prober
        self.transcriber = transcriber
        self.log = log
        self.cache_dir = cache_dir

    def cut(self, request: AutoCutRequest, report: Reporter | None = None) -> AutoCutResult:
        progress = report or (lambda label, fraction: None)
        self.validate(request)
        progress("Lendo a gravação", 0.02)
        source = request.source.resolve()
        info = self.prober(source)
        if not info.has_audio:
            raise ValueError(f"{source.name} não tem áudio para cortar")

        progress("Extraindo o áudio", 0.05)
        cache = (self.cache_dir or config.CACHE_DIR / "autocut") / _transcript_key(
            source, request.model, request.language
        )
        wav = cache.with_suffix(".wav")
        if not wav.exists():
            extract_audio_wav(self.runner, source, wav)
        cues = self._cues(request, wav, cache.with_suffix(".json"), progress)

        progress("Planejando os cortes", 0.85)
        samples, rate = read_wav(wav)
        words = [word for cue in cues for word in (cue.words or flatten_words([cue]))]
        plan = plan_cuts(words, samples, rate, request.options)
        duration = len(samples) / rate
        warnings = self._warnings(words, plan)
        refined = with_refined_words(cues, plan.words)

        progress("Montando o projeto", 0.95)
        project = self._project(request, source, plan, duration)
        spec_path = save_project(project)
        folder = project.base_dir or spec_path.parent
        cut_report = CutReport(
            str(source),
            duration,
            request.options.intensity,
            request.options.min_pause,
            request.options.breath,
            cut_records(plan),
        )
        save_cut_report(folder, cut_report)
        (folder / TRANSCRIPT_FILE).write_text(to_json(refined, request.language), encoding="utf-8")
        if request.captions:
            write_cut_captions(folder, refined, plan.keep, request.language)
        progress("Pronto", 1.0)
        return AutoCutResult(project, spec_path, cut_report, warnings)

    def validate(self, request: AutoCutRequest) -> None:
        """Falha antes da transcrição (minutos) se o pedido não pode dar certo."""
        if not request.source.exists():
            raise FileNotFoundError(f"Gravação não encontrada: {request.source}")
        get_preset(request.preset)
        # o nome vira pasta e arquivo: a spec valida (sem barras, sem caracteres proibidos)
        Project(name=request.name, timeline=[ClipSegment(src=str(request.source))])
        if project_path(request.name).exists() and not request.overwrite:
            raise ValueError(
                f"já existe um projeto chamado {request.name!r}: escolha outro nome ou use overwrite"
            )

    def _cues(self, request: AutoCutRequest, wav: Path, store: Path, progress: Reporter) -> list[Cue]:
        """Transcrição com cache por arquivo: refazer o corte com outra intensidade não transcreve de novo."""
        if store.exists():
            try:
                self.log("transcrição reaproveitada do cache")
                return from_json(store.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, KeyError, ValueError):
                pass
        progress("Transcrevendo (leva alguns minutos na CPU)", 0.1)
        transcriber = self.transcriber or WhisperTranscriber(model=request.model, device=request.device)
        cues = transcriber.transcribe(wav, request.language, DISFLUENCY_PROMPT).cues
        store.write_text(to_json(cues, request.language), encoding="utf-8")
        return cues

    @staticmethod
    def _warnings(words: list[Word], plan: CutPlan) -> list[str]:
        if not words:
            return ["O Whisper não encontrou fala na gravação: nada foi cortado."]
        if not plan.cuts:
            return [
                "Nada passou do limite para cortar: tente uma intensidade maior ou um limite de pausa menor."
            ]
        return []

    @staticmethod
    def _project(request: AutoCutRequest, source: Path, plan: CutPlan, duration: float) -> Project:
        return Project(
            name=request.name,
            output=Output(preset=request.preset),
            brand=request.brand,
            timeline=clips_from_ranges(source, plan.keep),
            captions=Captions(source=CAPTIONS_FILE, language=request.language, model=request.model)
            if request.captions
            else None,
        )


def default_autocut_service(log: Callable[[str], None] = lambda message: None) -> AutoCutService:
    """O serviço com as peças de verdade (ffmpeg, ffprobe, Whisper); o ponto que os testes da CLI trocam."""
    return AutoCutService(log=log)


# ---------- desfazer ----------


def undo_cut(name_or_path: str | Path, cut_id: int) -> CutReport:
    """Devolve ao projeto o trecho removido pelo corte `cut_id` (juntando os clipes vizinhos) e refaz as
    legendas; levanta ValueError se o corte não existe, já foi desfeito ou a linha do tempo mudou."""
    project = load_project(name_or_path)
    folder = project.base_dir or project_path(name_or_path).parent
    report = load_cut_report(folder)
    if report is None:
        raise ValueError(f"{project.name} não tem lista de cortes (não nasceu de um autocut)")
    record = report.find(cut_id)
    if record.undone:
        raise ValueError(f"o corte {cut_id} já foi desfeito")
    restored = restore_gap(project, record.start, record.end, origin=report.source)
    record.undone = True
    save_project(restored, folder)
    save_cut_report(folder, report)
    _rebuild_captions(restored, folder, report)
    return report


def _rebuild_captions(project: Project, folder: Path, report: CutReport) -> None:
    """As legendas seguem a linha do tempo: com o trecho de volta, as palavras dele voltam também."""
    captions = project.captions
    transcript = folder / TRANSCRIPT_FILE
    if captions is None or captions.source != CAPTIONS_FILE or not transcript.exists():
        return
    cues = from_json(transcript.read_text(encoding="utf-8"))
    write_cut_captions(folder, cues, kept_ranges(project, report.source, report.duration), captions.language)
