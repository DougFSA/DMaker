"""Regravar fala: o serviço com transcritor, isolamento e sintetizador falsos e o ffmpeg só gravado."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dmaker.media.ffmpeg import FFmpegCommand, RecordingRunner
from dmaker.media.probe import MediaInfo
from dmaker.media.separation import Stems
from dmaker.media.wavio import write_wav, write_wav_channels
from dmaker.pipeline.narration import NarrationService
from dmaker.pipeline.speech_fix import FixRequest, SpeechFixService, default_output_path
from dmaker.text.captions import Cue, Word
from dmaker.text.transcribe import Transcript
from dmaker.voice.library import VoiceLibrary
from dmaker.voice.pronunciation import Lexicon
from dmaker.voice.speech_edit import isolation_window
from dmaker.voice.synth import Speech, VoiceRequest

STEM_RATE = 44100
SPEECH_RATE = 24000


def shifted(items: list[tuple[str, float, float]], by: float = 0.0) -> list[Word]:
    return [Word(start + by, end + by, text, 0.9) for text, start, end in items]


# Fala contínua de 1 a 9 s ("a0".."a15", serve de referência), pausa, e a frase a corrigir em torno de 21 a 23 s.
REFERENCE_RUN = [Word(1.0 + i * 0.5, 1.45 + i * 0.5, f"a{i}", 0.9) for i in range(16)]
SENTENCE = shifted(
    [
        ("de", 21.7, 21.8),
        ("João", 21.8, 22.2),
        ("e", 22.2, 22.3),
        ("Maria.", 22.3, 22.9),
    ]
)
WORDS = [
    *REFERENCE_RUN,
    *shifted([("Hoje", 20.0, 20.3), ("é", 20.3, 20.4), ("casamento,", 20.5, 21.1)]),
    *SENTENCE,
]


class FakeTranscriber:
    """Devolve as palavras do roteiro (tempo no arquivo) recortadas pela janela que o serviço extraiu."""

    model = "fake"

    def __init__(self, words: list[Word] = WORDS):
        self.words = words
        self.calls = 0
        self.offset = 0.0  # início da janela extraída, aprendido do comando ffmpeg

    def transcribe(self, wav: Path, language: str, initial_prompt: str | None = None) -> Transcript:
        self.calls += 1
        relative = [
            Word(w.start - self.offset, w.end - self.offset, w.text, w.probability) for w in self.words
        ]
        return Transcript(
            [Cue(relative[0].start, relative[-1].end, " ".join(w.text for w in relative), relative)]
        )


class FakeIsolation:
    """Grava stems reais (tom no lugar da voz, ruído baixo no fundo) e anota cada janela pedida."""

    def __init__(self, root: Path):
        self.root = root
        self.calls: list[tuple[float | None, float | None]] = []

    def isolate(self, src, start=None, end=None, audio_stream=0, on_progress=None) -> Stems:
        self.calls.append((start, end))
        stems = Stems.in_directory(self.root / f"stems-{start}-{end}")
        if stems.exist():  # como o cache real: a segunda chamada devolve os mesmos arquivos
            return stems
        stems.vocals.parent.mkdir(parents=True, exist_ok=True)
        length = int(((end if end is not None else 40.0) - (start or 0.0)) * STEM_RATE)
        t = np.arange(length) / STEM_RATE
        voice = (0.2 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)
        write_wav_channels(stems.vocals, np.stack([voice, voice], axis=1), STEM_RATE)
        write_wav_channels(stems.background, np.zeros((length, 2), dtype=np.float32), STEM_RATE)
        if on_progress:
            on_progress(1, 1)
        return stems


class FakeSynthesizer:
    """Seno na duração pedida (como o OmniVoice com `duration`); sem ela, 0,05 s por caractere."""

    engine_id = "fake-fix"

    def __init__(self):
        self.requests: list[VoiceRequest] = []

    def synthesize(self, request: VoiceRequest) -> Speech:
        self.requests.append(request)
        seconds = request.duration if request.duration else len(request.text) * 0.05
        t = np.arange(int(seconds * SPEECH_RATE)) / SPEECH_RATE
        return Speech((0.1 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), SPEECH_RATE)


def video_info(path: Path, duration: float = 40.0, has_video: bool = True) -> MediaInfo:
    return MediaInfo(path, duration, 1920, 1080, 30.0, has_video, True, False, sample_rate=48000, channels=2)


class Harness:
    def __init__(
        self, tmp_path: Path, duration: float = 40.0, has_video: bool = True, words: list[Word] = WORDS
    ):
        self.tmp_path = tmp_path
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.src = tmp_path / "entrevista.mp4"
        self.src.write_bytes(b"video")
        self.transcriber = FakeTranscriber(words)
        self.isolation = FakeIsolation(tmp_path / "isolation")
        self.synthesizer = FakeSynthesizer()
        self.library = VoiceLibrary(tmp_path / "voices")
        self.runner = RecordingRunner(on_run=self._on_run)
        self.lexicon = Lexicon()  # vale para qualquer idioma, a menos que `by_language` esteja preenchido
        self.by_language: dict[str, Lexicon] = {}
        narrator = NarrationService(
            self.synthesizer, self.runner, tmp_path / "voice-cache", lexicons=self._lexicon_for
        )
        self.service = SpeechFixService(
            self.transcriber,
            self.isolation,
            narrator,
            self.library,
            self.runner,
            prober=lambda path: video_info(path, duration, has_video),
            cache_dir=tmp_path / "speech",
        )

    def _on_run(self, command: FFmpegCommand) -> None:
        out = Path(command.args[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.suffix == ".wav":
            write_wav(out, np.zeros(1600, dtype=np.float32), 16000)
        else:
            out.write_bytes(b"corrigido")
        if command.label == "áudio para transcrição":
            self.transcriber.offset = (
                float(command.args[command.args.index("-ss") + 1]) if "-ss" in command.args else 0.0
            )

    def labeled(self, label: str) -> list[FFmpegCommand]:
        return [c for c in self.runner.commands if label in c]

    def _lexicon_for(self, _brand: str | None, language: str | None) -> Lexicon:
        """Dicionário falso como o real: por idioma, e `language=None` junta os termos de todos."""
        if not self.by_language:
            return self.lexicon
        if language is None:
            return Lexicon.of(
                {term: spoken for lexicon in self.by_language.values() for term, spoken in lexicon.entries}
            )
        return self.by_language.get(language, Lexicon())

    def request(self, **options) -> FixRequest:
        defaults = {"src": self.src, "text": "Pedro", "find": "João", "out": self.tmp_path / "saida.mp4"}
        return FixRequest(**{**defaults, **options})


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


def splice_args(harness: Harness) -> list[str]:
    return next(c for c in harness.runner.commands if "-filter_complex" in c)


# ---------- o pedido ----------


def test_request_needs_exactly_one_way_to_say_where():
    src = Path("a.mp4")
    with pytest.raises(ValueError, match="texto \\(find\\) ou por tempo"):
        FixRequest(src, text="x")
    with pytest.raises(ValueError, match="texto \\(find\\) ou por tempo"):
        FixRequest(src, text="x", find="a", start=1.0, end=2.0)
    with pytest.raises(ValueError, match="start e end juntos"):
        FixRequest(src, text="x", start=1.0)
    with pytest.raises(ValueError, match="maior que start"):
        FixRequest(src, text="x", start=5.0, end=2.0)
    with pytest.raises(ValueError, match="texto novo"):
        FixRequest(src, text="  ", find="a")


# ---------- palavras ----------


def test_transcribe_words_returns_words_with_confidence_and_caches_them(harness: Harness):
    first = harness.service.transcribe_words(harness.src)
    again = harness.service.transcribe_words(harness.src)
    assert [w.text for w in first][:2] == ["a0", "a1"] and first[0].probability == 0.9
    assert [(w.start, w.end) for w in again] == [(w.start, w.end) for w in first]
    assert harness.transcriber.calls == 1  # a segunda leitura vem do cache


def test_transcribe_words_of_a_window_adds_the_offset_back(tmp_path: Path):
    words = shifted([("meio", 3905.0, 3905.5)])
    harness = Harness(tmp_path, duration=7000.0, words=words)
    result = harness.service.transcribe_words(harness.src, 3900.0, 3930.0)
    assert (result[0].start, result[0].end) == (3905.0, 3905.5)
    extract = harness.labeled("-ss")[0]
    assert extract[extract.index("-ss") + 1] == "3900.000" and extract[extract.index("-t") + 1] == "30.000"


def test_transcribe_words_cache_is_per_window(harness: Harness):
    harness.service.transcribe_words(harness.src, 0.0, 10.0)
    harness.service.transcribe_words(harness.src, 5.0, 15.0)
    harness.service.transcribe_words(harness.src, 0.0, 10.0)
    assert harness.transcriber.calls == 2


def test_transcribe_words_missing_file(harness: Harness, tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="não encontrado"):
        harness.service.transcribe_words(tmp_path / "nada.mp4")


# ---------- correção ----------


def test_fix_by_text_forces_the_duration_and_uses_the_group_context(harness: Harness):
    result = harness.service.fix(harness.request())

    assert result.old_text == "João" and result.new_text == "Pedro"
    assert result.spoken_context == "de Pedro e Maria."  # o grupo de fôlego inteiro, com a troca no meio
    request = harness.synthesizer.requests[0]
    assert request.text == "de Pedro e Maria."
    assert request.duration == pytest.approx(1.2)  # a duração do grupo original (21,7 a 22,9)
    assert "mantida" in result.rule and not result.squeezed
    assert result.path == harness.tmp_path / "saida.mp4"


def test_fix_splices_the_original_video_with_copy_and_only_the_region_changes(harness: Harness):
    result = harness.service.fix(harness.request())
    args = splice_args(harness)
    assert args[args.index("-c:v") + 1] == "copy"
    assert str(harness.src) in args and "-map" in args
    assert result.region_start < 21.7 and result.region_end > 22.9
    assert result.region_start > 21.1 and result.region_end < 23.5  # dentro das pausas vizinhas
    assert result.path.exists()


def test_fix_clones_the_speaker_from_a_stretch_outside_the_part_to_fix(harness: Harness):
    harness.service.fix(harness.request())
    voice = harness.synthesizer.requests[0].voice
    assert voice.kind == "clone" and voice.id.startswith("falante-")
    assert voice.reference_text.startswith("a0 a1")  # só a fala contínua do começo serve
    assert voice.reference_path.parent.parent.name == "speakers"

    cut = next(c for c in harness.runner.commands if "-ac" in c and "24000" in c)
    start = float(cut[cut.index("-ss") + 1])
    end = start + float(cut[cut.index("-t") + 1])
    assert 3.0 <= end - start <= 15.0
    assert end <= 21.7 - 0.2  # termina antes do grupo a corrigir


def test_fix_does_not_touch_the_user_library_by_default(harness: Harness):
    harness.service.fix(harness.request())
    assert harness.library.list(presets=False) == []


def test_fix_can_save_the_speaker_voice_with_a_name(harness: Harness):
    harness.service.fix(harness.request(save_voice="Entrevistado"))
    saved = harness.library.get("entrevistado")
    assert saved.kind == "clone" and saved.reference_text.startswith("a0 a1")
    assert harness.synthesizer.requests[0].voice.id == "entrevistado"


def test_fix_with_a_library_voice_skips_the_automatic_clone(harness: Harness):
    harness.library.save_design("Locutora", "female")
    harness.service.fix(harness.request(voice="locutora"))
    assert harness.synthesizer.requests[0].voice.id == "locutora"
    assert not any("-ar" in c and "24000" in c for c in harness.runner.commands)


def test_fix_reuses_words_stems_and_speaker_reference_on_the_second_run(harness: Harness):
    harness.service.fix(harness.request())
    harness.service.fix(harness.request(text="Paulo", out=harness.tmp_path / "outra.mp4"))
    assert harness.transcriber.calls == 1
    references = [c for c in harness.runner.commands if "-ar" in c and "24000" in c]
    assert len(references) == 1  # o recorte da referência ficou em cache


def test_fix_by_time_uses_the_window_around_the_edit(harness: Harness):
    result = harness.service.fix(harness.request(find=None, start=21.8, end=22.2))
    assert result.old_text == "João"
    assert harness.synthesizer.requests[0].duration == pytest.approx(1.2)


def test_fix_without_expansion_speaks_only_the_new_words(harness: Harness):
    result = harness.service.fix(harness.request(expand=False))
    request = harness.synthesizer.requests[0]
    assert request.text == "Pedro"
    # 4 letras viram 5 (0,4 s x 1,25 = 0,5 s), mas "João" está colada nas vizinhas: sem pausa para tomar emprestada,
    # só cabem os 0,4 s do original menos os fades, e a fala é comprimida
    assert request.duration == pytest.approx(0.4)
    assert result.squeezed and "comprimida" in result.rule
    assert result.spoken_context == "Pedro"


def test_fix_longer_text_stretches_the_group_into_the_pauses(harness: Harness):
    result = harness.service.fix(harness.request(text="Joaquim Eduardo"))
    request = harness.synthesizer.requests[0]
    assert request.duration > 1.2
    assert "esticado" in result.rule or result.squeezed


def test_fix_applies_the_pronunciation_dictionary_to_the_spoken_text(harness: Harness):
    harness.lexicon = Lexicon.of({"DMaker": "Di Meiker"})
    result = harness.service.fix(harness.request(text="DMaker"))
    assert harness.synthesizer.requests[0].text == "de Di Meiker e Maria."
    assert result.spoken_context == "de DMaker e Maria."  # o texto escrito não muda


def test_fix_matches_the_loudness_of_the_speaker(harness: Harness):
    harness.service.fix(harness.request())
    graph = splice_args(harness)[splice_args(harness).index("-filter_complex") + 1]
    # o stem tem tom de 0,2 e a fala de 0,1: o ganho vai ao teto de +9 dB (a diferença é de 6 dB)
    assert "volume=6." in graph


def test_fix_reports_progress_stages_in_order(harness: Harness):
    reports: list[tuple[str, float]] = []
    harness.service.fix(
        harness.request(), on_progress=lambda label, fraction: reports.append((label, fraction))
    )
    fractions = [fraction for _, fraction in reports]
    assert fractions == sorted(fractions) and fractions[0] == 0.0 and fractions[-1] >= 0.95
    labels = [label for label, _ in reports]
    assert labels[0].startswith("Transcrevendo") and labels[-1].startswith("Emendando")
    assert any(label.startswith("Sintetizando") for label in labels)


def test_fix_logs_the_duration_rule(tmp_path: Path):
    logged: list[str] = []
    harness = Harness(tmp_path)
    harness.service.log = logged.append
    harness.service.fix(harness.request())
    assert any(line.startswith("Duração: duração do trecho original mantida") for line in logged)


# ---------- arquivos longos ----------


def test_fix_isolates_only_a_window_around_a_long_file(tmp_path: Path):
    words = shifted([("a", 3900.0 + i * 0.5, 3900.45 + i * 0.5) for i in range(16)], 0.0)
    words += shifted([("de", 3921.7, 3921.8), ("João", 3921.8, 3922.2), ("e", 3922.2, 3922.3)])
    harness = Harness(tmp_path, duration=7000.0, words=words)
    harness.service.fix(harness.request())
    start, end = harness.isolation.calls[0]
    assert (start, end) == isolation_window(3921.8, 3922.2, 7000.0)
    assert end - start == 60.0
    assert splice_args(harness)  # a emenda usa o fundo da janela (deslocamento = início da janela)
    graph = splice_args(harness)[splice_args(harness).index("-filter_complex") + 1]
    assert "[0:a:0]" in graph and "asplit" in graph  # antes e depois vêm do original inteiro


def test_fix_whole_short_file_is_isolated_without_a_window(harness: Harness):
    harness.service.fix(harness.request())
    assert harness.isolation.calls == [(None, None)]


# ---------- áudio e saída ----------


def test_fix_of_an_audio_file_writes_audio_with_the_same_extension(tmp_path: Path):
    harness = Harness(tmp_path, has_video=False)
    audio = tmp_path / "entrevista.wav"
    audio.write_bytes(b"audio")
    out = tmp_path / "corrigido.wav"
    harness.service.fix(harness.request(src=audio, out=out))
    args = splice_args(harness)
    assert "-c:v" not in args and "pcm_s16le" in args


def test_default_output_goes_to_output_correcao_next_to_the_name(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("dmaker.config.OUTPUT_DIR", tmp_path / "output")
    harness = Harness(tmp_path)
    result = harness.service.fix(harness.request(out=None))
    assert result.path == tmp_path / "output" / "correcao" / "entrevista.corrigido.mp4"
    assert default_output_path(Path("x/video.mov"), ".mov").name == "video.corrigido.mov"


def test_fix_refuses_to_overwrite_the_original(harness: Harness):
    with pytest.raises(ValueError, match="próprio arquivo"):
        harness.service.fix(harness.request(out=harness.src))


# ---------- erros ----------


def test_fix_phrase_not_found_lists_similar_text(harness: Harness):
    with pytest.raises(ValueError, match="Não achei"):
        harness.service.fix(harness.request(find="Joana"))
    assert harness.synthesizer.requests == []  # falhou antes de gastar CPU com a síntese
    assert harness.isolation.calls == []


def test_fix_without_other_speech_for_reference_explains_what_to_do(tmp_path: Path):
    only_edit = SENTENCE
    harness = Harness(tmp_path, words=only_edit)
    with pytest.raises(ValueError, match="--voice"):
        harness.service.fix(harness.request())


def test_fix_file_without_audio_or_missing(harness: Harness, tmp_path: Path):
    silent = Harness(tmp_path / "mudo")
    silent.service.prober = lambda path: MediaInfo(path, 10.0, 100, 100, 30.0, True, False, False)
    with pytest.raises(ValueError, match="não tem faixa de áudio"):
        silent.service.fix(silent.request())
    with pytest.raises(FileNotFoundError, match="não encontrado"):
        harness.service.fix(harness.request(src=tmp_path / "fantasma.mp4"))


def test_fix_by_time_beyond_the_end_of_the_file(harness: Harness):
    with pytest.raises(ValueError, match="além do fim"):
        harness.service.fix(harness.request(find=None, start=99.0, end=100.0))


def test_fix_reference_comes_only_from_the_isolated_window(tmp_path: Path):
    far = [
        Word(100.0 + i * 0.5, 100.45 + i * 0.5, f"longe{i}", 0.99) for i in range(20)
    ]  # ótima, mas fora da janela
    near = shifted([("de", 3921.7, 3921.8), ("João", 3921.8, 3922.2), ("e", 3922.2, 3922.3)])
    harness = Harness(tmp_path, duration=7000.0, words=[*far, *near])
    with pytest.raises(ValueError, match="--voice"):
        harness.service.fix(harness.request())
    assert harness.synthesizer.requests == []


def test_fix_applies_only_the_pronunciation_of_the_language_of_the_speech(harness: Harness):
    harness.by_language = {
        "pt": Lexicon.of({"DMaker": "Di Meiker"}),
        "en": Lexicon.of({"DMaker": "Dee Maker"}),
    }

    harness.service.fix(harness.request(text="DMaker", language="pt"))
    assert harness.synthesizer.requests[-1].text == "de Di Meiker e Maria."

    harness.service.fix(harness.request(text="DMaker", language="en"))
    assert harness.synthesizer.requests[-1].text == "de Dee Maker e Maria."


def test_fix_in_a_language_without_an_entry_reads_the_term_as_written(harness: Harness):
    harness.by_language = {"pt": Lexicon.of({"DMaker": "Di Meiker"})}

    harness.service.fix(harness.request(text="DMaker", language="en"))

    assert harness.synthesizer.requests[0].text == "de DMaker e Maria."
