"""Biblioteca de vozes: clone, design, filtro por marca, erros e remoção."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dmaker.media.ffmpeg import RecordingRunner
from dmaker.media.wavio import wav_duration, write_wav
from dmaker.text.captions import Cue
from dmaker.text.transcribe import Transcript
from dmaker.voice.library import VoiceLibrary, VoiceNotFoundError, VoiceProfile, slugify


class FakeTranscriber:
    def __init__(self, text: str = "Olá, esta é a minha voz."):
        self.text = text
        self.calls: list[Path] = []

    def transcribe(self, wav: Path, language: str, initial_prompt: str | None = None) -> Transcript:
        self.calls.append(wav)
        return Transcript([Cue(0.0, 2.0, self.text)])


def _runner_writing_output(seconds: float = 3.0) -> RecordingRunner:
    """Runner que grava, no lugar do ffmpeg, uma referência de tom com a duração pedida."""

    def on_run(command):
        samples = np.sin(np.arange(int(seconds * 24000)) * 0.1).astype(np.float32) * 0.3
        write_wav(Path(command.args[-1]), samples, 24000)

    return RecordingRunner(on_run=on_run)


@pytest.fixture
def source(tmp_path) -> Path:
    path = tmp_path / "gravacao.m4a"
    path.write_bytes(b"x")
    return path


def test_slugify_removes_accents_and_symbols():
    assert slugify("Voz da Ana Júlia!") == "voz-da-ana-julia"
    with pytest.raises(ValueError):
        slugify("???")


def test_save_clone_converts_reference_and_transcribes(tmp_path, source):
    library = VoiceLibrary(tmp_path / "voices")
    runner = _runner_writing_output()
    transcriber = FakeTranscriber()

    profile = library.save_clone("Ana Júlia", source, runner, transcriber, brand="medlycare")

    assert profile.id == "ana-julia" and profile.kind == "clone" and profile.brand == "medlycare"
    assert profile.reference_text == "Olá, esta é a minha voz."
    command = runner.commands[0]
    assert str(source) in command and command[-1].endswith("reference.wav")
    assert command[command.index("-ac") + 1] == "1" and command[command.index("-ar") + 1] == "24000"
    graph = command[command.index("-af") + 1]
    assert "silenceremove" in graph and "areverse" in graph and "atrim" not in graph
    assert command[command.index("-t") + 1] == "120"  # teto de 8 janelas de 15 s
    assert (tmp_path / "voices" / "ana-julia" / "voice.json").exists()
    assert transcriber.calls == [tmp_path / "voices" / "ana-julia" / "reference.wav"]
    assert profile.reference_path == tmp_path / "voices" / "ana-julia" / "reference.wav"


def test_save_clone_with_given_text_skips_transcription(tmp_path, source):
    library = VoiceLibrary(tmp_path)
    transcriber = FakeTranscriber()
    profile = library.save_clone(
        "Teste", source, _runner_writing_output(), transcriber, reference_text="  texto dado  "
    )
    assert profile.reference_text == "texto dado" and transcriber.calls == []


def test_save_clone_failure_leaves_no_half_voice(tmp_path, source):
    library = VoiceLibrary(tmp_path)

    def failing(command):
        raise RuntimeError("ffmpeg quebrou")

    with pytest.raises(RuntimeError):
        library.save_clone("Quebrada", source, RecordingRunner(on_run=failing), None)
    assert library.list(presets=False) == [] and not (tmp_path / "quebrada").exists()


def test_save_clone_missing_reference_and_duplicate_name(tmp_path, source):
    library = VoiceLibrary(tmp_path)
    with pytest.raises(FileNotFoundError):
        library.save_clone("X", tmp_path / "nao-existe.wav", RecordingRunner(), None)
    library.save_clone("Igual", source, _runner_writing_output(), None, reference_text="oi")
    with pytest.raises(ValueError, match="Já existe"):
        library.save_clone("Igual", source, _runner_writing_output(), None, reference_text="oi")


def test_save_design_and_roundtrip(tmp_path):
    library = VoiceLibrary(tmp_path)
    saved = library.save_design("Locutor Grave", "male, low pitch", brand="medlycare")
    loaded = library.get("locutor-grave")
    assert loaded.kind == "design" and loaded.instruct == "male, low pitch" and loaded.reference is None
    assert loaded.model_dump(exclude={"folder"}) == saved.model_dump(exclude={"folder"})
    assert "folder" not in (tmp_path / "locutor-grave" / "voice.json").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        library.save_design("Vazia", "  ")


def test_list_by_brand_includes_unbranded_voices(tmp_path):
    library = VoiceLibrary(tmp_path)
    library.save_design("Medly", "female", brand="medlycare")
    library.save_design("Outra", "male", brand="pascom")
    library.save_design("Geral", "male, elderly")
    assert [v.id for v in library.list(presets=False)] == ["geral", "medly", "outra"]
    assert [v.id for v in library.list(brand="medlycare", presets=False)] == ["geral", "medly"]
    assert [v.id for v in library.list(brand="medlycare")] == ["dora", "alex", "santa", "geral", "medly"]


def test_list_of_missing_root_has_only_the_presets(tmp_path):
    library = VoiceLibrary(tmp_path / "nada")
    assert library.list(presets=False) == []
    assert [v.id for v in library.list()] == ["dora", "alex", "santa"]


def test_get_unknown_voice_lists_the_available_ones(tmp_path):
    library = VoiceLibrary(tmp_path)
    library.save_design("Medly", "female")
    with pytest.raises(VoiceNotFoundError) as error:
        library.get("fantasma")
    assert "fantasma" in str(error.value) and "medly" in str(error.value) and "dora" in str(error.value)


def test_remove_deletes_the_folder(tmp_path):
    library = VoiceLibrary(tmp_path)
    library.save_design("Medly", "female")
    library.remove("medly")
    assert not (tmp_path / "medly").exists()
    with pytest.raises(VoiceNotFoundError):
        library.remove("medly")


def test_fingerprint_changes_with_reference_bytes(tmp_path, source):
    library = VoiceLibrary(tmp_path)
    profile = library.save_clone("Ana", source, _runner_writing_output(), None, reference_text="oi")
    before = profile.fingerprint()
    assert before == library.get("ana").fingerprint()
    profile.reference_path.write_bytes(b"outra gravacao")
    assert profile.fingerprint() != before


def test_presets_are_kokoro_voices_with_readable_ids(tmp_path):
    library = VoiceLibrary(tmp_path)
    dora = library.get("dora")
    assert (dora.kind, dora.engine, dora.preset, dora.language) == ("preset", "kokoro", "pf_dora", "pt")
    assert {v.preset for v in library.list() if v.kind == "preset"} == {"pf_dora", "pm_alex", "pm_santa"}
    assert library.get("alex").preset == "pm_alex" and library.get("santa").preset == "pm_santa"


def test_presets_cannot_be_removed_or_shadowed(tmp_path):
    library = VoiceLibrary(tmp_path)
    with pytest.raises(ValueError, match="voz pronta e não pode ser removida"):
        library.remove("dora")
    with pytest.raises(ValueError, match="nome de uma voz pronta"):
        library.save_design("Dora", "female")
    assert not (tmp_path / "dora").exists()


def test_fingerprint_includes_engine_and_preset():
    dora = VoiceProfile(id="x", name="X", kind="preset", engine="kokoro", preset="pf_dora")
    alex = dora.model_copy(update={"preset": "pm_alex"})
    omni = dora.model_copy(update={"engine": "omnivoice"})
    assert len({dora.fingerprint(), alex.fingerprint(), omni.fingerprint()}) == 3


def test_old_voice_json_without_engine_loads_as_omnivoice(tmp_path):
    folder = tmp_path / "antiga"
    folder.mkdir()
    (folder / "voice.json").write_text(
        '{"id": "antiga", "name": "Antiga", "kind": "design", "instruct": "female"}', encoding="utf-8"
    )
    assert VoiceLibrary(tmp_path).get("antiga").engine == "omnivoice"


class WindowTranscriber:
    """Devolve o texto da janela pelo número de chamadas, para escolher qual janela vence."""

    def __init__(self, texts: list[str]):
        self.texts = texts
        self.calls = 0

    def transcribe(self, wav: Path, language: str, initial_prompt: str | None = None) -> Transcript:
        text = self.texts[self.calls]
        self.calls += 1
        return Transcript([Cue(0.0, 1.0, text)] if text else [])


def test_clip_up_to_twenty_seconds_is_kept_whole(tmp_path, source):
    library = VoiceLibrary(tmp_path)
    runner = _runner_writing_output(seconds=19.5)
    profile = library.save_clone("Inteira", source, runner, FakeTranscriber())
    assert wav_duration(profile.reference_path) == pytest.approx(19.5, abs=0.01)


def test_long_clip_keeps_the_fifteen_second_window_with_most_speech(tmp_path, source):
    library = VoiceLibrary(tmp_path)
    transcriber = WindowTranscriber(["", "janela com bastante fala aqui", "pouco"])
    profile = library.save_clone(
        "Longa",
        source,
        _runner_writing_output(seconds=40),
        transcriber,
        reference_text="texto da gravação inteira que não alinha",
    )
    assert transcriber.calls == 3  # 15 s + 15 s + 10 s
    assert profile.reference_text == "janela com bastante fala aqui"
    assert wav_duration(profile.reference_path) == pytest.approx(15.0, abs=0.01)
    assert not list(profile.reference_path.parent.glob(".*janela.wav"))


def test_long_clip_without_transcriber_or_speech_is_a_clear_error(tmp_path, source):
    library = VoiceLibrary(tmp_path)
    with pytest.raises(ValueError, match="transcritor"):
        library.save_clone("SemWhisper", source, _runner_writing_output(seconds=30), None)
    with pytest.raises(ValueError, match="fala"):
        library.save_clone("Muda", source, _runner_writing_output(seconds=30), WindowTranscriber(["", ""]))
    assert library.list(presets=False) == []
