"""A portadora do Vocoder vinda de outra trilha, sem ffmpeg de verdade (DMK-70): os pares aceitos e recusados, o ciclo, a spec que
não muda sem o campo, o grafo da trilha, onde cada tipo de item cai na linha do tempo e o que invalida a chave de cache."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from dmaker.domain.audio_effects import chain_signature, parse_effect
from dmaker.domain.carrier_tracks import PlacedRun, check_carrier_pair, find_cycle
from dmaker.domain.spec import Project
from dmaker.filtergraph.carrier import CarrierPiece, carrier_graph, stretch_filter
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.media.wavio import write_wav_float
from dmaker.pipeline.audio_effects import (
    SILENT_CARRIER_DB,
    AudioItem,
    EffectProcessor,
    processed_music,
    processed_voiceovers,
)
from dmaker.pipeline.carrier_tracks import (
    CarrierInputs,
    CarrierTrack,
    CarrierTracks,
    Deferred,
    uses_carrier_tracks,
    wav_layout,
)
from dmaker.pipeline.context import RenderContext, RenderOptions
from dmaker.pipeline.lint import lint
from dmaker.pipeline.voicefiles import prepare_voice_files
from dmaker.pipeline.voiceover import PreparedVoiceover

from .conftest import fake_ffmpeg_output
from .test_auto_duck_early import builder_for
from .test_pipeline_unit import LOUDNORM_JSON
from .test_preview_audio import make_prober, make_project, pieces

# ---------- os pares e o ciclo (puro) ----------


@pytest.mark.parametrize(
    ("host", "carrier"),
    [
        ("NAR", "MUS"),
        ("VO", "MUS"),
        ("MUS", "NAR"),
        ("A1", "MUS"),
        ("A2", "A1"),
        ("A2", "A3"),
        ("SFX", "A1"),
        ("A1", "VO"),
    ],
)
def test_every_pair_the_auto_duck_accepts_is_accepted(host, carrier):
    assert check_carrier_pair(host, carrier) is None


def test_the_same_track_is_refused_with_what_to_do_and_the_camera_hears_an_external_track():
    same = check_carrier_pair("MUS", "MUS")
    assert same is not None and "MUS" in same and "portadora gerada" in same
    assert check_carrier_pair("A1", "A2") is None and check_carrier_pair("A1", "A3") is None
    assert "desconhecida" in (check_carrier_pair("MUS", "XYZ") or "")


def test_a_cycle_of_two_and_of_three_is_found_and_a_chain_without_one_is_not():
    assert find_cycle([("MUS", "NAR"), ("NAR", "MUS")]) == ["MUS", "NAR", "MUS"]
    three = find_cycle([("A1", "MUS"), ("MUS", "NAR"), ("NAR", "A1")])
    assert three is not None and three[0] == three[-1] and set(three) == {"A1", "MUS", "NAR"}
    assert find_cycle([("VO", "MUS"), ("MUS", "NAR"), ("NAR", "A2")]) is None
    assert find_cycle([("VO", "MUS"), ("NAR", "MUS")]) is None  # duas trilhas ouvindo a mesma não é ciclo
    assert find_cycle([]) is None


def test_the_camera_and_an_external_track_that_hear_each_other_close_a_cycle():
    assert find_cycle([("A1", "A2"), ("A2", "A1")]) == ["A1", "A2", "A1"]


# ---------- a spec ----------

VOCODER_OLD = {
    "type": "vocoder",
    "enabled": True,
    "start": None,
    "end": None,
    "carrier": {
        "generator": "tone",
        "params": {"waveform": "sawtooth", "frequency_hz": 110.0, "amplitude_db": -6.0},
    },
    "bands": 40,
    "distance": 20.0,
    "original_level": 0.0,
    "noise_level": 25.0,
    "radar_level": 0.0,
    "radar_hz": 30.0,
    "output_db": -3.0,
}


def test_a_vocoder_without_a_track_dumps_and_signs_exactly_as_before_the_field_existed():
    effect = parse_effect({"type": "vocoder"})
    assert effect.model_dump(mode="json") == VOCODER_OLD
    assert chain_signature([effect]) == [VOCODER_OLD]
    assert effect.model_dump() == effect.model_dump(mode="python")
    assert parse_effect({"type": "vocoder", "carrier_track": " MUS "}).carrier_track_id() == "MUS"
    assert parse_effect({"type": "tremolo"}).carrier_track_id() is None


def test_the_track_id_must_be_a_timeline_track():
    assert parse_effect({"type": "vocoder", "carrier_track": "A3"}).model_dump()["carrier_track"] == "A3"
    with pytest.raises(ValueError, match="trilha desconhecida"):
        parse_effect({"type": "vocoder", "carrier_track": "guitarra"})


def audio_project(**audio) -> Project:
    return Project.model_validate(
        {
            "name": "p",
            "timeline": [{"type": "clip", "src": "v.mp4", "start": 0, "end": 5}],
            "audio": audio,
        }
    )


def vocoder(track: str | None) -> dict:
    return {"type": "vocoder", **({"carrier_track": track} if track else {})}


def test_the_project_refuses_the_pair_that_does_not_hold_and_says_which_item_and_what_to_do():
    with pytest.raises(ValueError, match=r"audio\.music.*MUS.*portadora gerada"):
        audio_project(music={"src": "m.mp3", "effects": [vocoder("MUS")]})
    camera = Project.model_validate(
        {
            "name": "p",
            "sources": {"c": {"src": "v.mp4"}, "r": {"src": "r.wav"}},
            "timeline": [{"type": "clip", "source": "c", "start": 0, "end": 5, "effects": [vocoder("A2")]}],
            "audio": {"tracks": [{"source": "r"}]},
        }
    )
    assert uses_carrier_tracks(camera)  # a câmera ouve a faixa externa
    with pytest.raises(ValueError, match="ciclo"):
        Project.model_validate(
            {
                "name": "p",
                "sources": {"c": {"src": "v.mp4"}, "r": {"src": "r.wav"}},
                "timeline": [
                    {"type": "clip", "source": "c", "start": 0, "end": 5, "effects": [vocoder("A2")]}
                ],
                "audio": {"tracks": [{"source": "r", "effects": [vocoder("A1")]}]},
            }
        )


def test_the_project_refuses_a_cycle_but_accepts_a_chain_and_ignores_a_disabled_effect():
    with pytest.raises(ValueError, match="ciclo"):
        audio_project(
            music={"src": "m.mp3", "effects": [vocoder("NAR")]},
            narration=[{"text": "oi", "effects": [vocoder("MUS")]}],
        )
    chain = audio_project(
        music={"src": "m.mp3", "effects": [vocoder("NAR")]},
        narration=[{"text": "oi"}],
        voiceover=[{"src": "v.wav", "effects": [vocoder("MUS")]}],
    )
    assert uses_carrier_tracks(chain)
    off = {**vocoder("MUS"), "enabled": False}
    quiet = audio_project(
        music={"src": "m.mp3", "effects": [vocoder("NAR")]}, narration=[{"text": "oi", "effects": [off]}]
    )
    assert uses_carrier_tracks(quiet)  # só o da música está ligado
    assert not uses_carrier_tracks(audio_project(music={"src": "m.mp3", "effects": [vocoder(None)]}))


def test_the_pip_is_not_a_track_and_refuses_a_carrier_track():
    with pytest.raises(ValueError, match="PiP.*não é uma trilha"):
        Project.model_validate(
            {
                "name": "p",
                "timeline": [{"type": "clip", "src": "v.mp4", "start": 0, "end": 5}],
                "overlays": [{"type": "video", "src": "pip.mp4", "effects": [vocoder("MUS")]}],
            }
        )


def test_a_track_the_project_does_not_have_is_a_lint_warning_and_not_an_error():
    project = audio_project(narration=[{"text": "oi", "effects": [vocoder("A5")]}], music=None)
    from dmaker.domain.brand import load_theme
    from dmaker.domain.presets import get_preset

    warnings = lint(project, load_theme(None), get_preset("youtube/video"), 5.0, [5.0], [None])
    assert any("A5" in warning and "portadora gerada" in warning for warning in warnings)


# ---------- o grafo da trilha (puro) ----------


def test_the_track_graph_reads_each_piece_with_seek_and_length_and_places_it_on_the_timeline():
    pieces_ = [
        CarrierPiece(Path("a.wav"), 0, 1.0, 2.0, 0.0, 4.0),
        CarrierPiece(Path("b.wav"), 1, 0.5, 10.0, 4.0, 4.0, speed=1.5, lead=0.25),
    ]
    inputs, lines, label = carrier_graph(pieces_, 8.0)
    assert inputs.args == [
        "-ss",
        "2.000000",
        "-t",
        "4.000000",
        "-i",
        "a.wav",
        "-ss",
        "10.000000",
        "-t",
        "5.750000",
        "-i",
        "b.wav",
    ]
    first, second = lines[0], lines[1]
    assert (
        "adelay" not in first and "atempo" not in first
    )  # o primeiro pedaço está no começo e na velocidade normal
    assert "[1:a:1]" in second and "volume=0.500000" in second
    assert "adelay=12000S:all=1" in second  # o silêncio de 0,25 s de fonte
    assert "atempo=1.5" in second and "adelay=192000S:all=1" in second  # e 4 s da linha do tempo, a 48 kHz
    assert "amix=inputs=2:normalize=0" in lines[2] and label == "[cr_out]"
    assert "apad=whole_dur=8.000000" in lines[-1]


def test_a_track_without_pieces_is_silence_and_one_piece_needs_no_mix():
    inputs, lines, _ = carrier_graph([], 3.0)
    assert "anullsrc" in " ".join(inputs.args) and "amix" not in " ".join(lines)
    _, one, _ = carrier_graph([CarrierPiece(Path("a.wav"), 0, 1.0, 0.0, 0.0, 2.0)], 3.0)
    assert "amix" not in " ".join(one) and "[cr0]anull[cr_mix]" in one


def test_the_stretch_keeps_the_pitch_and_makes_the_clip_speed_longer():
    assert "tempo=0.666666667" in stretch_filter(1.5) and "rubberband" in stretch_filter(1.5)
    assert "tempo=2.000000000" in stretch_filter(0.5)


# ---------- ler a janela de um item ----------


def tracks_with(tmp_path: Path, samples: np.ndarray, runner=None) -> CarrierTracks:
    path = write_wav_float(tmp_path / "trilha.wav", samples, 48000)
    ctx = SimpleNamespace(runner=runner or RecordingRunner(), options=RenderOptions(dry_run=False))
    tracks = CarrierTracks(ctx, CarrierInputs([], [], 10.0, None, lambda: [], lambda: [], lambda: None))  # type: ignore[arg-type]
    offset, frames = wav_layout(path)
    tracks._tracks["MUS"] = CarrierTrack(path, "identidade", offset, frames)
    return tracks


def ramp(seconds: float) -> np.ndarray:
    """Um sinal em que cada amostra diz onde está (o valor sobe de 0 a 1 ao longo de `seconds`)."""
    frames = round(seconds * 48000)
    return np.repeat((np.arange(frames, dtype=np.float32) / frames)[:, None], 2, axis=1)


def test_the_window_puts_the_part_of_the_track_that_sounds_with_the_item_and_silence_elsewhere(tmp_path):
    tracks = tracks_with(tmp_path, ramp(10.0))
    frames = 4 * 48000
    # o item toca de 1 s a 3 s dele no segundo 5 do projeto
    window = tracks.window("MUS", [PlacedRun(1.0, 5.0, 2.0)], frames)
    assert window is not None and window.shape == (frames, 2)
    assert float(np.abs(window[: 48000 - 1]).max()) == 0.0  # antes do trecho: silêncio
    assert window[48000, 0] == pytest.approx(0.5, abs=1e-4)  # o segundo 5 do projeto
    assert float(np.abs(window[3 * 48000 :]).max()) == 0.0  # depois do trecho: silêncio


def test_a_run_past_the_end_of_the_track_is_silence_and_a_missing_track_has_no_window(tmp_path):
    tracks = tracks_with(tmp_path, ramp(4.0))
    window = tracks.window("MUS", [PlacedRun(0.0, 3.0, 3.0)], 3 * 48000)
    assert (
        window is not None
        and float(np.abs(window[48000:]).max()) == 0.0
        and float(np.abs(window[:48000]).max()) > 0
    )
    tracks._tracks["NAR"] = None
    assert tracks.window("NAR", [PlacedRun(0.0, 0.0, 1.0)], 100) is None


def test_a_clip_at_another_speed_stretches_the_slice_back_to_item_time_by_the_runner(tmp_path):
    runner = RecordingRunner()
    tracks = tracks_with(tmp_path, ramp(10.0), runner)
    window = tracks.window("MUS", [PlacedRun(0.0, 4.0, 4.0, 1.5)], 6 * 48000)
    assert window is not None and window.shape == (6 * 48000, 2)  # 4 s do projeto são 6 s do item
    command = " ".join(runner.commands[-1])
    assert (
        "-ss 4.000000" in command and "-t 4.000000" in command and "rubberband=tempo=0.666666667" in command
    )


def test_a_circular_request_for_a_track_that_is_being_built_is_an_error_and_not_a_loop():
    with pytest.raises(ValueError, match="ciclo"):
        late: Deferred = Deferred(lambda: late(), "a música")
        late()


# ---------- o item solto, o silêncio e o aviso ----------


class FakeCarriers:
    def __init__(self, window: np.ndarray | None, identity: str | None = "id1") -> None:
        self._window, self._identity = window, identity
        self.asked: list[tuple[str, tuple]] = []

    def identity(self, track_id: str) -> str | None:
        return self._identity

    def window(self, track_id, placement, frames):
        self.asked.append((track_id, tuple(placement)))
        return self._window


def item_with(effect: dict, placement: tuple = (PlacedRun(0.0, 1.0, 2.0),), path: str = "x.wav") -> AudioItem:
    return AudioItem(Path(path), 2.0, (parse_effect(effect),), placement=placement)


def test_the_key_only_carries_the_carrier_part_when_an_effect_uses_a_track(tmp_path):
    plain = EffectProcessor(RecordingRunner(), tmp_path)
    old = item_with({"type": "vocoder"})
    assert plain.key(old) == plain.key(
        AudioItem(old.path, old.duration, old.effects, placement=(PlacedRun(0, 9, 1),))
    )
    assert plain.carrier_parts(old.effects, old.placement) == []

    def key_with(
        carriers: FakeCarriers, placement: tuple = (PlacedRun(0.0, 1.0, 2.0),), track: str = "MUS"
    ) -> str:
        processor = EffectProcessor(RecordingRunner(), tmp_path, carriers=lambda: carriers)
        return processor.key(item_with({"type": "vocoder", "carrier_track": track}, placement))

    base = key_with(FakeCarriers(None))
    assert key_with(FakeCarriers(None)) == base
    assert key_with(FakeCarriers(None, identity="id2")) != base  # o som da trilha mudou
    assert (
        key_with(FakeCarriers(None), placement=(PlacedRun(0.0, 1.5, 2.0),)) != base
    )  # o item andou na linha do tempo
    assert key_with(FakeCarriers(None), track="NAR") != base  # outra trilha
    assert base != plain.key(old)


def test_the_item_without_a_track_falls_back_to_the_generated_carrier_and_warns_once(tmp_path):
    warnings: list[str] = []
    processor = EffectProcessor(RecordingRunner(), tmp_path, on_warning=warnings.append)
    item = item_with({"type": "vocoder", "carrier_track": "MUS"}, placement=())
    effect = item.effects[0]
    from dmaker.media.ffmpeg import SubprocessRunner

    processor.runner = SubprocessRunner(quiet=True)
    first = processor._side(effect, item, 48000, False)
    second = processor._side(effect, item, 48000, False)
    assert first is not None and first.shape == (48000, 2) and float(np.abs(first).max()) > 0
    assert second is not None and len(warnings) == 1 and "item solto" in warnings[0] and "MUS" in warnings[0]


def test_a_track_that_does_not_exist_or_does_not_play_yet_falls_back_with_its_own_warning(tmp_path):
    from dmaker.media.ffmpeg import SubprocessRunner

    warnings: list[str] = []
    carriers = FakeCarriers(None)
    processor = EffectProcessor(
        SubprocessRunner(quiet=True), tmp_path, on_warning=warnings.append, carriers=lambda: carriers
    )
    item = item_with({"type": "vocoder", "carrier_track": "A5"})
    assert processor._side(item.effects[0], item, 4800, False) is not None
    assert warnings and "não existe" in warnings[0] and carriers.asked == [("A5", item.placement)]


def test_a_silent_carrier_window_warns_and_is_still_the_carrier(tmp_path):
    warnings: list[str] = []
    silence = np.zeros((4800, 2), dtype=np.float32)
    processor = EffectProcessor(
        RecordingRunner(), tmp_path, on_warning=warnings.append, carriers=lambda: FakeCarriers(silence)
    )
    item = item_with({"type": "vocoder", "carrier_track": "MUS"})
    assert processor._side(item.effects[0], item, 4800, False) is silence
    assert len(warnings) == 1 and f"{SILENT_CARRIER_DB:.0f} dBFS" in warnings[0] and "mudo" in warnings[0]
    loud = np.full((4800, 2), 0.1, dtype=np.float32)
    quiet_processor = EffectProcessor(
        RecordingRunner(), tmp_path, on_warning=warnings.append, carriers=lambda: FakeCarriers(loud)
    )
    assert quiet_processor._side(item.effects[0], item, 4800, False) is loud and len(warnings) == 1


def test_an_effect_that_changes_the_duration_before_the_vocoder_warns_to_put_it_after(tmp_path):
    warnings: list[str] = []
    loud = np.full((4800, 2), 0.1, dtype=np.float32)
    processor = EffectProcessor(
        RecordingRunner(), tmp_path, on_warning=warnings.append, carriers=lambda: FakeCarriers(loud)
    )
    item = item_with({"type": "vocoder", "carrier_track": "MUS"})
    processor._side(item.effects[0], item, 4800, True)
    assert (
        len(warnings) == 1 and "antes do efeito" not in warnings[0] and "ponha o Vocoder antes" in warnings[0]
    )


# ---------- onde cada tipo de item cai ----------


class SpyProcessor:
    """Registra o item e não processa nada: o som segue pela fonte, e o teste olha o `placement` que cada trilha montou."""

    def __init__(self) -> None:
        self.items: list[AudioItem] = []

    def process(self, item: AudioItem):
        self.items.append(item)

    def carrier_parts(self, effects, placement):
        return []


def spy_context(
    project: Project, spans: list[tuple[float, float]], total: float = 10.0
) -> tuple[RenderContext, SpyProcessor]:
    ctx = RenderContext.__new__(RenderContext)
    spy = SpyProcessor()
    ctx.project, ctx.options, ctx.log, ctx.warnings = (
        project,
        RenderOptions(dry_run=True),
        lambda message: None,
        [],
    )
    ctx.audio_fx, ctx.prober, ctx.session, ctx.runner = spy, make_prober, {}, RecordingRunner()  # type: ignore[assignment]
    ctx.carrier_tracks = CarrierTracks(  # type: ignore[arg-type]
        ctx, CarrierInputs(spans, [], total, None, lambda: [], lambda: [], lambda: None)
    )
    return ctx, spy


MUSIC_FX = {"src": "musica.mp3", "volume": 0.3, "effects": [vocoder("NAR")]}


def test_the_music_is_placed_by_each_window_and_the_loop_keeps_only_the_first_pass(tmp_path):
    project = make_project(
        tmp_path,
        timeline=[{"type": "card", "title": "x", "duration": 10}],
        audio={
            "music": {
                **MUSIC_FX,
                "spans": [{"start": 2, "end": 6, "start_at": 1.0}, {"start": 8, "end": 9}],
                "loop": False,
            }
        },
    )
    ctx, spy = spy_context(project, [(0.0, 10.0)])
    processed_music(ctx, tmp_path / "musica.mp3")
    assert spy.items[0].placement == (PlacedRun(1.0, 2.0, 4.0), PlacedRun(0.0, 8.0, 1.0))
    assert ctx.warnings == []

    looping = make_project(
        tmp_path,
        timeline=[{"type": "card", "title": "x", "duration": 10}],
        audio={"music": {**MUSIC_FX, "start_at": 119.0}},
    )
    ctx, spy = spy_context(looping, [(0.0, 10.0)])
    processed_music(ctx, tmp_path / "musica.mp3")
    assert spy.items[0].placement == (
        PlacedRun(119.0, 0.0, 1.0),
    )  # o arquivo tem 120 s: só 1 s antes de repetir
    assert len(ctx.warnings) == 1 and "loop" in ctx.warnings[0]


def test_the_narration_the_recorded_voice_and_the_generated_sound_are_placed_at_their_start(tmp_path):
    project = make_project(
        tmp_path,
        timeline=[{"type": "card", "title": "x", "duration": 10}],
        audio={"narration": [{"text": "oi", "start": 3.0, "effects": [vocoder("MUS")]}]},
    )
    ctx, spy = spy_context(project, [(0.0, 10.0)])
    spoken = PreparedVoiceover(
        tmp_path / "fala.wav", 3.0, 1.0, 2.5, effects=tuple(project.audio.narration[0].effects)
    )
    processed_voiceovers(ctx, [spoken])
    assert spy.items[0].placement == (PlacedRun(0.0, 3.0, 2.5),)

    voices = make_project(
        tmp_path,
        timeline=[{"type": "card", "title": "x", "duration": 10}],
        audio={
            "voiceover": [{"src": "locucao.wav", "start": 2.5, "offset": 20.0, "effects": [vocoder("MUS")]}]
        },
    )
    recorder = SpyProcessor()
    prepare_voice_files(voices, make_prober, recorder)  # type: ignore[arg-type]
    assert recorder.items[0].placement == (
        PlacedRun(0.0, 2.5, 100.0),
    )  # 120 s de arquivo menos os 20 s do ponto de entrada

    from dmaker.pipeline.generated_sounds import generated_tracks

    sounds = make_project(
        tmp_path,
        timeline=[{"type": "card", "title": "x", "duration": 10}],
        audio={
            "generated": [{"generator": "tone", "start": 1.5, "duration": 2.0, "effects": [vocoder("MUS")]}]
        },
    )
    ctx, spy = spy_context(sounds, [(0.0, 10.0)])
    ctx.options = RenderOptions(dry_run=True)
    renderer = SimpleNamespace(render=lambda sound, resolve: tmp_path / "tom.wav")
    generated_tracks(ctx, renderer)  # type: ignore[arg-type]
    assert spy.items[0].placement == (PlacedRun(0.0, 1.5, 2.0),)


# ---------- o clipe e a faixa externa, pelo caminho da prévia ----------

CLIP_FX = vocoder("MUS")


def timeline_project(tmp_path: Path, first_end: float = 4.0, carrier: str | None = "MUS", **audio) -> Project:
    tmp_path.mkdir(parents=True, exist_ok=True)
    effect = {"effects": [vocoder(carrier)]} if carrier is not None else {}
    return make_project(
        tmp_path,
        sources={"cam1": {"src": "cam1.mp4"}, "mesa": {"src": "mesa.wav", "sync": 0.0}},
        timeline=[
            {"type": "clip", "source": "cam1", "start": 0, "end": first_end},
            {"type": "clip", "source": "cam1", "start": 10, "end": 16, "speed": 1.5, **effect},
        ],
        audio={"normalize": "off", "music": {"src": "musica.mp3", "volume": 0.3, "ducking": False}, **audio},
    )


def build(tmp_path: Path, project: Project, monkeypatch=None) -> tuple[RecordingRunner, SpyProcessor]:
    runner = RecordingRunner(on_run=fake_ffmpeg_output, capture_stderr=LOUDNORM_JSON)
    spy = SpyProcessor()
    if monkeypatch is not None:
        monkeypatch.setattr(EffectProcessor, "process", lambda self, item: spy.process(item))
    builder_for(tmp_path, runner).build(project)
    return runner, spy


def test_a_clip_at_one_and_a_half_times_is_placed_where_it_starts_on_the_timeline(tmp_path, monkeypatch):
    _, spy = build(tmp_path, timeline_project(tmp_path), monkeypatch)
    item = next(item for item in spy.items if item.effects and item.effects[0].carrier_track_id())
    # o clipe de 6 s de fonte a 1,5x dura 4 s e começa onde o primeiro acaba
    assert item.placement == (PlacedRun(0.0, 4.0, 4.0, 1.5),) and item.duration == pytest.approx(6.0)


def test_an_external_track_used_by_two_clips_is_placed_once_per_clip(tmp_path, monkeypatch):
    project = make_project(
        tmp_path,
        sources={"cam1": {"src": "cam1.mp4"}, "mesa": {"src": "mesa.wav", "sync": 0.0}},
        timeline=[
            {"type": "clip", "source": "cam1", "start": 0, "end": 4},
            {"type": "clip", "source": "cam1", "start": 10, "end": 14},
        ],
        audio={
            "tracks": [{"source": "mesa", "effects": [vocoder("MUS")]}],
            "music": {"src": "musica.mp3", "volume": 0.3, "ducking": False},
            "normalize": "off",
        },
    )
    _, spy = build(tmp_path, project, monkeypatch)
    item = next(item for item in spy.items if item.path.name == "mesa.wav" and item.effects)
    assert item.placement == (PlacedRun(0.0, 0.0, 4.0), PlacedRun(10.0, 4.0, 4.0))


def piece_names(runner: RecordingRunner) -> list[str]:
    return [Path(command[-1]).name for command in pieces(runner)]


def test_the_piece_key_follows_the_track_the_file_of_the_track_and_the_position_of_the_clip(
    tmp_path, monkeypatch
):
    def names(label: str, **options) -> list[str]:
        # o projeto fica sempre na mesma pasta (o caminho do arquivo entra na chave); só o cache muda por rodada
        runner, _ = build(tmp_path / label, timeline_project(tmp_path, **options), monkeypatch)
        return piece_names(runner)

    base = names("base")
    assert names("de-novo") == base
    other_track = names("trilha", carrier="VO")
    assert other_track[1] != base[1] and other_track[0] == base[0]
    # o clipe andou 1 s na linha do tempo: o Vocoder ouve outro trecho da música
    assert names("andou", first_end=5.0)[1] != base[1]
    (tmp_path / "musica.mp3").write_bytes(b"outro som da musica")  # o arquivo da portadora trocou
    assert names("arquivo")[1] != base[1]


def test_a_vocoder_with_a_generated_carrier_keeps_its_piece_when_the_clip_moves(tmp_path, monkeypatch):
    def names(label: str, **options) -> list[str]:
        runner, _ = build(tmp_path / label, timeline_project(tmp_path, carrier=None, **options), monkeypatch)
        return piece_names(runner)

    assert names("andou", first_end=5.0)[1] == names("base")[1]


def test_a_project_without_a_carrier_track_does_not_install_the_pass_nor_run_it(tmp_path, monkeypatch):
    runner, _ = build(tmp_path, timeline_project(tmp_path, carrier=None), monkeypatch)
    assert not any(command[-1].startswith("#portadora") for command in runner.commands)
    assert not (tmp_path / "carriers").exists()
    project = timeline_project(tmp_path, carrier=None)
    assert not uses_carrier_tracks(project)


# ---------- os adaptadores ----------


def test_the_catalog_describes_the_track_choice_and_hides_the_generated_carrier_when_one_is_chosen():
    from dmaker.domain.audio_effects import catalog_payload

    vocoder_info = next(entry for entry in catalog_payload()["effects"] if entry["type"] == "vocoder")
    params = {param["name"]: param for param in vocoder_info["parameters"]}
    assert params["carrier_track"]["kind"] == "carrier_track" and params["carrier_track"]["default"] is None
    assert "portadora gerada" in params["carrier_track"]["hint"]
    assert params["carrier"]["shown_when"] == {"carrier_track": None}


def test_the_cli_sets_the_carrier_track_and_refuses_a_pair_that_does_not_hold(tmp_path):
    import json

    from typer.testing import CliRunner

    from dmaker.cli import app

    cli = CliRunner()
    spec = audio_project(music={"src": "m.mp3"}, narration=[{"text": "oi"}]).save(tmp_path / "spec.json")
    added = cli.invoke(
        app, ["audio", "effect", "add", str(spec), "audio.narration.0", "vocoder", "-p", "carrier_track=MUS"]
    )
    assert added.exit_code == 0, added.output
    effects = json.loads(spec.read_text(encoding="utf-8"))["audio"]["narration"][0]["effects"]
    assert [(effect["type"], effect["carrier_track"]) for effect in effects] == [("vocoder", "MUS")]
    refused = cli.invoke(
        app, ["audio", "effect", "add", str(spec), "audio.music", "vocoder", "-p", "carrier_track=MUS"]
    )
    assert refused.exit_code != 0 and "portadora gerada" in " ".join(refused.output.split())
    listing = cli.invoke(app, ["audio", "effects", "vocoder"])
    assert listing.exit_code == 0 and "carrier_track" in listing.output


# ---------- o aviso do loop e o temporário da passada (ajuste do DMK-70) ----------


def test_the_loop_warning_only_comes_when_the_music_itself_listens_to_another_track(tmp_path):
    def warnings_for(music_effects: list[dict]) -> list[str]:
        project = make_project(
            tmp_path,
            timeline=[{"type": "card", "title": "x", "duration": 10}],
            audio={
                "music": {"src": "musica.mp3", "start_at": 119.0, "effects": music_effects},
                "voiceover": [
                    {"src": "fala.wav", "effects": [vocoder("MUS")]}
                ],  # o projeto usa carrier_track
            },
        )
        ctx, _ = spy_context(project, [(0.0, 10.0)])
        processed_music(ctx, tmp_path / "musica.mp3")
        return ctx.warnings

    assert warnings_for([{"type": "tremolo"}]) == []  # outro efeito: nada a avisar
    assert warnings_for([{**vocoder("NAR"), "enabled": False}]) == []
    assert len(warnings_for([vocoder("NAR")])) == 1


def test_the_staging_file_of_the_carrier_pass_changes_on_every_run(tmp_path, monkeypatch):
    def staging_names(label: str) -> list[str]:
        # a chave do item pede a identidade da trilha, e é ela que dispara a passada
        monkeypatch.setattr(EffectProcessor, "process", lambda self, item: (self.key(item), None)[1])
        runner, _ = build(tmp_path / label, timeline_project(tmp_path / label))
        return [Path(c[-1]).name for c in runner.commands if Path(c[-1]).parent.name == "carriers"]

    first, second = staging_names("um"), staging_names("dois")
    assert first and second
    assert all(re.search(r"\.tmp-\d+-[0-9a-f]{8}\.wav$", name) for name in first + second)
    assert set(first).isdisjoint(second)
