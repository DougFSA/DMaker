"""Serviço de dublagem com transcritor, isolamento, tradutor e sintetizador falsos e o ffmpeg só gravado."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from dmaker.domain.dub import DubProject, load_dub_project, save_dub_project
from dmaker.media.ffmpeg import FFmpegCommand
from dmaker.pipeline.dub_stems import StemsOptions
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
from dmaker.voice.watermark import delay_on_detector_grid
from tests.conftest import WINDOWS_LINE_LIMIT, command_line_length
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

    def __init__(self, tmp_path: Path, words: list[Word] = WORDS, duration: float = 40.0):
        self.base = Harness(tmp_path, duration=duration, words=words)
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

        def on_run(command: FFmpegCommand) -> None:
            self.commands.append(command)
            record(command)
            if command.label == "trilhas":  # o runner gravado não cria arquivos: as três trilhas saem vazias
                folder = Path(command.args[-1]).parent
                for arg in command.args:
                    if arg.endswith(".wav") and Path(arg).parent == folder:
                        Path(arg).write_bytes(b"RIFF")

        self.base.runner.on_run = on_run
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


LONG_SENTENCES = 150  # passa das 64 falas por comando: a mixagem e as trilhas montam em blocos


@pytest.fixture
def long_dub(tmp_path: Path) -> DubHarness:
    """Uma dublagem de 150 frases, uma a cada 6 s, num arquivo de 15 minutos."""
    words = [
        word
        for index in range(LONG_SENTENCES)
        for word in sentence(f"Frase {index} da dublagem longa de teste.", 2.0 + index * 6.0)
    ]
    return DubHarness(tmp_path, words=words, duration=LONG_SENTENCES * 6.0 + 40.0)


def block_commands(dub: DubHarness) -> list[FFmpegCommand]:
    return [c for c in dub.commands if c.label.startswith("dublagem, bloco")]


def leftover_workspaces(tmp_path: Path) -> list[Path]:
    return list((tmp_path / "speech" / "dub").glob("montagem-*"))


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


def test_a_long_dubbing_premixes_the_clips_in_blocks_and_every_command_fits_the_windows_line(
    long_dub: DubHarness, tmp_path: Path
):
    project = long_dub.prepare()
    assert len(project.segments) == LONG_SENTENCES
    long_dub.service.render(load_dub_project(long_dub.project_path), long_dub.out)
    assert len(block_commands(long_dub)) == 3  # 150 falas em blocos de 50
    assert max(command_line_length(c.args) for c in long_dub.commands) < WINDOWS_LINE_LIMIT
    (mix,) = long_dub.mix_commands()
    assert mix.args.count("-i") == 5  # o vídeo, o fundo e os 3 blocos no lugar das 150 falas
    assert "amix=inputs=4:duration=first:normalize=0" in long_dub.graph()  # o fundo e os 3 blocos
    assert leftover_workspaces(tmp_path) == []


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


# ---------- trilhas separadas ----------


def test_export_stems_writes_the_three_tracks_next_to_the_dubbing(
    dub: DubHarness, monkeypatch, tmp_path: Path
):
    monkeypatch.setattr("dmaker.config.OUTPUT_DIR", tmp_path / "out")
    stems = dub.service.export_stems(dub.prepare())
    folder = tmp_path / "out" / "dublagem" / "entrevista.en.trilhas"
    assert stems.folder == folder
    assert [p.name for p in stems.files] == ["voz-dublada.wav", "fundo.wav", "voz-original.wav"]
    assert all(p.parent == folder and p.exists() for p in stems.files)
    assert stems.duration == 40.0 and stems.zip_path is None and stems.original_voice_db is None


def test_export_stems_runs_one_command_with_the_clips_of_the_render(dub: DubHarness):
    project = dub.prepare()
    dub.service.export_stems(project, StemsOptions(out_dir=dub.out.parent / "trilhas"))
    (command,) = dub.labeled("trilhas")
    assert not dub.mix_commands()  # o vídeo não é remontado
    graph_file = next(Path(arg) for arg in command.args if arg.endswith(".graph.txt"))
    graph = graph_file.read_text(encoding="utf-8")
    assert "adelay=delays=2000:all=1" in graph and "adelay=delays=14000:all=1" in graph
    assert "amix=inputs=3:duration=longest" in graph  # só as 3 falas dubladas
    assert command.total == 40.0


def test_the_stems_of_a_long_dubbing_premix_the_clips_in_blocks_too(long_dub: DubHarness, tmp_path: Path):
    long_dub.service.export_stems(long_dub.prepare(), StemsOptions(out_dir=tmp_path / "trilhas"))
    assert len(block_commands(long_dub)) == 3
    (command,) = long_dub.labeled("trilhas")
    assert max(command_line_length(c.args) for c in long_dub.commands) < WINDOWS_LINE_LIMIT
    graph = next(Path(a) for a in command.args if a.endswith(".graph.txt")).read_text(encoding="utf-8")
    assert "amix=inputs=3:duration=longest:normalize=0" in graph  # os 3 blocos, não as 150 falas
    assert leftover_workspaces(tmp_path) == []


def test_export_stems_reuses_the_speech_already_synthesized_by_the_render(dub: DubHarness):
    project = dub.prepare()
    dub.service.render(project, dub.out)
    synthesized = len(dub.synthesizer.requests)
    dub.service.export_stems(project, StemsOptions(out_dir=dub.out.parent / "trilhas"))
    assert len(dub.synthesizer.requests) == synthesized  # nada foi sintetizado de novo
    assert dub.base.isolation.calls.count((None, None)) >= 2  # o isolamento é o mesmo (cache)


def test_export_stems_synthesizes_only_what_is_missing_from_the_cache(dub: DubHarness):
    project = dub.prepare()
    dub.service.export_stems(project, StemsOptions(out_dir=dub.out.parent / "trilhas"))
    assert len(dub.synthesizer.requests) == 3
    dub.service.export_stems(
        project.edited("s2", text="Pick the right song."), StemsOptions(out_dir=dub.out.parent / "trilhas")
    )
    assert len(dub.synthesizer.requests) == 4


def test_export_stems_can_zip_the_three_tracks_next_to_the_folder(dub: DubHarness):
    import zipfile

    folder = dub.out.parent / "trilhas-casamento"
    stems = dub.service.export_stems(dub.prepare(), StemsOptions(out_dir=folder, make_zip=True))
    assert stems.zip_path == dub.out.parent / "trilhas-casamento.zip"
    with zipfile.ZipFile(stems.zip_path) as archive:
        assert archive.namelist() == ["voz-dublada.wav", "fundo.wav", "voz-original.wav"]


def test_export_stems_tells_the_attenuation_the_video_uses_for_the_original_voice(dub: DubHarness):
    project = dub.prepare(keep_original_db=-18.0)
    stems = dub.service.export_stems(project, StemsOptions(out_dir=dub.out.parent / "trilhas"))
    assert stems.original_voice_db == -18.0
    (command,) = dub.labeled("trilhas")
    graph = next(Path(a) for a in command.args if a.endswith(".graph.txt")).read_text(encoding="utf-8")
    assert "-18" not in graph  # a trilha da voz original sai sem atenuar


def test_export_stems_reports_progress_and_refuses_bad_projects(dub: DubHarness, tmp_path: Path):
    project = dub.prepare()
    labels: list[str] = []
    dub.service.export_stems(
        project,
        StemsOptions(out_dir=dub.out.parent / "t"),
        on_progress=lambda label, _f: labels.append(label),
    )
    assert "Sintetizando a fala 2 de 3" in labels and labels[-1] == "Trilhas prontas"
    blank = project.model_copy(
        update={"segments": [s.model_copy(update={"text": ""}) for s in project.segments]}
    )
    with pytest.raises(ValueError, match="Nenhuma fala está traduzida"):
        dub.service.export_stems(blank)
    gone = project.model_copy(update={"source": str(tmp_path / "sumiu.mp4")})
    with pytest.raises(FileNotFoundError, match="origem"):
        dub.service.export_stems(gone)


def test_render_with_stems_exports_them_from_the_same_speech(dub: DubHarness):
    result = dub.service.render(
        dub.prepare(), dub.out, stems=StemsOptions(out_dir=dub.out.parent / "trilhas", make_zip=True)
    )
    assert result.stems is not None and result.stems.zip_path is not None
    assert len(dub.synthesizer.requests) == 3 and len(dub.mix_commands()) == 1
    assert "Trilhas separadas" in result.timings
    assert dub.service.render(load_dub_project(dub.project_path), dub.out).stems is None


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


# ---------- quando a fala não cabe: esticar o vídeo ----------


def text_taking(seconds: float, source_text: str = S1, source_seconds: float = 3.62) -> str:
    """Uma tradução que, no ritmo do falante original, leva cerca de `seconds` (a fala sintética dura isso)."""
    from dmaker.voice.dub_plan import natural_seconds

    letters = 1
    while natural_seconds(source_text, "a" * letters, source_seconds, "pt", "en") < seconds:
        letters += 1
    return "a" * letters


def srt_starts(srt: str) -> list[float]:
    import re

    def seconds(stamp: str) -> float:
        h, m, rest = stamp.split(":")
        return int(h) * 3600 + int(m) * 60 + float(rest.replace(",", "."))

    return [seconds(m.group(1)) for m in re.finditer(r"(\d\d:\d\d:\d\d,\d\d\d) -->", srt)]


def stretched_project(dub: DubHarness, mode: str, seconds: float = 5.5) -> DubProject:
    """O projeto no `mode` com a primeira fala traduzida num texto que leva `seconds` e não cabe nos 4,8 s dela."""
    project = dub.prepare(fit_mode=mode)
    return project.edited("s1", text=text_taking(seconds))


def test_the_default_fit_mode_is_the_voice_and_a_new_project_keeps_the_choice(dub: DubHarness):
    assert dub.prepare().fit_mode == "voz"
    chosen = dub.prepare(fit_mode="video")
    assert chosen.fit_mode == "video"
    assert load_dub_project(dub.project_path).fit_mode == "video"
    assert project_summary(chosen, dub.project_path)["fit_mode"] == "video"


def test_an_old_project_without_the_field_loads_as_voice_mode():
    data = {"source": "a.mp4", "target_language": "en", "segments": []}
    assert DubProject.model_validate(data).fit_mode == "voz"


def test_video_mode_stretches_only_the_speech_that_did_not_fit_and_keeps_the_voice_natural(dub: DubHarness):
    project = stretched_project(dub, "video")
    result = dub.service.render(project, dub.out)
    first, second, third = result.report
    assert first.status == "stretched" and 1.0 < first.stretch <= 1.3 and not first.warns
    assert first.tempo == 1.0 and first.played_seconds == pytest.approx(first.speech_seconds)
    assert first.requested_seconds == pytest.approx(first.natural_seconds)  # o modelo fala no ritmo natural
    assert (second.stretch, third.stretch) == (1.0, 1.0)  # as que couberam não esticam
    assert result.stretched == [first] and result.warnings == []
    assert result.fit_mode == "video"
    assert "vídeo esticado" in first.message and f"{first.stretch:.2f}x" in first.message


def test_video_mode_recodes_the_picture_and_the_output_lasts_the_plan_total(dub: DubHarness):
    result = dub.service.render(stretched_project(dub, "video"), dub.out)
    (command,) = dub.mix_commands()
    args = command.args
    assert args[args.index("-c:v") + 1] == "libx264"
    added = result.report[0].added_seconds
    assert added > 0.3
    assert command.total == pytest.approx(40.0 + added, abs=1 / 30)
    assert result.output_seconds == pytest.approx(command.total)
    graph = dub.graph()
    assert f"setpts=(PTS-STARTPTS)*{result.report[0].stretch:.6f}" in graph and "concat=n=3:v=1:a=0" in graph
    assert "atempo=" in graph  # só o fundo acompanha o vídeo...
    first_clip_chain = next(line for line in graph.split(";") if line.endswith("[dub0]"))
    assert "atempo" not in first_clip_chain  # ...a voz dublada toca na velocidade dela


def test_the_following_speeches_and_the_subtitles_move_by_what_the_picture_grew(dub: DubHarness):
    project = stretched_project(dub, "video")
    plain = dub.service.render(project.model_copy(update={"fit_mode": "voz"}), dub.out)
    plain_starts = srt_starts(plain.srt_path.read_text(encoding="utf-8"))
    result = dub.service.render(project, dub.out)
    added = result.report[0].added_seconds
    starts = srt_starts(result.srt_path.read_text(encoding="utf-8"))
    assert starts[0] == pytest.approx(2.0)  # antes do esticado nada se move
    assert starts[-2:] == pytest.approx([s + added for s in plain_starts[-2:]], abs=1 / 30 + 0.002)
    assert [r.retimed_start for r in result.report[1:]] == pytest.approx(
        [r.start + added for r in result.report[1:]], abs=1 / 30 + 0.002
    )
    graph = dub.graph()
    for report in result.report[1:]:
        assert f"adelay=delays={delay_on_detector_grid(report.retimed_start)}:all=1" in graph


def test_the_voice_mode_is_unchanged_it_squeezes_the_voice_and_never_touches_the_picture(dub: DubHarness):
    result = dub.service.render(stretched_project(dub, "voz"), dub.out)
    first = result.report[0]
    assert first.stretch == 1.0 and first.status in ("squeezed", "advances") and first.tempo >= 1.0
    assert result.stretched == [] and result.output_seconds == pytest.approx(40.0)
    args = dub.mix_commands()[0].args
    assert args[args.index("-c:v") + 1] == "copy"
    assert "[vout]" not in dub.graph()


def test_video_mode_with_every_speech_fitting_copies_the_picture_like_before(dub: DubHarness):
    result = dub.service.render(dub.prepare(fit_mode="video"), dub.out)
    assert result.stretched == [] and [r.status for r in result.report] == ["advances"] * 3
    args = dub.mix_commands()[0].args
    assert args[args.index("-c:v") + 1] == "copy" and "[vout]" not in dub.graph()
    assert result.output_seconds == pytest.approx(40.0)


def test_mixed_mode_accelerates_the_voice_up_to_the_cap_and_stretches_the_rest(dub: DubHarness):
    result = dub.service.render(stretched_project(dub, "misto", seconds=6.6), dub.out)
    first = result.report[0]
    assert first.status == "stretched" and first.tempo == pytest.approx(1.15)
    assert 1.0 < first.stretch <= 1.3 and first.message.startswith("acelerada 1.15x e vídeo esticado")
    chain = next(line for line in dub.graph().split(";") if line.endswith("[dub0]"))
    assert "atempo" not in chain  # a aceleração é da fala, feita antes da marca d'água
    (speed_up,) = dub.labeled("acabamento da fala")
    assert speed_up.args[speed_up.args.index("-af") + 1] == "atempo=1.150000"


def test_a_mild_excess_in_mixed_mode_is_solved_by_the_voice_alone(dub: DubHarness):
    result = dub.service.render(stretched_project(dub, "misto", seconds=5.4), dub.out)
    assert result.report[0].status == "squeezed" and result.report[0].stretch == 1.0
    assert result.stretched == []


def test_beyond_the_limit_the_picture_stops_at_one_point_three_and_the_report_warns(dub: DubHarness):
    result = dub.service.render(stretched_project(dub, "video", seconds=9.0), dub.out)
    first = result.report[0]
    assert first.status == "overflow" and first.warns and first.stretch == 1.3
    assert result.warnings and "Fala s1" in result.warnings[0] and "encurte a tradução" in result.warnings[0]
    assert "atrim=duration=" in dub.graph() and "afade=t=out" in dub.graph()
    assert result.stretched == [first]


def test_switching_the_mode_does_not_synthesize_again_what_is_in_the_cache(dub: DubHarness):
    project = dub.prepare()
    dub.service.render(project, dub.out)
    requests = len(dub.synthesizer.requests)
    again = dub.service.render(project.model_copy(update={"fit_mode": "video"}), dub.out)
    assert len(dub.synthesizer.requests) == requests  # fits e advances pedem a duração natural nos dois modos
    assert again.regenerated == 0 and all(r.cached for r in again.report)


def test_audio_without_picture_has_nothing_to_stretch_and_falls_back_to_the_voice_mode(tmp_path: Path):
    audio = DubHarness(tmp_path)
    audio.base.src.rename(tmp_path / "radio.wav")
    audio.src = tmp_path / "radio.wav"
    prober = lambda path: __import__("tests.test_speech_fix", fromlist=["video_info"]).video_info(  # noqa: E731
        path, 40.0, has_video=False
    )
    audio.base.service.prober = audio.service.prober = prober
    project = audio.service.prepare(
        audio.src, "en", project_path=tmp_path / "radio.en.dub.json", fit_mode="video"
    ).edited("s1", text=text_taking(5.5))
    logged: list[str] = []
    audio.service.log = logged.append
    result = audio.service.render(project, tmp_path / "radio.en.m4a")
    assert (
        result.fit_mode == "voz" and result.stretched == [] and result.output_seconds == pytest.approx(40.0)
    )
    assert any("Sem vídeo para esticar" in line for line in logged)
    assert "[vout]" not in audio.graph()


def test_the_original_voice_stem_is_stretched_along_with_the_background(dub: DubHarness):
    project = stretched_project(dub, "video").model_copy(update={"keep_original_db": -18.0})
    dub.service.render(project, dub.out)
    graph = dub.graph()
    assert "[backgroundfull]asplit=" in graph and "[originalfull]asplit=" in graph
    assert "volume=-18.0dB" in graph


def test_the_result_dictionary_lists_the_stretched_speeches_and_the_final_length(dub: DubHarness):
    from dmaker.pipeline.dubbing import report_dict, result_dict

    result = dub.service.render(stretched_project(dub, "video"), dub.out)
    summary = result_dict(result)
    assert summary["fit_mode"] == "video" and summary["output_seconds"] > 40.0
    assert [item["id"] for item in summary["stretched"]] == ["s1"]
    assert summary["stretched"][0]["factor"] == pytest.approx(result.report[0].stretch, abs=1e-3)
    assert summary["stretched"][0]["added_seconds"] > 0
    row = report_dict(result.report[0])
    assert row["video_stretch"] > 1.0 and row["retimed_start"] == pytest.approx(2.0)


def test_stems_of_a_stretched_video_follow_the_new_timeline_like_the_dubbed_file(dub: DubHarness):
    """As trilhas separadas somam de volta o arquivo dublado: com o vídeo esticado, o fundo, a voz original e as
    falas acompanham a linha do tempo nova e a duração das trilhas é a do arquivo esticado."""
    project = stretched_project(dub, "video")
    result = dub.service.render(project, dub.out, stems=StemsOptions(out_dir=dub.out.parent / "trilhas"))

    assert result.output_seconds > 40.0
    assert result.stems is not None and result.stems.duration == pytest.approx(result.output_seconds)
    (command,) = dub.labeled("trilhas")
    assert command.total == pytest.approx(result.output_seconds)
    graph = next(Path(a) for a in command.args if a.endswith(".graph.txt")).read_text(encoding="utf-8")
    assert "[backgroundfull]asplit=" in graph and "[originalfull]asplit=" in graph
    start_after_stretch = result.report[1].retimed_start
    assert start_after_stretch is not None and start_after_stretch > result.report[1].start
    assert (
        f"adelay=delays={delay_on_detector_grid(start_after_stretch)}:all=1" in graph
    )  # a fala seguinte foi empurrada


def test_stems_without_stretching_keep_the_original_timeline(dub: DubHarness):
    result = dub.service.render(
        dub.prepare(), dub.out, stems=StemsOptions(out_dir=dub.out.parent / "trilhas")
    )
    (command,) = dub.labeled("trilhas")
    graph = next(Path(a) for a in command.args if a.endswith(".graph.txt")).read_text(encoding="utf-8")
    assert "full]" not in graph and result.stems is not None and result.stems.duration == 40.0
