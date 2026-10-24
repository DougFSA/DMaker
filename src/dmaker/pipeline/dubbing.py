"""Dublar um vídeo ou áudio para outro idioma com a voz clonada de quem fala, mantendo música e ruído de fundo.

Dois passos, com um projeto editável entre eles:
  preparar: separa voz e fundo -> transcreve a voz com tempo por palavra -> parte em frases -> separa quem fala
            (diarização, no modo per_speaker) -> traduz -> grava o `.dub.json` (o usuário revisa e corrige as
            traduções e o falante de cada fala);
  gerar:    para cada fala clona a voz de quem fala (uma por pessoa, por frase ou uma só, conforme o modo),
            sintetiza a tradução na duração que cabe (com cache por fala: editar uma tradução, ou trocar o
            falante dela, refaz só aquela) -> monta fundo + falas dubladas (+ voz original atenuada) no vídeo
            original e grava a legenda no idioma alvo. Conforme o `fit_mode` do projeto, a fala que não
            cabe é comprimida na voz (padrão) ou estica o vídeo na janela dela, e o resto da linha do tempo
            (falas seguintes, fundo, legenda, trilhas separadas) acompanha.
Cada dependência pesada (Whisper, Demucs, Ollama, OmniVoice, ffmpeg) entra por parâmetro.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path

from .. import config
from ..domain.dub import (
    PROJECT_SUFFIX,
    DubProject,
    DubSegment,
    DubSpeaker,
    FitMode,
    SpeakerMode,
    save_dub_project,
)
from ..filtergraph.dub import DubClip, dub_mix_command
from ..filtergraph.dub_stems import dub_stems_command
from ..filtergraph.speech_edit import corrected_suffix
from ..media.diarization import SpeakerDiarizer, SpeakerTurn, speaking_seconds
from ..media.ffmpeg import FFmpegRunner
from ..media.probe import MediaInfo, probe
from ..media.separation import Stems
from ..media.wavio import read_wav
from ..text.captions import Cue, Word, to_srt
from ..text.transcribe import Transcriber, extract_audio_wav
from ..text.translate import Line, OllamaTranslator, Translator
from ..voice.dub_plan import (
    Slot,
    natural_seconds,
    plan_fit,
    plan_video_fit,
    plan_voice_fit,
    segment_words,
    slot_plan,
    subtitle_cues,
)
from ..voice.dub_retime import IDENTITY, RetimePlan, StretchWindow, plan_retime, retimed_span
from ..voice.levels import active_rms, gain_to_match_db
from ..voice.lexicon_store import LexiconStore
from ..voice.library import VoiceLibrary, VoiceProfile
from ..voice.pronunciation import spoken_text, written_text
from ..voice.reference import ReferenceSpan, choose_speaker_reference
from ..voice.script import normalize_for_speech
from ..voice.speakers import assign_speakers, label_words, speaker_names
from ..voice.synth import SpeechSynthesizer, VoiceRequest
from .dub_stems import DubStems, StemsOptions, stem_outputs, zip_stems
from .isolation import IsolationService
from .narration import NarrationService
from .speech_fix import ProgressReport, SpeechFixService, VocalsWindow

OUTPUT_SUBDIR = "dublagem"
DEFAULT_SOURCE_LANGUAGE = "pt"
DIARIZATION_OFF = ("off", "0", "false", "no", "nao")
DIARIZATION_RECIPE = "d1"  # muda quando o uso dos turnos muda (invalida o cache de turnos)


@dataclass(frozen=True)
class SegmentReport:
    """O que aconteceu com uma fala na geração: o espaço, a duração, o encaixe e se veio do cache."""

    id: str
    start: float
    end: float
    text: str
    natural_seconds: float  # quanto a tradução leva no ritmo do falante original
    requested_seconds: float  # duração pedida ao modelo
    speech_seconds: float  # duração da fala sintetizada
    played_seconds: float  # quanto dela toca no vídeo (depois do atempo e do corte)
    tempo: float
    status: str  # fits | advances | squeezed | stretched | overflow | empty
    message: str
    cached: bool
    voice: str
    stretch: float = 1.0  # fator do vídeo na janela da fala; 1.0 = imagem intacta
    retimed_start: float | None = (
        None  # onde a fala começa no arquivo final (muda se algo antes foi esticado)
    )
    speaker: str = ""  # quem fala nesta fala (modo per_speaker); vazio nos outros modos

    @property
    def warns(self) -> bool:
        return self.status == "overflow"

    @property
    def added_seconds(self) -> float:
        """Quanto o vídeo cresceu nesta fala por causa do esticamento."""
        return (self.end - self.start) * (self.stretch - 1.0)


@dataclass(frozen=True)
class DubResult:
    path: Path
    srt_path: Path
    report: list[SegmentReport]
    timings: dict[str, float] = field(default_factory=dict)  # segundos de cada etapa
    fit_mode: FitMode = "voz"  # o modo que valeu de fato (áudio sem imagem não estica)
    output_seconds: float = 0.0  # duração do arquivo final; passa da original quando o vídeo foi esticado
    stems: DubStems | None = None  # as trilhas separadas, quando o render as exportou junto

    @property
    def warnings(self) -> list[str]:
        return [f"Fala {r.id} ({r.start:.1f} s): {r.message}" for r in self.report if r.warns]

    @property
    def stretched(self) -> list[SegmentReport]:
        """As falas cuja imagem foi esticada, na ordem do arquivo."""
        return [r for r in self.report if r.stretch > 1.0]

    @property
    def regenerated(self) -> int:
        """Quantas falas foram sintetizadas agora (o resto veio do cache)."""
        return sum(1 for r in self.report if not r.cached and r.status != "empty")


def default_project_path(src: Path, target: str) -> Path:
    return config.OUTPUT_DIR / OUTPUT_SUBDIR / f"{src.stem}.{target}{PROJECT_SUFFIX}"


def default_output_path(src: Path, target: str, suffix: str) -> Path:
    return config.OUTPUT_DIR / OUTPUT_SUBDIR / f"{src.stem}.{target}{suffix}"


def default_stems_dir(src: Path, target: str) -> Path:
    """Pasta das trilhas separadas, ao lado da dublagem; lê a pasta de saída do config na hora."""
    return config.OUTPUT_DIR / OUTPUT_SUBDIR / f"{src.stem}.{target}.trilhas"


@dataclass(frozen=True)
class _Synthesis:
    """O que a geração produz antes de montar: os stems, as falas prontas e o relatório de cada uma."""

    stems: Stems
    clips: list[DubClip]  # já na linha do tempo final: reposicionadas se o vídeo foi esticado
    reports: list[SegmentReport]
    fit_mode: FitMode = "voz"  # o modo que valeu de fato (áudio sem imagem não estica)
    retime: RetimePlan = IDENTITY


def glossary_terms(lexicon_terms: Sequence[str], extra: Sequence[str]) -> list[str]:
    """Termos que a tradução mantém: os do dicionário de pronúncia (marcas) e os do usuário, sem repetir."""
    seen: dict[str, str] = {}
    for term in [*lexicon_terms, *extra]:
        cleaned = term.strip()
        if cleaned:
            seen.setdefault(cleaned.casefold(), cleaned)
    return list(seen.values())


def project_summary(project: DubProject, path: Path) -> dict:
    """O projeto como dicionário para as respostas do MCP e da interface (as falas com tempo, original e tradução)."""
    return {
        "project": str(path),
        "source": project.source,
        "source_language": project.source_language,
        "target_language": project.target_language,
        "speaker_mode": project.speaker_mode,
        "speakers": project.speaker_names,
        "voice": project.voice,
        "keep_original_db": project.keep_original_db,
        "fit_mode": project.fit_mode,
        "glossary": project.glossary,
        "translator_model": project.translator_model,
        "segments": [
            {
                "id": s.id,
                "start": round(s.start, 2),
                "end": round(s.end, 2),
                "original": s.source_text,
                "text": s.text,
                "locked": s.locked,
                "speaker": s.speaker,
            }
            for s in project.segments
        ],
    }


def report_dict(report: SegmentReport) -> dict:
    return {
        "id": report.id,
        "start": round(report.start, 2),
        "end": round(report.end, 2),
        "text": report.text,
        "natural_seconds": round(report.natural_seconds, 2),
        "speech_seconds": round(report.speech_seconds, 2),
        "played_seconds": round(report.played_seconds, 2),
        "tempo": round(report.tempo, 3),
        "video_stretch": round(report.stretch, 3),
        "retimed_start": None if report.retimed_start is None else round(report.retimed_start, 3),
        "status": report.status,
        "message": report.message,
        "cached": report.cached,
        "speaker": report.speaker,
        "voice": report.voice,
    }


def result_dict(result: DubResult) -> dict:
    """O resultado da geração como dicionário (MCP e interface), sem a lista de falas: cada adaptador a nomeia."""
    return {
        "fit_mode": result.fit_mode,
        "output_seconds": round(result.output_seconds, 3),
        "stretched": [
            {
                "id": r.id,
                "start": round(r.start, 2),
                "factor": round(r.stretch, 3),
                "added_seconds": round(r.added_seconds, 2),
            }
            for r in result.stretched
        ],
        "warnings": result.warnings,
        "regenerated": result.regenerated,
        "timings": {name: round(seconds, 1) for name, seconds in result.timings.items()},
    }


class DubbingService:
    def __init__(
        self,
        translator: Translator,
        transcriber: Transcriber,
        isolation: IsolationService,
        narrator: NarrationService,
        library: VoiceLibrary,
        runner: FFmpegRunner,
        prober: Callable[[Path], MediaInfo] = probe,
        cache_dir: Path | None = None,
        log: Callable[[str], None] | None = None,
        diarizer: SpeakerDiarizer | None = None,
    ) -> None:
        self.translator = translator
        self.diarizer = diarizer
        self.isolation = isolation
        self.narrator = narrator
        self.library = library
        self.runner = runner
        self.prober = prober
        self.cache_dir = cache_dir or config.CACHE_DIR / "speech"
        self.log = log or (lambda _message: None)
        # transcrição com cache e clone temporário do falante já existem na correção de fala: mesmas peças, mesmo cache
        self.speech = SpeechFixService(
            transcriber,
            isolation,
            narrator,
            library,
            runner,
            prober=prober,
            cache_dir=self.cache_dir,
            log=self.log,
        )

    @contextmanager
    def _stage(self, timings: dict[str, float], name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            timings[name] = timings.get(name, 0.0) + time.perf_counter() - started
            self.log(f"{name}: {timings[name]:.1f} s")

    # -- preparar --

    def prepare(
        self,
        src: Path,
        target: str,
        source: str = DEFAULT_SOURCE_LANGUAGE,
        speaker_mode: SpeakerMode | None = None,
        voice: str | None = None,
        keep_original_db: float | None = None,
        glossary: Sequence[str] = (),
        brand: str | None = None,
        project_path: Path | None = None,
        on_progress: ProgressReport | None = None,
        fit_mode: FitMode = "voz",
        num_speakers: int | None = None,
    ) -> DubProject:
        """Transcreve, parte em frases e traduz `src`; grava o projeto editável e o devolve.

        Sem `speaker_mode`, vale `per_speaker` (uma voz por pessoa) quando há diarizador, e `per_segment` quando
        não há. `num_speakers` força a quantidade de pessoas na diarização.
        """
        report = on_progress or (lambda _label, _fraction: None)
        if not src.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {src}")
        if source.split("-")[0] == target.split("-")[0]:
            raise ValueError("O idioma de destino precisa ser diferente do idioma de origem.")
        mode = self._resolved_mode(speaker_mode, num_speakers)
        if voice:
            self.library.get(voice)  # falha já aqui, e não minutos depois, se a voz não existe
        info = self.prober(src)
        if not info.has_audio:
            raise ValueError(f"{src.name} não tem faixa de áudio para dublar.")
        timings: dict[str, float] = {}

        def separation(done: int, total: int) -> None:
            report("Separando a voz do fundo", 0.45 * done / max(total, 1))

        report("Separando a voz do fundo", 0.0)
        with self._stage(timings, "Separação de voz e fundo"):
            stems = self.isolation.isolate(src, on_progress=separation)
        report("Transcrevendo a fala", 0.45)
        with self._stage(timings, "Transcrição"):
            words = self.speech.transcribe_words(stems.vocals, language=source)
        phrases = segment_words(words)
        if not phrases:
            raise ValueError(f"Não encontrei fala em {src.name}.")
        segments = [
            DubSegment(id=f"s{number}", start=p.start, end=p.end, source_text=p.text, text="")
            for number, p in enumerate(phrases, 1)
        ]
        speakers: list[DubSpeaker] = []
        if mode == "per_speaker":
            report("Separando quem fala", 0.55)
            with self._stage(timings, "Diarização"):
                turns = self._turns(stems.vocals, info.duration, num_speakers, report)
            segments, speakers = self._attributed(segments, words, turns)
        project = DubProject(
            source=str(src.resolve()),
            source_language=source,
            target_language=target,
            segments=segments,
            keep_original_db=keep_original_db,
            speaker_mode=mode,
            speakers=speakers,
            voice=voice,
            translator_model=self.translator.model,
            glossary=list(glossary),
            brand=brand,
            fit_mode=fit_mode,
        )
        with self._stage(timings, "Tradução"):
            project = self._translated(project, 0.65, 0.98, report)
        saved = save_dub_project(project, project_path or default_project_path(src, target))
        report("Projeto de dublagem gravado", 1.0)
        self.log(f"Projeto gravado em {saved}")
        return project

    def _resolved_mode(self, requested: SpeakerMode | None, num_speakers: int | None) -> SpeakerMode:
        """O modo pedido ou o padrão (per_speaker se há diarizador); recusa já o que não vai funcionar."""
        mode: SpeakerMode = requested or ("per_speaker" if self.diarizer is not None else "per_segment")
        if num_speakers is not None and num_speakers < 1:
            raise ValueError("O número de falantes precisa ser 1 ou mais.")
        if num_speakers is not None and mode != "per_speaker":
            raise ValueError("O número de falantes só vale no modo per_speaker.")
        if mode == "per_speaker" and self.diarizer is None:
            raise ValueError(
                "A diarização não está disponível: instale o sherpa-onnx "
                "(.venv\\Scripts\\pip install -e .[voice]) ou escolha o modo per_segment ou single."
            )
        return mode

    def _turns_key(self, vocals: Path, num_speakers: int | None) -> str:
        assert self.diarizer is not None
        stat = vocals.stat()
        parts = [
            DIARIZATION_RECIPE,
            str(vocals.resolve()),
            stat.st_size,
            stat.st_mtime_ns,
            self.diarizer.model_id,
            num_speakers,
        ]
        return hashlib.sha256(json.dumps(parts).encode("utf-8")).hexdigest()[:20]

    def _turns(
        self, vocals: Path, duration: float, num_speakers: int | None, report: ProgressReport
    ) -> list[SpeakerTurn]:
        """Quem fala quando, no stem de voz: do cache, ou da diarização (que leva uma fração da duração)."""
        assert self.diarizer is not None
        cached = self.cache_dir / "diarization" / f"{self._turns_key(vocals, num_speakers)}.json"
        if cached.exists():
            return [SpeakerTurn(*item) for item in json.loads(cached.read_text(encoding="utf-8"))]

        def progress(done: int, total: int) -> None:
            report("Separando quem fala", 0.55 + 0.1 * done / max(total, 1))

        wav = extract_audio_wav(self.runner, vocals, cached.with_suffix(".16k.wav"))
        started = time.perf_counter()
        try:
            turns = self.diarizer.diarize(wav, num_speakers, progress)
        finally:
            wav.unlink(missing_ok=True)
        elapsed = time.perf_counter() - started
        self.log(
            f"Diarização: {len(speaking_seconds(turns))} falante(s) em {elapsed:.1f} s "
            f"({elapsed / max(duration, 1e-9):.2f}x a duração)"
        )
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(
            json.dumps([[t.start, t.end, t.speaker] for t in turns], ensure_ascii=False), encoding="utf-8"
        )
        return turns

    @staticmethod
    def _attributed(
        segments: list[DubSegment], words: list[Word], turns: list[SpeakerTurn]
    ) -> tuple[list[DubSegment], list[DubSpeaker]]:
        """Dá a cada fala o falante que mais fala nela e escolhe a referência de voz de cada falante.

        A referência sai agora, uma vez, só de palavras de um falante (as sobrepostas ficam de fora), e é gravada
        no projeto: depois, corrigir o falante de uma fala não muda a voz das outras.
        """
        owners = label_words(words, turns)
        speakers: list[DubSpeaker] = []
        for name in speaker_names(turns):
            span = choose_speaker_reference(words, owners, name)
            speakers.append(
                DubSpeaker(name=name)
                if span is None
                else DubSpeaker(
                    name=name, reference_start=span.start, reference_end=span.end, reference_text=span.text
                )
            )
        labeled = [
            segment.model_copy(update={"speaker": speaker})
            for segment, speaker in zip(segments, assign_speakers(segments, turns), strict=True)
        ]
        return labeled, speakers

    def retranslate(self, project: DubProject, on_progress: ProgressReport | None = None) -> DubProject:
        """Traduz de novo as falas que não estão travadas; as travadas (e as já editadas) ficam como estão."""
        return self._translated(project, 0.0, 1.0, on_progress or (lambda _label, _fraction: None))

    def _translated(self, project: DubProject, low: float, high: float, report: ProgressReport) -> DubProject:
        lines = [
            Line(s.id, s.source_text, s.duration, known=s.text if s.locked and s.text.strip() else None)
            for s in project.segments
        ]
        lexicon_terms = [term for term, _ in self.narrator.lexicons(project.brand, None).entries]

        def progress(done: int, total: int) -> None:
            report(
                f"Traduzindo a fala {min(done + 1, total)} de {total}",
                low + (high - low) * done / max(total, 1),
            )

        translations = self.translator.translate(
            lines,
            project.source_language,
            project.target_language,
            glossary_terms(lexicon_terms, project.glossary),
            progress,
        )
        segments = [
            s.model_copy(update={"text": text})
            for s, text in zip(project.segments, translations, strict=True)
        ]
        return project.model_copy(update={"segments": segments, "translator_model": self.translator.model})

    # -- gerar --

    @staticmethod
    def _one_voice_for_the_file(project: DubProject) -> bool:
        """`single`, ou `per_speaker` com menos de dois falantes (uma pessoa só tem uma voz)."""
        return project.speaker_mode == "single" or (
            project.speaker_mode == "per_speaker" and len(project.speakers) < 2
        )

    def _fixed_voice(
        self, project: DubProject, words: list[Word], stems_vocals: Path, vocals: VocalsWindow
    ) -> VoiceProfile | None:
        """A voz que vale para todas as falas: a da biblioteca ou, com um falante só, um clone do arquivo."""
        if project.voice:
            return self.library.get(project.voice)
        if self._one_voice_for_the_file(project):
            return self.speech.voice_near(words, stems_vocals, vocals, None, project.source_language)
        return None

    def _speaker_voices(
        self, project: DubProject, stems_vocals: Path, vocals: VocalsWindow
    ) -> dict[str, VoiceProfile]:
        """Um clone por falante (modo per_speaker), do trecho de referência gravado no projeto.

        Só quem tem fala a dublar e uma referência de 3 s ou mais ganha clone; para os outros vale a
        referência em volta de cada fala, como no modo per_segment.
        """
        if project.speaker_mode != "per_speaker" or project.voice or len(project.speakers) < 2:
            return {}
        spoken = {s.speaker for s in project.segments if s.speaker and s.text.strip()}
        voices: dict[str, VoiceProfile] = {}
        for speaker in project.speakers:
            if speaker.name not in spoken:
                continue
            if (
                speaker.reference_start is None
                or speaker.reference_end is None
                or speaker.reference_text is None
            ):
                self.log(
                    f"{speaker.name}: sem 3 s seguidos de fala para clonar; usa a voz em volta de cada fala"
                )
                continue
            span = ReferenceSpan(speaker.reference_start, speaker.reference_end, speaker.reference_text)
            voices[speaker.name] = self.speech.voice_from_span(
                span, stems_vocals, vocals, project.source_language, name=speaker.name
            )
            self.log(
                f"{speaker.name}: voz clonada do trecho {span.start:.1f} a {span.end:.1f} s "
                f"({voices[speaker.name].id})"
            )
        return voices

    def render(
        self,
        project: DubProject,
        out: Path | None = None,
        on_progress: ProgressReport | None = None,
        steps: int | None = None,
        stems: StemsOptions | None = None,
    ) -> DubResult:
        """Sintetiza as traduções, monta a dublagem no arquivo original e grava o vídeo e a legenda.

        Com `stems`, exporta também as trilhas separadas, reaproveitando as falas já sintetizadas.
        """
        report = on_progress or (lambda _label, _fraction: None)
        src, info = self._checked_source(project)
        out = out or default_output_path(
            src, project.target_language, corrected_suffix(src.suffix, info.has_video)
        )
        if out.resolve() == src.resolve():
            raise ValueError("A saída não pode ser o próprio arquivo original.")
        timings: dict[str, float] = {}
        synthesis = self._synthesize(project, src, info, steps, report, timings)

        report("Montando a dublagem", 0.95)
        with self._stage(timings, "Montagem"):
            self._mix(project, src, info, synthesis.stems, synthesis.clips, out, synthesis.retime)
        exported = None
        if stems is not None:
            with self._stage(timings, "Trilhas separadas"):
                exported = self._write_stems(project, src, info, synthesis, stems)
        srt_path = self._write_srt(out, project, synthesis.reports, synthesis.retime)
        report("Dublagem pronta", 1.0)
        retime = synthesis.retime
        output_seconds = info.duration if retime.is_identity else retime.total_seconds
        return DubResult(
            out, srt_path, synthesis.reports, timings, synthesis.fit_mode, output_seconds, exported
        )

    def export_stems(
        self,
        project: DubProject,
        options: StemsOptions | None = None,
        on_progress: ProgressReport | None = None,
        steps: int | None = None,
    ) -> DubStems:
        """Grava as trilhas separadas (voz dublada, fundo e voz original) para remixar em outro editor.

        As falas passam pelo mesmo caminho do render: as já sintetizadas vêm do cache e só o que falta é gerado.
        """
        report = on_progress or (lambda _label, _fraction: None)
        src, info = self._checked_source(project)
        timings: dict[str, float] = {}
        synthesis = self._synthesize(project, src, info, steps, report, timings)
        report("Gravando as trilhas", 0.95)
        with self._stage(timings, "Trilhas separadas"):
            stems = self._write_stems(project, src, info, synthesis, options or StemsOptions())
        report("Trilhas prontas", 1.0)
        return stems

    def _checked_source(self, project: DubProject) -> tuple[Path, MediaInfo]:
        """O arquivo de origem e suas medidas, depois de conferir que há o que dublar."""
        src = Path(project.source)
        if not src.exists():
            raise FileNotFoundError(f"Arquivo de origem não encontrado: {src}")
        if not any(s.text.strip() for s in project.segments):
            raise ValueError(
                "Nenhuma fala está traduzida. Prepare o projeto de novo ou escreva as traduções."
            )
        return src, self.prober(src)

    def _synthesize(
        self,
        project: DubProject,
        src: Path,
        info: MediaInfo,
        steps: int | None,
        report: ProgressReport,
        timings: dict[str, float],
    ) -> _Synthesis:
        """Separa voz e fundo e sintetiza cada fala (com cache): é o que o vídeo e as trilhas têm em comum."""
        report("Separando a voz do fundo", 0.0)
        with self._stage(timings, "Separação de voz e fundo"):
            stems = self.isolation.isolate(src)
            vocals = VocalsWindow.load(stems.vocals, 0.0)
            needs_clone = not project.voice
            words = (
                self.speech.transcribe_words(stems.vocals, language=project.source_language)
                if needs_clone
                else []
            )
        fixed_voice = self._fixed_voice(project, words, stems.vocals, vocals)
        speaker_voices = self._speaker_voices(project, stems.vocals, vocals)

        fit_mode = self._effective_fit_mode(project, info)
        slots = slot_plan(project.segments, info.duration)
        spoken: list[tuple[DubSegment, DubClip]] = []
        reports: list[SegmentReport] = []
        total = len(project.segments)
        with self._stage(timings, "Síntese das falas"):
            for number, (segment, slot) in enumerate(zip(project.segments, slots, strict=True), 1):
                label = f"Sintetizando a fala {number} de {total}"
                self.log(label)
                report(label, 0.1 + 0.85 * (number - 1) / total)
                entry, clip = self._synthesize_segment(
                    project,
                    segment,
                    slot,
                    fit_mode,
                    fixed_voice,
                    speaker_voices,
                    words,
                    stems.vocals,
                    vocals,
                    steps,
                )
                reports.append(entry)
                if clip is not None:
                    spoken.append((segment, clip))

        # só depois de sintetizar se sabe quanto cada fala dura, e portanto o que precisa esticar
        retime = self._retime_plan(project, reports, info)
        reports = [
            replace(entry, retimed_start=retime.retime(segment.start))
            for segment, entry in zip(project.segments, reports, strict=True)
        ]
        clips = [replace(clip, start=retime.retime(segment.start)) for segment, clip in spoken]
        for entry in (r for r in reports if r.stretch > 1.0):
            self.log(f"Fala {entry.id}: {entry.message}")
        return _Synthesis(stems, clips, reports, fit_mode, retime)

    def _write_stems(
        self, project: DubProject, src: Path, info: MediaInfo, synthesis: _Synthesis, options: StemsOptions
    ) -> DubStems:
        """Roda o ffmpeg das três trilhas na pasta pedida e, se pedido, junta tudo num .zip.

        Com o vídeo esticado, as trilhas seguem a linha do tempo nova (a mesma do arquivo dublado).
        """
        folder = options.out_dir or default_stems_dir(src, project.target_language)
        folder.mkdir(parents=True, exist_ok=True)
        outputs = stem_outputs(folder)
        graph_file = self.cache_dir / "dub" / f"{folder.name}.graph.txt"
        retime = synthesis.retime
        duration = info.duration if retime.is_identity else retime.total_seconds
        built = dub_stems_command(
            synthesis.stems.background,
            synthesis.stems.vocals,
            synthesis.clips,
            outputs,
            graph_file,
            info.duration,
            retime,
        )
        graph_file.parent.mkdir(parents=True, exist_ok=True)
        graph_file.write_text(built.graph, encoding="utf-8")
        self.runner.run(built.command)
        stems = DubStems(folder, outputs, duration, project.keep_original_db)
        if options.make_zip:
            stems = replace(stems, zip_path=zip_stems(stems))
        return stems

    def _effective_fit_mode(self, project: DubProject, info: MediaInfo) -> FitMode:
        """O modo que vale: sem imagem (ou sem taxa de quadros) não há o que esticar, e a voz se ajusta como antes."""
        if project.fit_mode != "voz" and not (info.has_video and info.fps > 0):
            self.log("Sem vídeo para esticar: a voz se ajusta ao tempo (modo voz).")
            return "voz"
        return project.fit_mode

    @staticmethod
    def _retime_plan(project: DubProject, reports: list[SegmentReport], info: MediaInfo) -> RetimePlan:
        """Os trechos esticados do vídeo: a janela original de cada fala que não coube (as que couberam ficam)."""
        windows = [
            StretchWindow(segment.start, segment.end, entry.stretch)
            for segment, entry in zip(project.segments, reports, strict=True)
            if entry.stretch > 1.0
        ]
        return plan_retime(windows, info.duration, info.fps) if windows else IDENTITY

    def _synthesize_segment(
        self,
        project: DubProject,
        segment: DubSegment,
        slot: Slot,
        fit_mode: FitMode,
        fixed_voice: VoiceProfile | None,
        speaker_voices: dict[str, VoiceProfile],
        words: list[Word],
        stems_vocals: Path,
        vocals: VocalsWindow,
        steps: int | None,
    ) -> tuple[SegmentReport, DubClip | None]:
        if not segment.text.strip():
            return self._empty_report(segment), None
        voice = (
            fixed_voice
            or speaker_voices.get(segment.speaker or "")
            or self.speech.voice_near(
                words, stems_vocals, vocals, (segment.start, segment.end), project.source_language
            )
        )
        natural = natural_seconds(
            segment.source_text,
            segment.text,
            segment.duration,
            project.source_language,
            project.target_language,
        )
        fit = plan_fit(natural, slot)
        # No modo `voz` o modelo já recebe a fala comprimida; nos outros a fala é pedida na duração natural, e
        # é a imagem que se ajusta a ela (ou a voz, só até o `atempo`, no misto).
        requested = fit.request_seconds if fit_mode == "voz" else natural
        lexicon = self.narrator.lexicons(project.brand or voice.brand, project.target_language)
        request = VoiceRequest(
            text=normalize_for_speech(spoken_text(segment.text, lexicon), project.target_language),
            language=project.target_language,
            voice=voice,
            steps=steps,
            duration=round(requested, 3),
        )
        cached = self.narrator.is_cached(request)
        path, speech_seconds = self.narrator.speak(request)
        samples, rate = read_wav(path)
        gain = gain_to_match_db(active_rms(samples, rate), vocals.level_within(segment.start, segment.end))
        outcome = (
            plan_voice_fit(speech_seconds, fit)
            if fit_mode == "voz"
            else plan_video_fit(speech_seconds, slot, fit_mode)
        )
        clip = DubClip(path, segment.start, gain, outcome.tempo, outcome.max_seconds)
        entry = SegmentReport(
            id=segment.id,
            start=segment.start,
            end=segment.end,
            text=segment.text,
            natural_seconds=natural,
            requested_seconds=requested,
            speech_seconds=speech_seconds,
            played_seconds=outcome.played_seconds,
            tempo=outcome.tempo,
            status=outcome.status,
            message=outcome.message,
            cached=cached,
            voice=voice.id,
            stretch=outcome.stretch,
            speaker=segment.speaker or "",
        )
        return entry, clip

    @staticmethod
    def _empty_report(segment: DubSegment) -> SegmentReport:
        return SegmentReport(
            id=segment.id,
            start=segment.start,
            end=segment.end,
            text="",
            natural_seconds=0.0,
            requested_seconds=0.0,
            speech_seconds=0.0,
            played_seconds=0.0,
            tempo=1.0,
            status="empty",
            message="sem tradução: a fala fica em silêncio",
            cached=True,
            voice="-",
        )

    def _mix(
        self,
        project: DubProject,
        src: Path,
        info: MediaInfo,
        stems: Stems,
        clips: list[DubClip],
        out: Path,
        retime: RetimePlan,
    ) -> None:
        out.parent.mkdir(parents=True, exist_ok=True)
        graph_file = self.cache_dir / "dub" / f"{out.stem}.graph.txt"
        mix = dub_mix_command(
            src,
            stems.background,
            clips,
            out,
            graph_file,
            info.duration,
            info.has_video,
            original_voice=stems.vocals if project.keep_original_db is not None else None,
            original_voice_db=project.keep_original_db if project.keep_original_db is not None else -18.0,
            retime=retime,
            fps=info.fps,
        )
        graph_file.parent.mkdir(parents=True, exist_ok=True)
        graph_file.write_text(mix.graph, encoding="utf-8")
        self.runner.run(mix.command)

    @staticmethod
    def _write_srt(
        out: Path, project: DubProject, reports: list[SegmentReport], retime: RetimePlan = IDENTITY
    ) -> Path:
        """Legenda no idioma alvo: cada fala aparece enquanto a voz dublada toca, na linha do tempo do arquivo final."""
        cues: list[Cue] = []
        for segment, entry in zip(project.segments, reports, strict=True):
            if entry.status == "empty":
                continue
            begin, end = retimed_span(retime, segment.start, max(entry.played_seconds, 0.5))
            cues += [Cue(a, b, text) for a, b, text in subtitle_cues(written_text(segment.text), begin, end)]
        srt_path = out.with_suffix(".srt")
        srt_path.write_text(to_srt(cues), encoding="utf-8")
        return srt_path


def default_dubbing_service(
    runner: FFmpegRunner,
    log: Callable[[str], None] | None = None,
    library: VoiceLibrary | None = None,
    transcriber: Transcriber | None = None,
    isolation: IsolationService | None = None,
    synthesizer: SpeechSynthesizer | None = None,
    lexicons: LexiconStore | None = None,
    translator: Translator | None = None,
    prober: Callable[[Path], MediaInfo] = probe,
    device: str = "auto",
    diarizer: SpeakerDiarizer | None = None,
) -> DubbingService:
    """Serviço de produção: as peças da correção de fala (Whisper, Demucs, OmniVoice), o tradutor do Ollama e a
    diarização local (se o sherpa-onnx estiver instalado; sem ele, o padrão volta a ser o modo per_segment)."""
    from .speech_fix import default_speech_fix_service

    speech = default_speech_fix_service(
        runner,
        log,
        library=library,
        transcriber=transcriber,
        isolation=isolation,
        synthesizer=synthesizer,
        lexicons=lexicons,
        prober=prober,
        device=device,
    )
    return DubbingService(
        translator or OllamaTranslator(),
        speech.transcriber,
        speech.isolation,
        speech.narrator,
        speech.library,
        runner,
        prober=prober,
        log=log,
        diarizer=diarizer or default_diarizer(),
    )


def default_diarizer() -> SpeakerDiarizer | None:
    """O diarizador local, ou None se o sherpa-onnx não está instalado ou `DMAKER_DIARIZATION=off` (aí o
    padrão é o modo per_segment). A variável serve a quem não quer baixar os modelos e aos testes."""
    from importlib.util import find_spec

    if (
        os.environ.get("DMAKER_DIARIZATION", "").strip().lower() in DIARIZATION_OFF
        or find_spec("sherpa_onnx") is None
    ):
        return None
    from ..media.diarization import SherpaDiarizer

    return SherpaDiarizer()
