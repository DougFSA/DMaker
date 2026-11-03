"""Analisar o áudio de um projeto: a porta de entrada que a CLI, o MCP e a interface compartilham.

Acha o som que o pedido quer (um item do projeto como ele soa, a saída final renderizada ou um arquivo solto),
decodifica o trecho pelo `FFmpegRunner` injetado, entrega as amostras ao analisador registrado (`dmaker.analysis`) e, se
o pedido manda marcar, grava o resultado num grupo de marcadores com nome próprio pela operação `marker_group_set` do
`apply_edit_report`: os marcadores da pessoa nunca são tocados. A conta de cada análise é pura e mora em `analysis/`.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..analysis import AnalysisResult, MarkerProposal, Signal, analyzer_class, parse_analyzer
from ..analysis.analyzers.spectrum import SpectrumResult
from ..analysis.plot import png_bytes, spectrum_image
from ..domain.audio_effects import active_effects, chain_duration
from ..domain.markers import MarkerError, is_marker_ref, marker_instant
from ..domain.spec import Project
from ..media.decode import decode_to_wav
from ..media.ffmpeg import FFmpegRunner, SubprocessRunner
from ..media.probe import probe
from ..media.wavio import read_wav_float
from .analysis_items import ItemAudio, ItemClock, TargetError, resolve_item
from .audio_effects import AudioItem, EffectProcessor
from .context import Prober
from .edits import apply_edit_report
from .final_output import latest_final_output
from .layout import ProjectLayout, project_layout, to_presentation
from .missing import MissingMedia
from .projects import load_project, project_path, save_project
from .sync import OffsetFinder

# O teto do que uma análise carrega na memória: 60 milhões de amostras em ponto flutuante são 240 MB, uns 10 minutos
# de estéreo a 48 kHz. Um trecho maior que isso pede um intervalo (`start` e `end`) em vez de travar a máquina.
MAX_ANALYSIS_SAMPLES = 60_000_000
OUTPUT_TARGET = "output"


@dataclass(frozen=True)
class AnalysisRequest:
    """O que analisar e como. `target` é um item (`timeline.2`, `audio.music`...) ou `output` (a saída final já
    renderizada); `file` é um arquivo solto. `start` e `end` recortam o item (segundos do áudio dele, ou
    `marker:<texto>`). `mark` grava os marcadores no `group` (o analisador tem o padrão dele)."""

    analyzer: str
    params: Mapping[str, Any] = field(default_factory=dict)
    target: str | None = None
    file: str | None = None
    start: float | str | None = None
    end: float | str | None = None
    mark: bool | None = None
    group: str | None = None


@dataclass
class LoadedSignal:
    """O som que vai para o analisador e de onde ele veio: `offset` é o instante, no áudio do item, da primeira
    amostra (o recorte `start`), e `clock` leva o tempo do item para o do projeto (None: não há lugar na linha do tempo)."""

    signal: Signal
    label: str
    offset: float
    clock: ItemClock | None
    notes: tuple[str, ...] = ()


@dataclass
class AnalysisOutcome:
    result: AnalysisResult
    label: str
    interval: tuple[float, float]
    notes: tuple[str, ...] = ()
    marker_group: str | None = None
    markers_written: int = 0
    edit_warnings: list[str] = field(default_factory=list)
    exported: str | None = None
    project: Project | None = None
    clock: ItemClock | None = None  # o relógio do item analisado: leva o tempo da análise para o do projeto

    def to_dict(self, detail: str = "compact", limit: int | None = None) -> dict[str, Any]:
        """O resultado como o MCP o devolve: o dado da análise, de onde veio e o que foi marcado ou exportado.
        `detail="full"` não reduz as listas longas (a curva do espectro, as amostras); `limit` as reduz a tantos itens."""
        data: dict[str, Any] = {
            "source": self.label,
            "interval_s": [round(self.interval[0], 6), round(self.interval[1], 6)],
            **self.result.to_dict(detail, limit),
        }
        if self.notes:
            data["notes"] = list(self.notes)
        if self.marker_group is not None:
            data["markers"] = {
                "group": self.marker_group,
                "written": self.markers_written,
                "warnings": self.edit_warnings,
            }
        if self.exported:
            data["exported"] = self.exported
        return data


class AudioAnalysisService:
    """Carrega o som do pedido e roda o analisador. As dependências do mundo (ffmpeg, probe, sincronizador de fontes)
    entram por injeção, como no resto do pipeline."""

    def __init__(
        self,
        runner: FFmpegRunner | None = None,
        prober: Prober = probe,
        offset_finder: OffsetFinder | None = None,
    ) -> None:
        self.runner: FFmpegRunner = runner or SubprocessRunner(quiet=True)
        self.prober = prober
        self.offset_finder = offset_finder

    # ---------- o som do pedido ----------

    def layout(self, project: Project) -> ProjectLayout:
        return project_layout(project, self.prober, self.offset_finder, MissingMedia.scan(project))

    def load(
        self, project: Project, request: AnalysisRequest, layout: ProjectLayout | None = None
    ) -> LoadedSignal:
        """Decodifica o trecho pedido do alvo. Alvo que não existe ou não tem som é `TargetError`. Quem analisa vários
        itens do mesmo projeto passa o `layout` uma vez, para as fontes não serem lidas de novo a cada item."""
        if request.file:
            return self.load_file(Path(request.file), request)
        target = (request.target or OUTPUT_TARGET).strip()
        if target == OUTPUT_TARGET:
            return self._load_output(project, request)
        layout = layout or self.layout(project)
        item = resolve_item(project, layout, target, prober=self.prober, runner=self.runner)
        return self._load_item(project, item, request)

    def load_file(self, path: Path, request: AnalysisRequest) -> LoadedSignal:
        if not path.exists():
            raise TargetError(f"arquivo não encontrado: {path}")
        info = self.prober(path)
        if not info.has_audio:
            raise TargetError(f"{path.name} não tem áudio para analisar")
        start, end = self._interval(request, None, info.duration)
        signal = self._decode(path, start, end - start, 0, info)
        return LoadedSignal(signal, path.name, start, None)

    def _load_output(self, project: Project, request: AnalysisRequest) -> LoadedSignal:
        path = latest_final_output(project)
        if path is None:
            raise TargetError(
                f"o projeto {project.name!r} não tem saída final renderizada: renderize antes, ou informe um arquivo"
            )
        info = self.prober(path)
        if not info.has_audio:
            raise TargetError(f"{path.name} não tem áudio para analisar")
        start, end = self._interval(request, ItemClock(), info.duration, project)
        signal = self._decode(path, start, end - start, 0, info)
        return LoadedSignal(signal, f"saída final ({path.name})", start, ItemClock())

    def _load_item(self, project: Project, item: ItemAudio, request: AnalysisRequest) -> LoadedSignal:
        playable = item.duration if item.whole_file else chain_duration(item.effects, item.duration)
        start, end = self._interval(request, item.clock, playable, project)
        length = end - start
        if active_effects(item.effects):
            signal = self._processed(item, start, length)
        else:
            info = self.prober(item.path)
            signal = self._decode(item.path, item.offset + start, length, item.stream, info)
        if item.gain != 1.0:
            signal = Signal((signal.samples * item.gain).astype(signal.samples.dtype), signal.sample_rate)
        return LoadedSignal(signal, item.label, start, item.clock, item.notes)

    def _processed(self, item: ItemAudio, start: float, length: float) -> Signal:
        """O trecho do item depois da cadeia de efeitos: o arquivo processado do `EffectProcessor` (o do render)."""
        processor = EffectProcessor(self.runner)
        if item.whole_file:
            done = processor.process(AudioItem(item.path, item.file_duration, item.effects, 0.0, item.stream))
            base = item.offset
        else:
            done = processor.process(
                AudioItem(item.path, item.duration, item.effects, item.offset, item.stream)
            )
            base = 0.0
        assert done is not None  # há efeito ligado: o processador sempre devolve o arquivo
        probed = self.prober(done.path) if done.path.exists() else None
        rate, channels = (probed.sample_rate, probed.channels) if probed else (48000, 2)
        self._check_size(length, rate or 48000, channels or 2)
        samples, sample_rate = read_wav_float(done.path, base + start, length)
        return Signal(samples, sample_rate)

    def _decode(self, path: Path, start: float, length: float, stream: int, info: Any) -> Signal:
        self._check_size(length, info.sample_rate or 48000, info.channels or 2)
        with tempfile.TemporaryDirectory(prefix="dmaker-analise-") as folder:
            wav = decode_to_wav(
                self.runner, path, Path(folder) / "audio.wav", start=start, duration=length, stream=stream
            )
            samples, rate = read_wav_float(wav)
        return Signal(samples, rate)

    @staticmethod
    def _check_size(length: float, rate: int, channels: int) -> None:
        if length * rate * channels > MAX_ANALYSIS_SAMPLES:
            minutes = MAX_ANALYSIS_SAMPLES / (rate * channels) / 60
            raise TargetError(
                f"o trecho tem {length / 60:.1f} min, mais do que cabe numa análise (cerca de {minutes:.0f} min): "
                "escolha um intervalo menor com start e end"
            )

    def _interval(
        self,
        request: AnalysisRequest,
        clock: ItemClock | None,
        playable: float,
        project: Project | None = None,
    ) -> tuple[float, float]:
        """O recorte pedido em segundos do áudio do item, dentro de [0, playable]. `marker:<texto>` é um instante da
        linha do tempo e vira o instante do item pelo relógio dele."""
        start = self._instant(request.start, clock, project, "start") if request.start is not None else 0.0
        end = self._instant(request.end, clock, project, "end") if request.end is not None else playable
        end = min(end, playable)
        if start < 0:
            raise TargetError(f"start ({start:g} s) não pode ser negativo")
        if start >= playable:
            raise TargetError(f"start ({start:g} s) está depois do fim do áudio ({playable:g} s)")
        if end <= start:
            raise TargetError(f"end ({end:g} s) precisa ser maior que start ({start:g} s)")
        return start, end

    @staticmethod
    def _instant(value: float | str, clock: ItemClock | None, project: Project | None, name: str) -> float:
        if isinstance(value, str) and is_marker_ref(value):
            if clock is None or project is None:
                raise TargetError(
                    f"{name}: marker:<texto> só vale para um item preso à linha do tempo do projeto"
                )
            try:
                return clock.to_item(marker_instant(project.markers, value))
            except MarkerError as exc:
                raise TargetError(str(exc)) from exc
        try:
            return float(value)
        except (TypeError, ValueError):
            raise TargetError(
                f"{name} precisa ser um número de segundos ou marker:<texto>, não {value!r}"
            ) from None

    # ---------- a análise ----------

    @staticmethod
    def check(request: AnalysisRequest) -> None:
        """Recusa o pedido de um analisador que não existe ou de um parâmetro fora da faixa ANTES de decodificar o
        som (o `marker:<texto>` de um parâmetro só vira tempo depois, então vale um tempo qualquer por ora)."""
        parse_analyzer(
            request.analyzer,
            {
                key: 0.0 if isinstance(value, str) and is_marker_ref(value) else value
                for key, value in request.params.items()
            },
        )

    def analyze(self, project: Project, request: AnalysisRequest) -> AnalysisOutcome:
        """Carrega o som e roda o analisador, sem gravar nada."""
        self.check(request)
        return self.analyze_loaded(project, request, self.load(project, request))

    def analyze_loaded(
        self, project: Project, request: AnalysisRequest, loaded: LoadedSignal
    ) -> AnalysisOutcome:
        """Roda o analisador sobre o som já carregado. Os tempos dos parâmetros contam desde o começo do trecho
        analisado, e um `marker:<texto>` num parâmetro vira esse tempo."""
        params = {
            key: self._param_instant(project, value, loaded) if isinstance(value, str) else value
            for key, value in request.params.items()
        }
        result = parse_analyzer(request.analyzer, params).analyze(loaded.signal)
        return AnalysisOutcome(
            result=result,
            label=loaded.label,
            interval=(loaded.offset, loaded.offset + loaded.signal.duration),
            notes=loaded.notes,
            clock=loaded.clock,
        )

    def _param_instant(self, project: Project, value: str, loaded: LoadedSignal) -> Any:
        if not is_marker_ref(value):
            return value
        return self._instant(value, loaded.clock, project, "parâmetro") - loaded.offset


# ---------- marcar ----------


def marker_dicts(
    proposals: list[MarkerProposal], offset: float, clock: ItemClock | None, total: float, color: str | None
) -> list[dict[str, Any]]:
    """Os marcadores propostos (segundos desde o começo do trecho analisado) como dados de marcador do projeto, no
    tempo da linha do tempo final. O que cai fora do vídeo é descartado, e a região que passa do fim é cortada nele."""
    dicts: list[dict[str, Any]] = []
    for proposal in proposals:
        first = clock.to_project(offset + proposal.start) if clock else offset + proposal.start
        if proposal.end is None:
            if 0 <= first < total + 1e-9:
                dicts.append(_with_color({"at": round(first, 6), "text": proposal.text}, color))
            continue
        last = clock.to_project(offset + proposal.end) if clock else offset + proposal.end
        first, last = max(first, 0.0), min(last, total)
        if last - first > 1e-6:
            dicts.append(
                _with_color({"start": round(first, 6), "end": round(last, 6), "text": proposal.text}, color)
            )
    return dicts


def _with_color(data: dict[str, Any], color: str | None) -> dict[str, Any]:
    return {**data, "color": color} if color else data


def apply_marks(
    project: Project,
    outcome: AnalysisOutcome,
    request: AnalysisRequest,
    loaded_clock: ItemClock | None,
    total: float,
    prober: Prober,
) -> Project:
    """Grava os marcadores da análise no grupo certo (a operação `marker_group_set`), um passo só do desfazer."""
    cls = analyzer_class(request.analyzer)
    group = (request.group or cls.marker_group).strip()
    if not group:
        raise TargetError(
            f"informe o nome do grupo (group) para o {cls.label} marcar: o grupo vazio é a trilha da pessoa"
        )
    if loaded_clock is None:
        raise TargetError(
            "para marcar, analise um item preso à linha do tempo (clipe, voz gravada, narração, música, PiP) "
            "ou a saída final: uma faixa externa ou um arquivo solto não têm lugar certo nela"
        )
    markers = marker_dicts(
        outcome.result.markers(), outcome.interval[0], loaded_clock, total, cls.marker_color
    )
    report = apply_edit_report(
        project, {"type": "marker_group_set", "group": group, "markers": markers}, prober
    )
    outcome.marker_group = group
    outcome.markers_written = len(markers)
    outcome.edit_warnings = report.warnings
    return report.project


# ---------- exportar ----------


def export_result(result: AnalysisResult, path: Path) -> Path:
    """Grava o resultado no arquivo, no formato que a extensão diz: `.csv` (vírgula) e `.txt` (tabulação) para a
    tabela da análise, `.png` para o gráfico do espectro e `.json` para o resultado inteiro."""
    suffix = path.suffix.lower()
    path.parent.mkdir(parents=True, exist_ok=True)
    if suffix in (".csv", ".txt", ".tsv"):
        table = result.table("," if suffix == ".csv" else "\t")
        if table is None:
            raise ValueError("este analisador não exporta uma tabela: use um arquivo .json")
        path.write_bytes(table.encode("utf-8"))
    elif suffix == ".png":
        if not isinstance(result, SpectrumResult):
            raise ValueError("só o Espectro de Frequência exporta o gráfico em PNG")
        image = spectrum_image(
            result.frequencies,
            result.levels_db,
            axis=result.axis,
            title=f"{result.algorithm}, janela {result.window}, FFT {result.size}",
        )
        path.write_bytes(png_bytes(image))
    elif suffix == ".json":
        text = json.dumps(result.to_dict("full"), ensure_ascii=False, indent=2)
        path.write_bytes(text.encode("utf-8"))
    else:
        raise ValueError(
            f"formato de arquivo desconhecido: {suffix or path.name!r} (use .csv, .txt, .png ou .json)"
        )
    return path


def analyze_project(
    name_or_path: str | Path,
    request: AnalysisRequest,
    *,
    out: Path | str | None = None,
    service: AudioAnalysisService | None = None,
    save: Callable[[Project], Any] | None = None,
) -> AnalysisOutcome:
    """Carrega o projeto, analisa e, se o pedido manda, marca (e salva o projeto) e exporta o arquivo `out`."""
    project = load_project(name_or_path)
    service = service or AudioAnalysisService()
    service.check(request)  # pedido inválido falha antes de decodificar
    cls = analyzer_class(request.analyzer)
    wants_mark = cls.marks_by_default if request.mark is None else request.mark
    loaded = service.load(project, request)
    outcome = service.analyze_loaded(project, request, loaded)
    if wants_mark:
        total = _project_total(project, service)
        outcome.project = apply_marks(project, outcome, request, loaded.clock, total, service.prober)
        # a spec volta para o lugar de onde veio (o nome do projeto, ou o caminho do `spec.json` dado)
        (save or (lambda changed: save_project(changed, project_path(name_or_path).parent)))(outcome.project)
    if out is not None:
        outcome.exported = str(export_result(outcome.result, Path(out)))
    return outcome


def _project_total(project: Project, service: AudioAnalysisService) -> float:
    return to_presentation(project, service.layout(project)).total


__all__ = [
    "AnalysisOutcome",
    "AnalysisRequest",
    "AudioAnalysisService",
    "TargetError",
    "analyze_project",
    "apply_marks",
    "export_result",
    "marker_dicts",
]
