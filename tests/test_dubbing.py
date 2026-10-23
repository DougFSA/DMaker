"""Serviço de dublagem com transcritor, isolamento, tradutor e sintetizador falsos e o ffmpeg só gravado."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from dmaker.domain.dub import DubProject, load_dub_project, save_dub_project
from dmaker.media.ffmpeg import FFmpegCommand
from dmaker.pipeline.dubbing import (
    DubbingService,
    default_dubbing_service,
    default_output_path,
    default_project_path,
    glossary_terms,
    project_summary,
)
from dmaker.text.captions import Word
from dmaker.text.translate import Line
from dmaker.voice.pronunciation import Lexicon
from tests.test_speech_fix import Harness


def sentence(text: str, start: float, per_word: float = 0.5) -> list[Word]:
    words, cursor = [], start
    for token in text.split():
        words.append(Word(cursor, cursor + per_word, token, 0.9))
        cursor += per_word + 0.02
    return words


# Três frases de 3 a 4 s separadas por pausas de 1 s, num arquivo de 40 s.
S1 = "Olá pessoal, hoje vamos falar do DMaker."  # 7 palavras
S2 = "Primeiro precisamos escolher a música certa."  # 6 palavras
S3 = "Depois é só exportar o vídeo e publicar."  # 8 palavras
WORDS = [*sentence(S1, 2.0), *sentence(S2, 8.0), *sentence(S3, 14.0)]


class FakeTranslator:
    model = "tradutor-falso"

    def __init__(self, replies: dict[str, str] | None = None):
        self.replies = replies or {}
        self.calls: list[dict] = []

    def translate(
        self,
        lines: Sequence[Line],
        source: str,
        target: str,
        glossary: Sequence[str] = (),
        on_progress=None,
    ) -> list[str]:
        self.calls.append(
            {"lines": list(lines), "source": source, "target": target, "glossary": list(glossary)}
        )
        if on_progress:
            on_progress(0, len(lines))
            on_progress(len(lines), len(lines))
        return [
            line.known if line.known is not None else self.replies.get(line.id, f"EN {line.text}")
            for line in lines
        ]


class DubHarness:
    """A mesma bancada da correção de fala (fakes de Whisper, Demucs e OmniVoice) com um tradutor falso."""

    def __init__(self, tmp_path: Path, words: list[Word] = WORDS):
        self.base = Harness(tmp_path, words=words)
        self.translator = FakeTranslator()
        self.service = DubbingService(
            self.translator,
            self.base.transcriber,
            self.base.isolation,
            self.base.service.narrator,
            self.base.library,
            self.base.runner,
            prober=self.base.service.prober,
            cache_dir=tmp_path / "speech",
        )
        self.commands: list[FFmpegCommand] = []
        record = self.base.runner.on_run
        self.base.runner.on_run = lambda command: (self.commands.append(command), record(command))[1]
        self.src = self.base.src
        self.project_path = tmp_path / "saida" / "entrevista.en.dub.json"
        self.out = tmp_path / "saida" / "entrevista.en.mp4"

    @property
    def synthesizer(self):
        return self.base.synthesizer

    @property
    def runner(self):
        return self.base.runner

    def labeled(self, label: str) -> list[FFmpegCommand]:
        return [c for c in self.commands if c.label == label]

    def prepare(self, **options) -> DubProject:
        return self.service.prepare(self.src, "en", project_path=self.project_path, **options)

    def mix_commands(self) -> list[FFmpegCommand]:
        return self.labeled("dublagem")

    def graph(self) -> str:
        return next(
            Path(arg) for arg in self.mix_commands()[-1].args if arg.endswith(".graph.txt")
        ).read_text(encoding="utf-8")


@pytest.fixture
def dub(tmp_path: Path) -> DubHarness:
    return DubHarness(tmp_path)


# ---------- preparar ----------


def test_prepare_writes_an_editable_project_with_translated_phrases(dub: DubHarness):
    project = dub.prepare()
    assert [s.source_text for s in project.segments] == [S1, S2, S3]
    assert [s.text for s in project.segments] == [f"EN {S1}", f"EN {S2}", f"EN {S3}"]
    assert (project.source_language, project.target_language) == ("pt", "en")
    assert project.translator_model == "tradutor-falso" and project.source == str(dub.src.resolve())
    assert load_dub_project(dub.project_path) == project
    assert [s.id for s in project.segments] == ["s1", "s2", "s3"]
    assert project.segments[0].start == pytest.approx(2.0)


def test_prepare_transcribes_the_voice_stem_not_the_mixed_file(dub: DubHarness):
    dub.prepare()
    extractions = dub.labeled("áudio para transcrição")
    assert len(extractions) == 1
    source_of_audio = extractions[0].args[extractions[0].args.index("-i") + 1]
    assert source_of_audio.endswith("vocals.wav") or "stems" in source_of_audio
    assert str(dub.src) not in extractions[0].args


def test_prepare_sends_the_glossary_with_the_pronunciation_terms_and_the_user_terms(dub: DubHarness):
    dub.base.lexicon = Lexicon.of({"DMaker": "Di Mêiker"})
    dub.prepare(glossary=["MedlyCare", "dmaker"])
    call = dub.translator.calls[0]
    assert call["glossary"] == ["DMaker", "MedlyCare"]
    assert (call["source"], call["target"]) == ("pt", "en")
    assert [line.seconds for line in call["lines"]][0] == pytest.approx(3.5, abs=0.2)


def test_prepare_keeps_the_choices_in_the_project(dub: DubHarness):
    dub.base.library.save_design("Locutora", "female, low pitch", language="en")
    project = dub.prepare(speaker_mode="single", voice="locutora", keep_original_db=-18.0, brand=None)
    assert (project.speaker_mode, project.voice, project.keep_original_db) == ("single", "locutora", -18.0)


def test_prepare_reports_stage_progress(dub: DubHarness):
    seen: list[tuple[str, float]] = []
    dub.prepare(on_progress=lambda label, fraction: seen.append((label, fraction)))
    labels = [label for label, _ in seen]
    assert labels[0].startswith("Separando") and any(label.startswith("Transcrevendo") for label in labels)
    assert any(label.startswith("Traduzindo a fala") for label in labels)
    assert seen[-1][1] == 1.0 and [f for _, f in seen] == sorted(f for _, f in seen)


def test_prepare_refuses_bad_requests_before_working(dub: DubHarness, tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        dub.service.prepare(tmp_path / "nada.mp4", "en")
    with pytest.raises(ValueError, match="diferente do idioma de origem"):
        dub.service.prepare(dub.src, "pt", "pt-BR")
    with pytest.raises(Exception, match="fantasma"):
        dub.service.prepare(dub.src, "en", voice="fantasma")
    assert dub.base.isolation.calls == []


def test_prepare_with_no_words_reports_no_speech(dub: DubHarness, monkeypatch):
    monkeypatch.setattr(dub.service.speech, "transcribe_words", lambda *args, **kwargs: [])
    with pytest.raises(ValueError, match="Não encontrei fala"):
        dub.prepare()


def test_prepare_refuses_a_file_without_audio(dub: DubHarness):
    from dmaker.media.probe import MediaInfo

    dub.service.prober = lambda path: MediaInfo(path, 5.0, 1920, 1080, 30.0, True, False, False)
    with pytest.raises(ValueError, match="não tem faixa de áudio"):
        dub.prepare()


# ---------- gerar ----------


def test_render_synthesizes_each_translation_in_the_target_language_with_a_forced_duration(dub: DubHarness):
    dub.prepare()
    result = dub.service.render(load_dub_project(dub.project_path), dub.out)
    requests = dub.synthesizer.requests
    assert [r.text for r in requests] == [f"EN {S1}", f"EN {S2}", f"EN {S3}"]
    assert {r.language for r in requests} == {"en"}
    assert all(r.duration and r.duration > 0 for r in requests)
    assert result.path == dub.out and dub.out.exists()
    assert result.srt_path == dub.out.with_suffix(".srt") and result.srt_path.exists()
    # o inglês de "EN ..." é um pouco mais longo que a fala original: avança na pausa, sem acelerar nem cortar
    assert [r.status for r in result.report] == ["advances"] * 3
    assert result.warnings == [] and all(r.tempo == 1.0 for r in result.report)


def test_render_mixes_background_and_each_clip_at_its_position_and_copies_the_video(dub: DubHarness):
    dub.prepare()
    dub.service.render(load_dub_project(dub.project_path), dub.out)
    (command,) = dub.mix_commands()
    assert command.args[command.args.index("-c:v") + 1] == "copy"
    graph = dub.graph()
    assert "adelay=delays=2000:all=1" in graph and "adelay=delays=8000:all=1" in graph
    assert "adelay=delays=14000:all=1" in graph
    assert "amix=inputs=4" in graph  # fundo + 3 falas
    assert "[original]" not in graph


def test_each_segment_clones_the_voice_around_itself(dub: DubHarness):
    dub.prepare()
    dub.service.render(load_dub_project(dub.project_path), dub.out)
    references = [r.voice.reference_text for r in dub.synthesizer.requests]
    assert len(set(references)) == 3  # três falas, três referências
    assert (
        references[0].split()[0] in S1 and references[1].split()[0] in S2 and references[2].split()[0] in S3
    )
    assert all(r.voice.id.startswith("falante-") for r in dub.synthesizer.requests)


def test_single_mode_uses_one_clone_for_the_whole_file(dub: DubHarness):
    dub.prepare(speaker_mode="single")
    dub.service.render(load_dub_project(dub.project_path), dub.out)
    voices = {r.voice.id for r in dub.synthesizer.requests}
    assert len(voices) == 1 and len(dub.labeled("referência do falante")) == 1


def test_a_library_voice_replaces_the_clone(dub: DubHarness):
    dub.base.library.save_design("Locutora", "female, low pitch", language="en")
    dub.prepare(voice="locutora")
    dub.service.render(load_dub_project(dub.project_path), dub.out)
    assert {r.voice.id for r in dub.synthesizer.requests} == {"locutora"}
    assert dub.labeled("referência do falante") == []


def test_render_twice_reuses_every_segment_and_editing_one_translation_regenerates_only_it(dub: DubHarness):
    project = dub.prepare()
    first = dub.service.render(project, dub.out)
    assert first.regenerated == 3 and len(dub.synthesizer.requests) == 3

    again = dub.service.render(project, dub.out)
    assert again.regenerated == 0 and len(dub.synthesizer.requests) == 3
    assert all(r.cached for r in again.report)

    edited = project.edited("s2", text="First we need to pick the right song.")
    third = dub.service.render(edited, dub.out)
    assert third.regenerated == 1 and len(dub.synthesizer.requests) == 4
    assert dub.synthesizer.requests[-1].text == "First we need to pick the right song."
    assert [r.cached for r in third.report] == [True, False, True]


def test_pronunciation_dictionary_applies_to_the_spoken_text_but_not_the_subtitle(dub: DubHarness):
    dub.base.lexicon = Lexicon.of({"DMaker": "Di Mêiker"})
    project = dub.prepare().edited("s1", text="Hello everyone, today we talk about DMaker.")
    result = dub.service.render(project, dub.out)
    assert dub.synthesizer.requests[0].text == "Hello everyone, today we talk about Di Mêiker."
    assert "DMaker" in result.srt_path.read_text(encoding="utf-8")


def test_keep_original_adds_the_attenuated_voice_stem_to_the_mix(dub: DubHarness):
    dub.prepare(keep_original_db=-18.0)
    dub.service.render(load_dub_project(dub.project_path), dub.out)
    args = dub.mix_commands()[0].args
    assert sum(1 for a in args if a == "-i") == 2 + 1 + 3  # vídeo, fundo, voz original e 3 falas
    assert "volume=-18.0dB" in dub.graph() and "[original]" in dub.graph()


def test_a_translation_that_does_not_fit_is_cut_and_reported(dub: DubHarness):
    project = dub.prepare()
    long_text = " ".join(["this translation is far too long to ever fit in the original slot"] * 4)
    result = dub.service.render(project.edited("s1", text=long_text), dub.out)
    first = result.report[0]
    assert first.status == "overflow" and first.warns and first.tempo > 1.0
    assert result.warnings and "Fala s1" in result.warnings[0] and "encurte a tradução" in result.warnings[0]
    assert "atrim=duration=" in dub.graph() and "afade=t=out" in dub.graph()


def test_an_empty_translation_is_silent_and_not_synthesized(dub: DubHarness):
    project = dub.prepare().edited("s2", text=" ")
    result = dub.service.render(project, dub.out)
    assert [r.status for r in result.report][1] == "empty"
    assert len(dub.synthesizer.requests) == 2
    assert "adelay=delays=8000" not in dub.graph()
    assert result.regenerated == 2


def test_subtitles_are_in_the_target_language_and_follow_the_dubbed_voice(dub: DubHarness):
    project = dub.prepare().edited("s3", text="Then just export the video and publish it.")
    result = dub.service.render(project, dub.out)
    srt = result.srt_path.read_text(encoding="utf-8")
    flat = srt.replace("\n", " ")
    assert "Then just export the video and publish it." in flat and f"EN {S1}" in flat
    assert srt.startswith("1\n00:00:02,000 -->")


def test_render_reports_progress_by_segment_and_times_each_stage(dub: DubHarness):
    seen: list[str] = []
    result = dub.service.render(
        dub.prepare(), dub.out, on_progress=lambda label, fraction: seen.append(label)
    )
    assert [label for label in seen if label.startswith("Sintetizando")] == [
        "Sintetizando a fala 1 de 3",
        "Sintetizando a fala 2 de 3",
        "Sintetizando a fala 3 de 3",
    ]
    assert seen[-1] == "Dublagem pronta"
    assert set(result.timings) == {"Separação de voz e fundo", "Síntese das falas", "Montagem"}


def test_render_steps_are_passed_to_the_synthesizer(dub: DubHarness):
    dub.service.render(dub.prepare(), dub.out, steps=8)
    assert {r.steps for r in dub.synthesizer.requests} == {8}


def test_render_default_output_goes_to_the_dubbing_folder(dub: DubHarness, monkeypatch, tmp_path: Path):
    monkeypatch.setattr("dmaker.config.OUTPUT_DIR", tmp_path / "out")
    result = dub.service.render(dub.prepare())
    assert result.path == tmp_path / "out" / "dublagem" / "entrevista.en.mp4"


def test_render_refuses_bad_projects(dub: DubHarness, tmp_path: Path):
    project = dub.prepare()
    blank = project.model_copy(
        update={"segments": [s.model_copy(update={"text": ""}) for s in project.segments]}
    )
    with pytest.raises(ValueError, match="Nenhuma fala está traduzida"):
        dub.service.render(blank, dub.out)
    gone = project.model_copy(update={"source": str(tmp_path / "sumiu.mp4")})
    with pytest.raises(FileNotFoundError, match="origem"):
        dub.service.render(gone, dub.out)
    with pytest.raises(ValueError, match="próprio arquivo original"):
        dub.service.render(project, dub.src)


def test_audio_only_sources_are_dubbed_to_audio(tmp_path: Path):
    audio = DubHarness(tmp_path)
    audio.base.src.rename(tmp_path / "radio.wav")
    audio.src = tmp_path / "radio.wav"
    audio.base.service.prober = lambda path: __import__(
        "tests.test_speech_fix", fromlist=["video_info"]
    ).video_info(path, 40.0, has_video=False)
    audio.service.prober = audio.base.service.prober
    project = audio.service.prepare(audio.src, "en", project_path=tmp_path / "radio.en.dub.json")
    result = audio.service.render(project, tmp_path / "radio.en.m4a")
    args = audio.mix_commands()[0].args
    assert "-c:v" not in args and "aac" in args and result.path.suffix == ".m4a"


# ---------- traduzir de novo e edição ----------


def test_retranslate_keeps_locked_translations(dub: DubHarness):
    project = dub.prepare().edited("s2", text="My own careful translation.", locked=True)
    dub.translator.replies = {"s1": "New first.", "s3": "New third."}
    again = dub.service.retranslate(project)
    assert [s.text for s in again.segments] == ["New first.", "My own careful translation.", "New third."]
    lines = dub.translator.calls[-1]["lines"]
    assert [line.known for line in lines] == [None, "My own careful translation.", None]
    assert [s.locked for s in again.segments] == [False, True, False]


def test_project_edits_do_not_touch_the_original_text_and_unknown_ids_are_errors(dub: DubHarness):
    project = dub.prepare()
    edited = project.edited("s1", text="Changed")
    assert edited.segment("s1").source_text == S1 and edited.segment("s1").text == "Changed"
    assert project.segment("s1").text != "Changed"  # o original não é alterado no lugar
    with pytest.raises(KeyError, match="s9"):
        project.edited("s9", text="x")


# ---------- peças puras e montagem do serviço ----------


def test_glossary_terms_merge_without_repeating_ignoring_case():
    assert glossary_terms(["DMaker", "MedlyCare"], ["dmaker", " Ollama ", ""]) == [
        "DMaker",
        "MedlyCare",
        "Ollama",
    ]


def test_default_paths_use_the_dubbing_folder(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("dmaker.config.OUTPUT_DIR", tmp_path)
    assert default_project_path(Path("x/video.mp4"), "en") == tmp_path / "dublagem" / "video.en.dub.json"
    assert default_output_path(Path("x/video.mp4"), "es", ".mp4") == tmp_path / "dublagem" / "video.es.mp4"


def test_project_summary_lists_the_segments(dub: DubHarness):
    project = dub.prepare()
    summary = project_summary(project, dub.project_path)
    assert summary["project"] == str(dub.project_path) and summary["target_language"] == "en"
    assert summary["segments"][0] == {
        "id": "s1",
        "start": 2.0,
        "end": pytest.approx(5.62, abs=0.01),
        "original": S1,
        "text": f"EN {S1}",
        "locked": False,
        "speaker": None,
    }


def test_default_service_wires_the_parts_it_is_given(dub: DubHarness, tmp_path: Path):
    service = default_dubbing_service(
        dub.runner,
        library=dub.base.library,
        transcriber=dub.base.transcriber,
        isolation=dub.base.isolation,
        synthesizer=dub.synthesizer,
        translator=dub.translator,
        prober=dub.base.service.prober,
    )
    assert isinstance(service, DubbingService)
    assert service.translator is dub.translator and service.isolation is dub.base.isolation
    assert service.library is dub.base.library and service.speech.transcriber is dub.base.transcriber


def test_project_roundtrip_through_disk(dub: DubHarness, tmp_path: Path):
    project = dub.prepare().edited("s1", text="Editada", locked=True)
    path = save_dub_project(project, tmp_path / "x" / "p.dub.json")
    assert load_dub_project(path) == project
    assert "Editada" in path.read_text(encoding="utf-8") and "—" not in path.read_text(encoding="utf-8")


def test_dubbing_into_english_does_not_apply_the_portuguese_pronunciation(dub: DubHarness):
    dub.base.by_language = {"pt": Lexicon.of({"DMaker": "Di Mêiker"})}
    project = dub.prepare().edited("s1", text="Hello everyone, today we talk about DMaker.")

    dub.service.render(project, dub.out)

    assert dub.synthesizer.requests[0].text == "Hello everyone, today we talk about DMaker."


def test_dubbing_applies_the_pronunciation_of_the_target_language(dub: DubHarness):
    dub.base.by_language = {
        "pt": Lexicon.of({"DMaker": "Di Mêiker"}),
        "en": Lexicon.of({"DMaker": "Dee Maker"}),
    }
    project = dub.prepare().edited("s1", text="Hello everyone, today we talk about DMaker.")

    result = dub.service.render(project, dub.out)

    assert dub.synthesizer.requests[0].text == "Hello everyone, today we talk about Dee Maker."
    assert "DMaker" in result.srt_path.read_text(encoding="utf-8")  # a legenda mantém o texto escrito


def test_glossary_keeps_the_terms_of_every_language_untranslated(dub: DubHarness):
    dub.base.by_language = {
        "pt": Lexicon.of({"DMaker": "Di Mêiker"}),
        "es": Lexicon.of({"MedlyCare": "Medli Care"}),
    }

    dub.prepare(glossary=["Samanta"])

    assert dub.translator.calls[0]["glossary"] == ["DMaker", "MedlyCare", "Samanta"]


def test_inline_override_still_applies_when_dubbing_in_any_language(dub: DubHarness):
    dub.base.by_language = {"pt": Lexicon.of({"DMaker": "Di Mêiker"})}
    project = dub.prepare().edited("s1", text="Hello, today we talk about [[DMaker|Dee Maker]] again.")

    result = dub.service.render(project, dub.out)

    assert dub.synthesizer.requests[0].text == "Hello, today we talk about Dee Maker again."
    assert "[[" not in result.srt_path.read_text(encoding="utf-8")
