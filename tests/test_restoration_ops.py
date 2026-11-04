"""As operações de limpeza do `edit_project`: o perfil de ruído e o Truncar Silêncio, sem ffmpeg.

O som vem de um leitor de amostras falso (tons com pausas de duração conhecida), então a conta esperada de cada corte
sai de aritmética. A prova com ffmpeg de verdade (imagem e som no mesmo instante depois do corte) está em
`test_audio_restoration_integration.py`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

from dmaker.domain.audio_effects import chain_duration
from dmaker.domain.edits import EditError
from dmaker.domain.spec import ClipSegment, Project
from dmaker.media.probe import MediaInfo
from dmaker.pipeline.edit_history import edit_label
from dmaker.pipeline.edits import apply_edit_report
from dmaker.pipeline.sample_reader import AudioSlice

DURATIONS = {"video.mp4": 10.0, "fala.wav": 6.0, "rua.wav": 8.0}


def prober(path: Path) -> MediaInfo:
    video = path.suffix == ".mp4"
    return MediaInfo(
        path, DURATIONS.get(path.name, 5.0), 1280 if video else 0, 720 if video else 0, 30.0, video, True, False
    )


def tone_with_gaps(*gaps: tuple[float, float], hiss: float = 0.0) -> Callable[[np.ndarray], np.ndarray]:
    """Um tom de 440 Hz (amplitude 0,3) calado nas pausas `gaps` (segundos do arquivo), com um chiado opcional."""

    def make(t: np.ndarray) -> np.ndarray:
        signal = 0.3 * np.sin(2 * np.pi * 440 * t)
        quiet = np.zeros(len(t), dtype=bool)
        for start, end in gaps:
            quiet |= (t >= start) & (t < end)
        noise = np.random.default_rng(1).standard_normal(len(t)) * hiss
        return np.where(quiet, noise, signal)

    return make


class FakeReader:
    """Lê arquivos sintéticos: cada nome de arquivo tem uma função do tempo (segundos) dele."""

    def __init__(self, signals: dict[str, Callable[[np.ndarray], np.ndarray]]) -> None:
        self.signals = signals
        self.reads: list[AudioSlice] = []

    def read(self, audio: AudioSlice, *, rate: int, channels: int) -> np.ndarray:
        self.reads.append(audio)
        t = audio.start + np.arange(round(audio.duration * rate)) / rate
        mono = self.signals[audio.path.name](t).astype(np.float32)
        return np.repeat(mono[:, None], channels, axis=1)


@pytest.fixture
def folder(tmp_path) -> Path:
    for name in DURATIONS:
        (tmp_path / name).write_bytes(b"\x00" * 16)
    return tmp_path


def make(folder: Path, **parts) -> Project:
    data = {
        "name": "limpeza",
        "timeline": [{"type": "clip", "src": "video.mp4", "start": 0, "end": 10}],
        **parts,
    }
    project = Project.model_validate(data)
    project.base_dir = folder
    return project


SIGNALS = {
    "video.mp4": tone_with_gaps((3.0, 5.0), (8.0, 10.0)),
    "fala.wav": tone_with_gaps((2.0, 4.0)),
    "rua.wav": tone_with_gaps((0.0, 1.0), hiss=0.003),
}


def edit(project: Project, **op):
    return apply_edit_report(project, op, prober=prober, sample_reader=FakeReader(SIGNALS))


# ---------- perfil de ruído ----------


def test_a_profile_stores_the_target_and_the_interval_in_item_time(folder):
    project = make(folder, audio={"voiceover": [{"src": "rua.wav", "start": 3.0, "offset": 1.0}]})
    report = edit(project, type="noise_profile_set", name="sala", target="audio.voiceover.0", start=3.0, end=3.5)
    profile = report.project.audio.noise_profiles["sala"]
    assert (profile.target, profile.start, profile.end) == ("audio.voiceover.0", 0.0, 0.5)  # o tempo é o do item
    assert project.audio.noise_profiles == {}  # a spec original não muda


def test_a_profile_interval_accepts_markers_and_is_refused_when_too_short_to_measure(folder):
    project = make(
        folder,
        audio={"voiceover": [{"src": "rua.wav"}]},
        markers=[{"at": 0.5, "text": "início"}, {"at": 1.5, "text": "fim"}, {"at": 0.55, "text": "perto"}],
    )
    report = edit(project, type="noise_profile_set", name="p", target="audio.voiceover.0", start="marker:início", end="marker:fim")
    assert (report.project.audio.noise_profiles["p"].start, report.project.audio.noise_profiles["p"].end) == (0.5, 1.5)
    with pytest.raises(EditError, match="use pelo menos 0.1 s só de ruído"):
        edit(project, type="noise_profile_set", name="p", target="audio.voiceover.0", start="marker:início", end="marker:perto")


def test_without_an_interval_the_profile_is_the_quietest_stretch_of_the_item(folder):
    project = make(folder, audio={"voiceover": [{"src": "rua.wav"}]})
    report = edit(project, type="noise_profile_set", name="chiado", target="audio.voiceover.0")
    profile = report.project.audio.noise_profiles["chiado"]
    assert 0.0 <= profile.start and profile.end == pytest.approx(profile.start + 0.5, abs=0.01)
    assert profile.end <= 1.0 + 0.01  # dentro da pausa de 0 a 1 s, onde só há o chiado


def test_the_name_auto_is_reserved_and_the_narration_and_the_mix_have_nothing_to_measure(folder):
    project = make(folder, audio={"voiceover": [{"src": "rua.wav"}], "narration": [{"text": "oi"}]})
    with pytest.raises(EditError, match="perfil automático"):
        edit(project, type="noise_profile_set", name="auto", target="audio.voiceover.0", start=0, end=1)
    with pytest.raises(EditError, match="sintetizada"):
        edit(project, type="noise_profile_set", name="p", target="audio.narration.0", start=0, end=1)
    with pytest.raises(EditError, match="não é um arquivo"):
        edit(project, type="noise_profile_set", name="p", target="audio.master", start=0, end=1)


def test_a_profile_can_be_removed_but_not_while_a_noise_reduction_still_uses_it(folder):
    project = make(
        folder,
        audio={
            "voiceover": [{"src": "rua.wav", "effects": [{"type": "noise_reduction", "profile": "sala"}]}],
            "noise_profiles": {"sala": {"target": "audio.voiceover.0", "start": 0, "end": 1}},
        },
    )
    with pytest.raises(EditError, match="é usado por 1 efeito"):
        edit(project, type="noise_profile_remove", name="sala")
    free = make(folder, audio={"noise_profiles": {"sala": {"target": "audio.voiceover.0", "start": 0, "end": 1}}})
    assert edit(free, type="noise_profile_remove", name="sala").project.audio.noise_profiles == {}
    with pytest.raises(EditError, match="não há o perfil"):
        edit(free, type="noise_profile_remove", name="outro")


def test_the_history_names_the_new_steps():
    assert edit_label({"type": "noise_profile_set", "name": "sala", "target": "timeline.0"}).startswith("Perfil de ruído name=sala")
    assert edit_label({"type": "audio_truncate_silence", "target": "timeline.0"}).startswith("Truncar silêncio target=timeline.0")


# ---------- Truncar Silêncio na voz gravada ----------


def test_truncating_the_voice_cuts_the_middle_of_the_pause_and_the_item_shrinks_by_the_expected_amount(folder):
    project = make(folder, audio={"voiceover": [{"src": "fala.wav", "start": 1.0}, {"src": "fala.wav", "start": 8.0}]})
    report = edit(project, type="audio_truncate_silence", target="audio.voiceover.0")
    first = report.project.audio.voiceover[0]
    ((cut,),) = [[effect for effect in first.effects if effect.type == "cut"]]
    assert cut.keep_length is False
    assert cut.end - cut.start == pytest.approx(1.5, abs=0.01)  # a pausa de 2 s fica com 0,5 s
    assert chain_duration(first.effects, 6.0) == pytest.approx(4.5, abs=0.01)
    assert report.project.audio.voiceover[1].start == pytest.approx(6.5, abs=0.01)  # a voz seguinte recuou o que saiu
    assert any("1 silêncio(s) truncado(s)" in note for note in report.notes)
    assert report.time_map.is_identity  # a imagem não mexe: os marcadores ficam


def test_several_pauses_become_one_cut_each_starting_from_the_last_so_the_earlier_times_stay_valid(folder):
    signals = dict(SIGNALS, **{"fala.wav": tone_with_gaps((1.0, 2.5), (3.5, 5.5))})
    project = make(folder, audio={"voiceover": [{"src": "fala.wav"}]})
    report = apply_edit_report(
        project, {"type": "audio_truncate_silence", "target": "audio.voiceover.0"}, prober=prober, sample_reader=FakeReader(signals)
    )
    cuts = [effect for effect in report.project.audio.voiceover[0].effects if effect.type == "cut"]
    # pausas de 1,5 s e de 2 s: saem 1 s (de 1,25 a 2,25) e 1,5 s (de 3,75 a 5,25), do último para o primeiro
    assert [cut.start for cut in cuts] == pytest.approx([3.75, 1.25], abs=0.02)
    assert chain_duration(report.project.audio.voiceover[0].effects, 6.0) == pytest.approx(6.0 - 1.0 - 1.5, abs=0.02)


def test_the_compress_mode_keeps_the_minimum_plus_a_share_of_the_excess(folder):
    project = make(folder, audio={"voiceover": [{"src": "fala.wav"}]})
    report = edit(project, type="audio_truncate_silence", target="audio.voiceover.0", mode="compress", compress_percent=50)
    # 2 s de pausa: fica 0,5 + 0,5 * 1,5 = 1,25 s, saem 0,75 s
    assert chain_duration(report.project.audio.voiceover[0].effects, 6.0) == pytest.approx(5.25, abs=0.01)


def test_a_selection_limits_the_search_to_that_stretch(folder):
    signals = dict(SIGNALS, **{"fala.wav": tone_with_gaps((0.5, 1.5), (3.0, 5.0))})
    project = make(folder, audio={"voiceover": [{"src": "fala.wav"}]})
    report = apply_edit_report(
        project,
        {"type": "audio_truncate_silence", "target": "audio.voiceover.0", "start": 2.0, "end": 6.0},
        prober=prober,
        sample_reader=FakeReader(signals),
    )
    cut = next(effect for effect in report.project.audio.voiceover[0].effects if effect.type == "cut")
    assert 3.0 < cut.start < cut.end < 5.0  # só a pausa de dentro da seleção


# ---------- Truncar Silêncio no clipe ----------


def test_truncating_a_clip_cuts_image_and_sound_together_into_clips_that_skip_the_pauses(folder):
    project = make(folder, markers=[{"at": 2.0, "text": "antes"}, {"at": 6.5, "text": "depois"}, {"at": 4.0, "text": "dentro"}])
    report = edit(project, type="audio_truncate_silence", target="timeline.0")
    clips = [segment for segment in report.project.timeline if isinstance(segment, ClipSegment)]
    # pausas em 3 a 5 s e 8 a 10 s: ficam 0 a ~3,27 (grade de quadros), ~4,75 a ~8,27 e ~9,75 a 10
    assert len(clips) == 3
    assert clips[0].start == 0 and clips[0].end == pytest.approx(3.2667, abs=0.01)
    assert clips[1].start == pytest.approx(4.75, abs=0.03) and clips[1].end == pytest.approx(8.2667, abs=0.1)
    assert clips[2].end == 10 and clips[2].start == pytest.approx(9.75, abs=0.03)
    assert all(clip.audio_fade >= 0.01 for clip in clips)  # o fade tira o estalo da emenda
    kept = sum(clip.end - clip.start for clip in clips)  # type: ignore[operator]
    assert kept == pytest.approx(10.0 - 1.5 - 1.5, abs=0.07)  # duas pausas de 2 s viram 0,5 s: saem 1,5 s de cada
    # os marcadores: antes do corte fica, depois dele recua o que saiu, dentro do trecho cortado some com aviso
    positions = {marker.text: marker.at for marker in report.project.markers}
    assert positions["antes"] == 2.0
    assert positions["depois"] == pytest.approx(6.5 - 1.48, abs=0.05)
    assert "dentro" not in positions and any("dentro" in warning for warning in report.warnings)
    assert report.notes and "2 silêncio(s) truncado(s)" in report.notes[0]


def test_the_cut_on_a_sped_up_clip_is_made_in_timeline_seconds(folder):
    project = make(folder, timeline=[{"type": "clip", "src": "video.mp4", "start": 0, "end": 10, "speed": 2}])
    report = edit(project, type="audio_truncate_silence", target="timeline.0")
    kept = sum(clip.end - clip.start for clip in report.project.timeline)  # type: ignore[operator]
    assert kept == pytest.approx(10.0 - 3.0, abs=0.15)  # em segundos de fonte
    assert len(report.project.timeline) == 3


def test_the_pieces_of_a_clip_keep_the_same_gravacao_so_the_mouth_stays_in_sync(folder):
    project = make(folder, timeline=[{"type": "clip", "src": "video.mp4", "start": 0, "end": 10, "volume": 0.8}])
    report = edit(project, type="audio_truncate_silence", target="timeline.0")
    assert {segment.src for segment in report.project.timeline} == {"video.mp4"}  # type: ignore[union-attr]
    assert {segment.volume for segment in report.project.timeline} == {0.8}  # type: ignore[union-attr]


# ---------- recusas ----------


def test_nothing_to_truncate_is_an_error_that_says_what_to_try_and_leaves_no_history_step(folder):
    project = make(folder, audio={"voiceover": [{"src": "fala.wav"}]})
    with pytest.raises(EditError, match="nenhum silêncio de pelo menos 3 s"):
        edit(project, type="audio_truncate_silence", target="audio.voiceover.0", min_duration=3)


@pytest.mark.parametrize(
    ("target", "motive"),
    [
        ("overlays.0", "presa à imagem"),
        ("audio.narration.0", "sintetizada"),
        ("audio.tracks.0", "segue a sessão"),
        ("audio.master", "mistura inteira"),
        ("audio.music", "não tem pausas"),
    ],
)
def test_items_that_cannot_shrink_say_why(folder, target, motive):
    project = make(
        folder,
        sources={"mesa": {"src": "rua.wav"}},
        overlays=[{"type": "video", "src": "video.mp4"}],
        audio={
            "narration": [{"text": "oi"}],
            "tracks": [{"source": "mesa"}],
            "music": {"src": "rua.wav"},
        },
    )
    with pytest.raises(EditError, match=motive):
        edit(project, type="audio_truncate_silence", target=target)


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"threshold_db": -10}, "`threshold_db` precisa ser um número de -80 a -20"),
        ({"min_duration": 0}, "`min_duration` precisa ser um número"),
        ({"compress_percent": 150}, "`compress_percent` precisa ser um número de 0 a 100"),
        ({"mode": "apagar"}, "`mode` desconhecido"),
    ],
)
def test_parameters_outside_the_audacity_ranges_are_refused_with_the_range(folder, extra, message):
    project = make(folder, audio={"voiceover": [{"src": "fala.wav"}]})
    with pytest.raises(EditError, match=message):
        edit(project, type="audio_truncate_silence", target="audio.voiceover.0", **extra)
