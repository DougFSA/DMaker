"""Regravar um trecho de fala com a voz do próprio falante, sem gravar de novo.

Fluxo: transcreve (palavras com tempo) -> acha o trecho -> isola voz e fundo da região -> clona a voz do
falante a partir de outro trecho do mesmo arquivo -> sintetiza o texto novo na duração que cabe -> emenda
no original. Cada dependência pesada (Whisper, Demucs, OmniVoice, ffmpeg) entra por parâmetro; a mesma
peça serve depois à dublagem (`transcribe_words` e o clone automático do falante).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .. import config
from ..filtergraph.speech_edit import (
    corrected_suffix,
    speaker_reference_command,
    speech_splice_command,
)
from ..filtergraph.voice import SpeechFinish
from ..media.ffmpeg import FFmpegRunner
from ..media.probe import MediaInfo, probe
from ..media.wavio import read_wav
from ..text.captions import Cue, Word, flatten_words
from ..text.transcribe import Transcriber, extract_audio_wav
from ..voice.levels import active_rms, gain_to_match_db, quietest_time
from ..voice.lexicon_store import LexiconStore
from ..voice.library import REFERENCE_FILE, VoiceLibrary, VoiceProfile
from ..voice.pronunciation import spoken_text
from ..voice.reference import ReferenceSpan, choose_reference_near, choose_reference_span
from ..voice.script import normalize_for_speech
from ..voice.speech_edit import (
    SNAP_RADIUS_SECONDS,
    SpeechEdit,
    SplicePlan,
    compose_text,
    expand_to_breath_group,
    fit_tempo,
    isolation_window,
    locate_phrase,
    pause_room,
    plan_splice,
    text_between,
)
from ..voice.synth import SpeechSynthesizer, VoiceRequest
from .isolation import IsolationService
from .narration import NarrationService

WORDS_RECIPE = "w1"  # muda quando a leitura das palavras muda (invalida o cache de transcrições)
SPEAKER_RECIPE = "s1"
LEVEL_CONTEXT_SECONDS = 6.0  # quanto de fala em volta da região serve de medida de volume do falante
REFERENCE_PADDING_SECONDS = 0.05  # folga na ponta da referência: o tempo do Whisper erra por dezenas de ms
OUTPUT_SUBDIR = "correcao"

ProgressReport = Callable[[str, float], None]  # (etapa, fração de 0 a 1)


@dataclass(frozen=True)
class FixRequest:
    """O que corrigir: o trecho (por texto ou por tempo) e o texto novo, mais as escolhas de voz e saída."""

    src: Path
    text: str
    find: str | None = None
    occurrence: int | None = None
    start: float | None = None
    end: float | None = None
    search_from: float | None = None
    search_to: float | None = None
    voice: str | None = None
    expand: bool = True
    save_voice: str | None = None
    language: str = "pt"
    brand: str | None = None
    steps: int | None = None
    seed: int | None = None
    out: Path | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("Informe o texto novo (o que deve ser dito no lugar).")
        by_time = self.start is not None or self.end is not None
        if bool(self.find) == by_time:
            raise ValueError(
                "Diga o trecho por texto (find) ou por tempo (start e end), não os dois nem nenhum."
            )
        if by_time and (self.start is None or self.end is None):
            raise ValueError("Informe start e end juntos.")
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError(f"end ({self.end}) precisa ser maior que start ({self.start}).")


@dataclass(frozen=True)
class SpeechAudio:
    samples: np.ndarray
    rate: int

    @property
    def seconds(self) -> float:
        return len(self.samples) / self.rate


@dataclass(frozen=True)
class FixResult:
    path: Path
    region_start: float  # trecho do arquivo que foi trocado (pausas vizinhas incluídas)
    region_end: float
    old_text: str  # o que foi dito no trecho escolhido
    new_text: str
    spoken_context: str  # frase completa que o modelo falou (trecho novo no meio das palavras vizinhas)
    rule: str  # como a duração foi decidida
    voice: str
    speech_seconds: float
    squeezed: bool


@dataclass(frozen=True)
class VocalsWindow:
    """O stem de voz de uma janela do arquivo: converte tempo do arquivo em tempo do stem e mede volume."""

    samples: np.ndarray
    rate: int
    start: float  # tempo da janela no arquivo

    @classmethod
    def load(cls, vocals: Path, start: float) -> VocalsWindow:
        samples, rate = read_wav(vocals)
        return cls(samples, rate, start)

    def snap(self, seconds: float) -> float:
        """Tempo no arquivo do ponto mais quieto perto de `seconds` (a emenda cai entre sons, não no meio)."""
        return self.start + quietest_time(self.samples, self.rate, seconds - self.start, SNAP_RADIUS_SECONDS)

    @property
    def end(self) -> float:
        return self.start + len(self.samples) / self.rate

    def _index(self, seconds: float) -> int:
        return max(0, min(len(self.samples), int((seconds - self.start) * self.rate)))

    def level_within(self, start: float, end: float) -> float:
        """Volume da fala entre `start` e `end` (tempo do arquivo); 0 se o stem não cobre o trecho."""
        return active_rms(self.samples[self._index(start) : self._index(end)], self.rate)

    def level_around(self, region_start: float, region_end: float) -> float:
        """Volume da fala nos segundos em volta da região, ela mesma de fora; sem vizinhança, o da janela toda."""
        before = self.samples[self._index(region_start - LEVEL_CONTEXT_SECONDS) : self._index(region_start)]
        after = self.samples[self._index(region_end) : self._index(region_end + LEVEL_CONTEXT_SECONDS)]
        around = np.concatenate([before, after])
        return active_rms(around if around.size else self.samples, self.rate)


class _Stages:
    """Traduz as etapas do serviço em linhas de log e em fração de progresso."""

    def __init__(self, report: ProgressReport | None, log: Callable[[str], None]) -> None:
        self.report = report or (lambda _label, _fraction: None)
        self.log = log

    def begin(self, label: str, low: float, high: float) -> Callable[[int, int], None]:
        """Abre a etapa e devolve o callback (feito, total) que anda de `low` até `high`."""
        self.log(label)
        self.report(label, low)

        def step(done: int, total: int) -> None:
            self.report(label, low + (high - low) * done / max(total, 1))

        return step


def _words_to_json(words: list[Word]) -> str:
    return json.dumps(
        [{"start": w.start, "end": w.end, "text": w.text, "probability": w.probability} for w in words],
        ensure_ascii=False,
    )


def _words_from_json(text: str) -> list[Word]:
    return [Word(w["start"], w["end"], w["text"], w.get("probability")) for w in json.loads(text)]


def _transcript_words(cues: list[Cue]) -> list[Word]:
    """Palavras com tempo (e confiança, quando o Whisper dá) de todas as cues, em ordem."""
    words: list[Word] = []
    for cue in cues:
        words.extend(cue.words or flatten_words([cue]))
    return words


def default_output_path(src: Path, suffix: str) -> Path:
    return config.OUTPUT_DIR / OUTPUT_SUBDIR / f"{src.stem}.corrigido{suffix}"


class SpeechFixService:
    def __init__(
        self,
        transcriber: Transcriber,
        isolation: IsolationService,
        narrator: NarrationService,
        library: VoiceLibrary,
        runner: FFmpegRunner,
        prober: Callable[[Path], MediaInfo] = probe,
        cache_dir: Path | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.transcriber = transcriber
        self.isolation = isolation
        self.narrator = narrator
        self.library = library
        self.runner = runner
        self.prober = prober
        self.cache_dir = cache_dir or config.CACHE_DIR / "speech"
        self.log = log or (lambda _message: None)

    # -- palavras com tempo --

    def _words_key(self, src: Path, start: float | None, end: float | None, language: str) -> str:
        stat = src.stat()
        model = getattr(self.transcriber, "model", type(self.transcriber).__name__)
        parts = [
            WORDS_RECIPE,
            str(src.resolve()),
            stat.st_size,
            stat.st_mtime_ns,
            start,
            end,
            language,
            model,
        ]
        return hashlib.sha256(json.dumps(parts).encode("utf-8")).hexdigest()[:20]

    def transcribe_words(
        self, src: Path, start: float | None = None, end: float | None = None, language: str = "pt"
    ) -> list[Word]:
        """Palavras do arquivo (ou do trecho `start`..`end`) com o tempo no arquivo; o resultado fica em cache."""
        if not src.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {src}")
        key = self._words_key(src, start, end, language)
        cached = self.cache_dir / "words" / f"{key}.json"
        if cached.exists():
            return _words_from_json(cached.read_text(encoding="utf-8"))
        wav = self.cache_dir / "audio" / f"{key}.16k.wav"
        extract_audio_wav(self.runner, src, wav, start, end)
        try:
            transcript = self.transcriber.transcribe(wav, language)
        finally:
            wav.unlink(missing_ok=True)
        offset = start or 0.0
        words = [
            Word(w.start + offset, w.end + offset, w.text, w.probability)
            for w in _transcript_words(transcript.cues)
        ]
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(_words_to_json(words), encoding="utf-8")
        return words

    # -- achar o trecho --

    def _locate(self, request: FixRequest, duration: float) -> tuple[list[Word], float, float]:
        """Palavras da transcrição e o trecho a trocar (início, fim), por texto ou por tempo."""
        if request.find:
            words = self.transcribe_words(
                request.src, request.search_from, request.search_to, request.language
            )
            start, end = locate_phrase(words, request.find, request.occurrence)
            return words, start, end
        assert request.start is not None and request.end is not None  # garantido por FixRequest
        if request.start >= duration:
            raise ValueError(f"start ({request.start:.1f} s) está além do fim do arquivo ({duration:.1f} s).")
        end = min(request.end, duration)
        window = isolation_window(request.start, end, duration)
        words = self.transcribe_words(request.src, window[0], window[1], request.language)
        return words, request.start, end

    # -- voz do falante --

    def _reference_folder(self, vocals: Path, span: ReferenceSpan) -> Path:
        stat = vocals.stat()
        parts = [SPEAKER_RECIPE, str(vocals.resolve()), stat.st_size, stat.st_mtime_ns]
        parts += [round(span.start, 2), round(span.end, 2)]
        key = hashlib.sha256(json.dumps(parts).encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / "speakers" / key

    def speaker_voice(
        self,
        words: list[Word],
        vocals_path: Path,
        vocals: VocalsWindow,
        avoid: tuple[float, float],
        language: str,
    ) -> VoiceProfile:
        """Clone temporário do falante, de um trecho do stem de voz fora de `avoid`; nada vai à biblioteca.

        `words` e `avoid` estão no tempo do arquivo. A referência fica em cache por stem e trecho, então
        reparos seguidos no mesmo ponto reaproveitam a voz.
        """
        inside = [
            w for w in words if vocals.start <= w.start and w.end <= vocals.end
        ]  # só o que o stem cobre
        span = choose_reference_span(inside, *avoid)
        if span is None:
            raise ValueError(
                "Não achei, no mesmo arquivo, um trecho de 3 s ou mais da fala do falante fora do trecho a "
                "corrigir para servir de referência. Informe uma voz da biblioteca (--voice)."
            )
        return self.voice_from_span(span, vocals_path, vocals, language)

    def voice_near(
        self,
        words: list[Word],
        vocals_path: Path,
        vocals: VocalsWindow,
        around: tuple[float, float] | None,
        language: str,
    ) -> VoiceProfile:
        """Clone temporário da voz que fala em `around` (a própria fala conta); sem `around`, a melhor do arquivo.

        É a referência da dublagem, onde não há trecho "errado" a evitar: a fala a dublar é a melhor amostra.
        """
        inside = [w for w in words if vocals.start <= w.start and w.end <= vocals.end]
        span = choose_reference_near(inside, around)
        if span is None:
            raise ValueError(
                "Não achei no arquivo um trecho de 3 s ou mais de fala contínua para clonar a voz. "
                "Informe uma voz da biblioteca (--voice)."
            )
        return self.voice_from_span(span, vocals_path, vocals, language)

    def voice_from_span(
        self,
        span: ReferenceSpan,
        vocals_path: Path,
        vocals: VocalsWindow,
        language: str,
        name: str = "Falante do arquivo",
    ) -> VoiceProfile:
        """Recorta `span` do stem de voz (em cache por stem e trecho) e devolve o clone temporário dele.

        `name` é só o rótulo para quem lê (a dublagem por falante passa "Falante 1"); a identidade do som, e com
        ela o cache das falas, vem do trecho recortado."""
        folder = self._reference_folder(vocals_path, span)
        reference = folder / REFERENCE_FILE
        text_file = folder / "reference.txt"
        if not (reference.exists() and text_file.exists()):
            folder.mkdir(parents=True, exist_ok=True)
            start = vocals.snap(span.start - REFERENCE_PADDING_SECONDS) - vocals.start
            end = vocals.snap(span.end + REFERENCE_PADDING_SECONDS) - vocals.start
            self.runner.run(speaker_reference_command(vocals_path, max(0.0, start), end, reference))
            text_file.write_text(span.text, encoding="utf-8")
        return VoiceProfile(
            id=f"falante-{folder.name[:8]}",
            name=name,
            kind="clone",
            language=language,
            reference=REFERENCE_FILE,
            reference_text=text_file.read_text(encoding="utf-8"),
            folder=folder,
        )

    def _save_speaker(self, profile: VoiceProfile, name: str, language: str) -> VoiceProfile:
        """Passa o clone temporário para a biblioteca do usuário com o nome pedido."""
        assert profile.reference_path is not None
        return self.library.save_clone(
            name,
            profile.reference_path,
            self.runner,
            None,
            reference_text=profile.reference_text,
            language=language,
        )

    # -- correção --

    def fix(self, request: FixRequest, on_progress: ProgressReport | None = None) -> FixResult:
        """Troca o trecho pedido por `request.text` na voz do falante e grava o arquivo corrigido."""
        stages = _Stages(on_progress, self.log)
        src = request.src
        if not src.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {src}")
        info = self.prober(src)
        if not info.has_audio:
            raise ValueError(f"{src.name} não tem faixa de áudio para corrigir.")

        stages.begin("Transcrevendo para achar o trecho", 0.0, 0.1)
        words, found_start, found_end = self._locate(request, info.duration)
        edit = SpeechEdit(found_start, found_end, request.text)
        group_start, group_end = (
            expand_to_breath_group(words, edit.start, edit.end) if request.expand else (edit.start, edit.end)
        )
        old_text = text_between(words, edit.start, edit.end)
        self.log(f'Trecho a trocar ({edit.start:.1f} a {edit.end:.1f} s): "{old_text}"')

        window_start, window_end = isolation_window(edit.start, edit.end, info.duration)
        whole_file = window_start <= 0.0 and window_end >= info.duration
        stems = self.isolation.isolate(
            src,
            None if whole_file else window_start,
            None if whole_file else window_end,
            on_progress=stages.begin("Separando a voz do fundo", 0.1, 0.45),
        )
        vocals = VocalsWindow.load(stems.vocals, window_start)

        context = compose_text(words, edit, group_start, group_end)
        room_before, room_after = pause_room(words, group_start, group_end, info.duration)
        plan = plan_splice(
            group_start,
            group_end,
            text_between(words, group_start, group_end),
            context,
            room_before,
            room_after,
            vocals.snap,
        )
        self.log(f"Duração: {plan.rule}")

        stages.begin("Preparando a voz do falante", 0.45, 0.5)
        voice = self._voice(request, words, stems.vocals, vocals, (group_start, group_end))
        stages.begin("Sintetizando a fala nova (na CPU leva alguns minutos)", 0.5, 0.95)
        speech_request, speech = self._synthesize(request, context, voice, plan)
        stages.begin("Emendando no arquivo", 0.95, 1.0)
        out = self._splice(request, info, stems.background, vocals, plan, speech_request, speech)
        return FixResult(
            path=out,
            region_start=plan.region_start,
            region_end=plan.region_end,
            old_text=old_text,
            new_text=request.text,
            spoken_context=context,
            rule=plan.rule,
            voice=voice.id,
            speech_seconds=speech.seconds,
            squeezed=plan.squeezed,
        )

    def _voice(
        self,
        request: FixRequest,
        words: list[Word],
        vocals_path: Path,
        vocals: VocalsWindow,
        avoid: tuple[float, float],
    ) -> VoiceProfile:
        """A voz pedida; sem ela, o clone temporário do falante (ou salvo na biblioteca se `save_voice`)."""
        if request.voice:
            return self.library.get(request.voice)
        profile = self.speaker_voice(words, vocals_path, vocals, avoid, request.language)
        if request.save_voice:
            return self._save_speaker(profile, request.save_voice, request.language)
        return profile

    def _synthesize(
        self, request: FixRequest, context: str, voice: VoiceProfile, plan: SplicePlan
    ) -> tuple[VoiceRequest, SpeechAudio]:
        """Sintetiza o texto do grupo (com a pronúncia da marca) na duração do plano; a fala sai CRUA.

        Ela ainda pode precisar de `atempo` para caber, e a marca d'água não sobrevive a isso: a marca só
        entra em `_splice`, depois de decidido o andamento."""
        lexicon = self.narrator.lexicons(request.brand or voice.brand, request.language)
        voice_request = VoiceRequest(
            text=normalize_for_speech(spoken_text(context, lexicon), request.language),
            language=request.language,
            voice=voice,
            steps=request.steps,
            seed=request.seed,
            duration=round(plan.target_duration, 3),
        )
        path, _ = self.narrator.speak_dry(voice_request)
        samples, rate = read_wav(path)
        return voice_request, SpeechAudio(samples, rate)

    def _splice(
        self,
        request: FixRequest,
        info: MediaInfo,
        background: Path,
        vocals: VocalsWindow,
        plan: SplicePlan,
        speech_request: VoiceRequest,
        speech: SpeechAudio,
    ) -> Path:
        """Iguala o volume da fala nova ao do falante e emenda no original."""
        gain = gain_to_match_db(
            active_rms(speech.samples, speech.rate), vocals.level_around(plan.region_start, plan.region_end)
        )
        tempo = fit_tempo(speech.seconds, plan.usable_end - plan.speech_start)
        # o `atempo` é aplicado à fala antes da marca d'água; a emenda recebe a fala já na velocidade final
        speech_path, _ = self.narrator.speak(speech_request, SpeechFinish(tempo=tempo))
        out = request.out or default_output_path(
            request.src, corrected_suffix(request.src.suffix, info.has_video)
        )
        if out.resolve() == request.src.resolve():
            raise ValueError("A saída não pode ser o próprio arquivo original.")
        out.parent.mkdir(parents=True, exist_ok=True)
        self.runner.run(
            speech_splice_command(
                request.src,
                background,
                speech_path,
                out,
                plan,
                background_offset=vocals.start,
                gain_db=gain,
                sample_rate=info.sample_rate or 48000,
                layout="mono" if info.channels == 1 else "stereo",
                has_video=info.has_video,
                source_duration=info.duration,
            )
        )
        return out


def default_speech_fix_service(
    runner: FFmpegRunner,
    log: Callable[[str], None] | None = None,
    library: VoiceLibrary | None = None,
    transcriber: Transcriber | None = None,
    isolation: IsolationService | None = None,
    synthesizer: SpeechSynthesizer | None = None,
    lexicons: LexiconStore | None = None,
    prober: Callable[[Path], MediaInfo] = probe,
    device: str = "auto",
) -> SpeechFixService:
    """Serviço de produção: Whisper, Demucs e o roteador de vozes; o que vier por parâmetro (testes) vale no lugar."""
    from ..media.separation import DemucsSeparator
    from ..text.transcribe import WhisperTranscriber
    from .isolation import default_isolation_service
    from .voices import build_synthesizer, shared_synthesizer

    if isolation is None:
        isolation = (
            default_isolation_service(runner, log)
            if device == "auto"
            else IsolationService(DemucsSeparator(device=device), runner, log=log)
        )
    if synthesizer is None:
        synthesizer = shared_synthesizer() if device == "auto" else build_synthesizer(device)
    narrator = NarrationService(synthesizer, runner, log=log, lexicons=(lexicons or LexiconStore()).for_brand)
    return SpeechFixService(
        transcriber or WhisperTranscriber(),
        isolation,
        narrator,
        library or VoiceLibrary(),
        runner,
        prober=prober,
        log=log,
    )
