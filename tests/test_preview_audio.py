"""Áudio da prévia da linha do tempo: a receita dos pedaços (a mesma do mezanino do render), a chave de cache
da mixagem e o serviço inteiro com `RecordingRunner`, probe falso e sintetizador falso, sem ffmpeg de verdade."""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from dmaker import config
from dmaker.domain.spec import ClipSegment, Project
from dmaker.filtergraph.mezzanine import TrackSlice, clip_mezzanine
from dmaker.filtergraph.preview_audio import (
    PREVIEW_AUDIO_BITRATE,
    clip_audio_piece,
    preview_encode_args,
    silence_piece,
)
from dmaker.media.audiosync import SyncResult
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.media.probe import MediaInfo
from dmaker.media.separation import Stems
from dmaker.pipeline.isolation import IsolationService
from dmaker.pipeline.narration import NarrationService
from dmaker.pipeline.preview_audio import PreviewAudioBuilder, piece_recipe
from dmaker.pipeline.preview_audio_tasks import PreviewAudioTasks
from dmaker.voice.synth import Speech, VoiceRequest

from .conftest import fake_ffmpeg_output
from .test_pipeline_unit import LOUDNORM_JSON


def make_prober(path: Path) -> MediaInfo:
    """Câmeras de 400 s, gravadores de 120 s e câmeras em partes de 60 s."""
    if path.suffix in (".wav", ".mp3"):
        return MediaInfo(path, 120.0, 0, 0, 0.0, False, True, False)
    if path.name.startswith("cam1_"):
        return MediaInfo(path, 60.0, 1920, 1080, 30.0, True, True, False)
    return MediaInfo(path, 400.0, 1920, 1080, 30.0, True, True, False)


def no_audio_link(master: Path, other: Path, master_stream: int, other_stream: int) -> SyncResult:
    """Correlação sem confiança: a cadeia das partes cai para o relógio (uma parte encosta na outra)."""
    return SyncResult(0.0, confidence=0.0)


FILES = ("cam1.mp4", "cam2.mp4", "cam1_a.mp4", "cam1_b.mp4", "mesa.wav", "musica.mp3", "locucao.wav")


def make_project(tmp_path: Path, **spec) -> Project:
    for name in FILES:
        if not (tmp_path / name).exists():  # reescrever mudaria a data do arquivo, e com ela a chave
            (tmp_path / name).write_bytes(b"x")
    project = Project.model_validate({"name": "sessao", "output": {"preset": "youtube/video"}, **spec})
    project.base_dir = tmp_path
    return project


def make_builder(tmp_path: Path, **kwargs) -> tuple[PreviewAudioBuilder, RecordingRunner]:
    runner = RecordingRunner(on_run=fake_ffmpeg_output, capture_stderr=LOUDNORM_JSON)
    builder = PreviewAudioBuilder(
        runner=runner,
        prober=make_prober,
        offset_finder=no_audio_link,
        cache_dir=tmp_path / "preview-audio",
        jobs_dir=tmp_path / "jobs",
        **kwargs,
    )
    return builder, runner


def pieces(runner: RecordingRunner) -> list[list[str]]:
    """Os comandos que fazem o WAV de um trecho (silêncio ou clipe): os que escrevem na pasta dos pedaços."""
    return [c for c in runner.commands if Path(c[-1]).parent.name == "pieces"]


def mixes(runner: RecordingRunner) -> list[list[str]]:
    return [c for c in runner.commands if "aac" in c]


def graph_of(command: list[str]) -> str:
    return command[command.index("-filter_complex") + 1]


def inputs_of(command: list[str]) -> list[tuple[str, float]]:
    """(arquivo, `-ss`) de cada entrada do comando."""
    found, ss = [], 0.0
    for position, arg in enumerate(command):
        if arg == "-ss":
            ss = float(command[position + 1])
        elif arg == "-i":
            found.append((Path(command[position + 1]).name, ss))
            ss = 0.0
    return found


SESSION = {
    "sources": {"cam1": {"src": "cam1.mp4"}, "mesa": {"src": "mesa.wav", "sync": -3.0}},
    "timeline": [
        {"type": "clip", "source": "cam1", "start": 20, "end": 30, "mute": True},
        {
            "type": "clip",
            "source": "cam1",
            "start": 45,
            "end": 50,
            "mute": True,
            "transition": {"type": "cut"},
        },
    ],
    "audio": {
        "tracks": [{"source": "mesa", "volume": 0.5}],
        "music": {
            "src": "musica.mp3",
            "volume": 0.3,
            "spans": [{"start": 0, "end": 8, "fade_in": 0.5, "fade_out": 1.0}],
        },
    },
}


# ---------- filtergraph: o pedaço é o ramo de áudio do mezanino ----------


def test_piece_audio_branch_is_the_one_the_mezzanine_uses():
    """A prévia soa como o vídeo final porque a receita do som de um trecho é uma só: as linhas de áudio do
    pedaço são exatamente as do mezanino (câmera, faixas externas, velocidade e fades)."""
    segment = ClipSegment(
        src="cam.mp4", start=2, end=12, speed=2.0, fade_in=0.3, fade_out=0.4, audio_fade=0.1
    )
    info = MediaInfo(Path("cam.mp4"), 60.0, 1920, 1080, 30.0, True, True, False)
    tracks = (TrackSlice(Path("mesa.wav"), -1.5, 0.5, 0), TrackSlice(Path("outra.wav"), 7.0, 1.0, 1))

    mezzanine = clip_mezzanine(
        segment, info, Path("cam.mp4"), 5.0, 1080, 1920, 30, Path("m.mov"), in_point=2.0, tracks=tracks
    )
    piece = clip_audio_piece(segment, info, Path("cam.mp4"), 5.0, Path("p.wav"), in_point=2.0, tracks=tracks)

    def audio_lines(command) -> list[str]:
        graph = command.args[command.args.index("-filter_complex") + 1]
        return [
            line for line in graph.split(";") if "[mz_cam]" in line or "[mz_trk" in line or "[aout]" in line
        ]

    assert audio_lines(piece) == audio_lines(mezzanine)
    assert piece.args[piece.args.index("-map") + 1] == "[aout]" and piece.args[-1] == "p.wav"
    assert "-c:a" in piece.args and "pcm_s16le" in piece.args and "-c:v" not in piece.args


def test_piece_does_not_open_the_clip_file_when_the_camera_is_silent():
    segment = ClipSegment(source="cam1", start=0, end=10, mute=True)
    info = MediaInfo(Path("cam1.mp4"), 60.0, 1920, 1080, 30.0, True, True, False)
    piece = clip_audio_piece(
        segment,
        info,
        Path("cam1.mp4"),
        10.0,
        Path("p.wav"),
        in_point=0.0,
        tracks=(TrackSlice(Path("mesa.wav"), 4.0),),
    )
    assert [Path(a).name for a in piece.args if a.endswith((".mp4", ".wav")) and a != "p.wav"] == ["mesa.wav"]
    assert "volume" not in graph_of(piece.args)  # volume 1: sem filtro de ganho


def test_piece_uses_the_isolated_camera_audio_instead_of_the_clip_file():
    segment = ClipSegment(src="cam.mp4", start=0, end=10, audio_mode="voice")
    info = MediaInfo(Path("cam.mp4"), 60.0, 1920, 1080, 30.0, True, True, False)
    piece = clip_audio_piece(
        segment, info, Path("cam.mp4"), 10.0, Path("p.wav"), in_point=0.0, camera_audio=Path("voz.wav")
    )
    names = [Path(a).name for a in piece.args if a.endswith((".mp4", ".wav")) and a != "p.wav"]
    assert names == ["voz.wav"]


def test_silence_piece_and_encoding():
    silence = silence_piece(3.5, Path("s.wav"))
    assert "anullsrc=r=48000:cl=stereo" in silence.args and silence.args[-1] == "s.wav"
    assert silence.args[silence.args.index("-t") + 1] == "3.500"
    args = preview_encode_args(12.25, Path("saida.m4a"))
    assert (
        args[args.index("-c:a") + 1] == "aac"
        and args[args.index("-b:a") + 1] == PREVIEW_AUDIO_BITRATE == "96k"
    )
    assert "-vn" in args and args[args.index("-t") + 1] == "12.250" and "+faststart" in args


# ---------- receita e chave ----------


def test_piece_recipe_ignores_what_does_not_change_the_sound():
    base = ClipSegment(src="a.mp4", start=1, end=5)
    visual = base.model_copy(update={"color": base.color.model_copy(update={"brightness": 0.2})})
    assert piece_recipe(base) == piece_recipe(visual)
    for change in ({"volume": 0.5}, {"mute": True}, {"speed": 2.0}, {"audio_mode": "voice"}, {"start": 2}):
        assert piece_recipe(base) != piece_recipe(base.model_copy(update=change)), change


def test_key_follows_the_sound_and_not_the_picture(tmp_path):
    builder, _ = make_builder(tmp_path)
    project = make_project(tmp_path, **SESSION)
    key = builder.key(project)
    assert key == builder.key(make_project(tmp_path, **SESSION))  # estável

    texted = make_project(
        tmp_path, **SESSION, overlays=[{"type": "text", "text": "Olá", "start": 0, "end": 2}]
    )
    assert builder.key(texted) == key  # texto na tela não muda o som

    def tweaked(**audio) -> str:
        spec = {**SESSION, "audio": {**SESSION["audio"], **audio}}
        return builder.key(make_project(tmp_path, **spec))

    assert tweaked(mute_clips=True) != key
    assert tweaked(voice_gain=0.5) != key
    assert tweaked(tracks=[{"source": "mesa", "volume": 0.8}]) != key
    assert tweaked(music={**SESSION["audio"]["music"], "volume": 0.5}) != key

    muted_track = make_project(tmp_path, **SESSION, tracks={"A2": {"muted": True}})
    assert builder.key(muted_track) != key  # o mudo da trilha A2 vale na prévia

    (tmp_path / "mesa.wav").write_bytes(b"outro conteudo")  # o arquivo mudou no disco
    assert builder.key(project) != key


# ---------- a mixagem ----------


def test_mix_slices_the_external_track_by_cut_like_the_render(tmp_path):
    """Câmeras mudas, a mesa começa 3 s antes da câmera (sync -3) e toca a 0,5: cada corte leva o pedaço da
    mesa que corresponde ao instante dele, e a música segue o span com os fades."""
    builder, runner = make_builder(tmp_path)
    project = make_project(tmp_path, **SESSION)

    audio = builder.build(project)

    first, second = pieces(runner)
    assert inputs_of(first) == [("mesa.wav", 23.0)]  # 20 s da sessão = 23 s no arquivo da mesa
    assert inputs_of(second) == [("mesa.wav", 48.0)]
    assert "volume=0.500" in graph_of(first)
    (mix,) = mixes(runner)
    graph = (
        graph_of(mix)
        if "-filter_complex" in mix
        else Path(mix[mix.index("-/filter_complex") + 1]).read_text(encoding="utf-8")
    )
    assert "concat=n=2:v=0:a=1" in graph  # corte seco: os dois trechos seguem juntos
    assert "atrim=start=0.000:duration=8.000" in graph and "afade=t=out" in graph  # span da música com fade
    assert audio.path.exists() and audio.path.suffix == ".m4a" and audio.duration == pytest.approx(15.0)
    assert Path(mix[-1]).name.startswith(f"{project.name}__{audio.key}") and mix[-1].endswith(".m4a")
    # a normalização two-pass mediu antes de mixar
    assert any("print_format=json" in " ".join(c) for c in runner.commands)
    assert "measured_I=-23.5" in graph


def test_mix_follows_the_part_of_a_source_that_records_each_instant(tmp_path):
    spec = {
        "sources": {
            "cam1": {"parts": ["cam1_a.mp4", "cam1_b.mp4"]},
            "mesa": {"src": "mesa.wav", "sync": 5.0},
        },
        "timeline": [{"type": "clip", "source": "cam1", "start": 50, "end": 70, "mute": True}],
        "audio": {"tracks": [{"source": "mesa"}], "normalize": "off"},
    }
    builder, runner = make_builder(tmp_path)
    builder.build(make_project(tmp_path, **spec))

    # o clipe atravessa a fronteira dos dois arquivos: dois pedaços, e a mesa continua do ponto onde parou
    assert [inputs_of(c) for c in pieces(runner)] == [[("mesa.wav", 45.0)], [("mesa.wav", 55.0)]]
    assert not any("print_format=json" in " ".join(c) for c in runner.commands)  # normalize off: sem medição


def test_second_build_is_the_cache_and_an_edit_redoes_only_that_cut(tmp_path):
    builder, runner = make_builder(tmp_path)
    project = make_project(tmp_path, **SESSION)
    first = builder.build(project)
    done = len(runner.commands)

    again = builder.build(project)
    assert again.path == first.path and len(runner.commands) == done  # nada foi refeito

    spec = {**SESSION, "timeline": [dict(SESSION["timeline"][0], speed=2.0), SESSION["timeline"][1]]}
    edited = builder.build(make_project(tmp_path, **spec))
    assert edited.key != first.key and edited.path != first.path
    redone = pieces(runner)[2:]
    assert len(redone) == 1 and inputs_of(redone[0]) == [("mesa.wav", 23.0)]  # só o corte que mudou
    assert len(mixes(runner)) == 2


def test_measuring_the_sync_does_not_make_the_first_mix_unreachable(tmp_path):
    """Sincronizar pelo áudio grava o `sync.json`, que entra na chave: a mixagem fica guardada sob a chave de
    depois, a que o próximo pedido da mesma spec calcula, e então ele a acha em vez de mixar de novo."""
    spec = {
        "sources": {"cam1": {"src": "cam1.mp4"}, "mesa": {"src": "mesa.wav", "sync": "auto"}},
        "timeline": [{"type": "clip", "source": "cam1", "start": 20, "end": 30, "mute": True}],
        "audio": {"tracks": [{"source": "mesa"}], "normalize": "off"},
    }
    builder, runner = make_builder(tmp_path)
    builder.offset_finder = lambda master, other, ms, os_: SyncResult(-3.0, confidence=9.0)
    project = make_project(tmp_path, **spec)
    asked = builder.key(project)

    first = builder.build(project, asked)
    assert (tmp_path / "sync.json").exists()
    assert first.key != asked  # a chave de antes de medir não é a de depois
    assert builder.key(project) == first.key
    assert builder.cached(project.name, first.key) is not None

    done = len(runner.commands)
    again = builder.build(project)
    assert again.path == first.path and len(runner.commands) == done


def test_mute_clips_and_a_muted_track_change_the_next_mix(tmp_path):
    builder, runner = make_builder(tmp_path)
    plain = builder.build(make_project(tmp_path, **SESSION))
    muted_clips = builder.build(
        make_project(tmp_path, **{**SESSION, "audio": {**SESSION["audio"], "mute_clips": True}})
    )
    muted_track = builder.build(make_project(tmp_path, **SESSION, tracks={"A2": {"muted": True}}))
    assert len({plain.key, muted_clips.key, muted_track.key}) == 3

    def mix_graph(command: list[str]) -> str:
        return (
            graph_of(command)
            if "-filter_complex" in command
            else Path(command[command.index("-/filter_complex") + 1]).read_text(encoding="utf-8")
        )

    plain_mix, clips_mix, _ = (mix_graph(c) for c in mixes(runner))
    assert "volume=0[a_mute]" not in plain_mix and "volume=0[a_mute]" in clips_mix
    # sem a faixa A2 não há de onde tirar o som: os trechos viram silêncio e a mesa nem é aberta
    track_pieces = pieces(runner)[2:]
    assert len(track_pieces) == 2 and all("anullsrc" in " ".join(c) for c in track_pieces)
    assert all("mesa.wav" not in " ".join(c) for c in track_pieces)
    assert "mesa.wav" not in " ".join(mixes(runner)[2])


def test_a_missing_camera_file_becomes_silence_and_the_mix_still_comes_out(tmp_path):
    spec = {
        "timeline": [
            {"type": "clip", "src": "cam1.mp4", "start": 0, "end": 4},
            {"type": "clip", "src": "sumiu.mp4", "start": 0, "end": 6},
        ],
        "audio": {"normalize": "off"},
    }
    builder, runner = make_builder(tmp_path)
    audio = builder.build(make_project(tmp_path, **spec))
    assert audio.path.exists() and audio.duration == pytest.approx(10.0)
    assert any("anullsrc" in " ".join(c) for c in pieces(runner))  # o trecho sem arquivo é silêncio
    assert all("sumiu.mp4" not in " ".join(c) for c in runner.commands)


def test_image_and_card_are_silence(tmp_path):
    spec = {
        "timeline": [{"type": "card", "title": "Fim", "duration": 2.0}],
        "audio": {"normalize": "off"},
    }
    builder, runner = make_builder(tmp_path)
    audio = builder.build(make_project(tmp_path, **spec))
    assert audio.duration == pytest.approx(2.0)
    (piece,) = pieces(runner)
    assert "anullsrc" in " ".join(piece)


def test_pip_with_sound_enters_the_mix_and_music_without_file_is_dropped(tmp_path):
    spec = {
        "timeline": [{"type": "clip", "src": "cam1.mp4", "start": 0, "end": 6, "mute": True}],
        "overlays": [
            {"type": "video", "src": "cam2.mp4", "start": 1, "end": 5, "offset": 2.0, "volume": 0.7}
        ],
        "audio": {"normalize": "off", "music": {"src": "nao-existe.mp3"}},
    }
    builder, runner = make_builder(tmp_path)
    builder.build(make_project(tmp_path, **spec))
    (mix,) = mixes(runner)
    names = [name for name, _ in inputs_of(mix)]
    assert "cam2.mp4" in names and "nao-existe.mp3" not in names
    assert "adelay=1000:all=1" in graph_of(mix) and "volume=0.700" in graph_of(mix)


# ---------- narração: só a já sintetizada ----------


class FakeSynthesizer:
    engine_id = "fake-preview"

    def __init__(self) -> None:
        self.requests: list[VoiceRequest] = []

    def synthesize(self, request: VoiceRequest) -> Speech:
        self.requests.append(request)
        count = int(len(request.text) * 0.05 * 24000)
        return Speech((0.3 * np.sin(2 * np.pi * 440 * np.arange(count) / 24000)).astype(np.float32), 24000)


def narrated_builder(tmp_path: Path, synthesizer: FakeSynthesizer):
    runner = RecordingRunner(on_run=fake_ffmpeg_output, capture_stderr=LOUDNORM_JSON)

    def narrator(narration_runner):
        return NarrationService(synthesizer, narration_runner, cache_dir=tmp_path / "voice-cache")

    builder = PreviewAudioBuilder(
        runner=runner,
        prober=make_prober,
        offset_finder=no_audio_link,
        narrator=narrator,
        cache_dir=tmp_path / "preview-audio",
        jobs_dir=tmp_path / "jobs",
    )
    return builder, runner, narrator


NARRATED = {
    "timeline": [{"type": "clip", "src": "cam1.mp4", "start": 0, "end": 10, "mute": True}],
    "audio": {"normalize": "off", "narration": [{"text": "Fala pronta.", "start": 2.0, "volume": 0.8}]},
}


def test_a_synthesized_narration_enters_the_mix_at_its_start(tmp_path):
    synthesizer = FakeSynthesizer()
    builder, runner, narrator = narrated_builder(tmp_path, synthesizer)
    narrator(runner).render("Fala pronta.", tmp_path / "pronta.wav", None)  # a fala já foi gerada antes
    asked = len(synthesizer.requests)
    project = make_project(tmp_path, **NARRATED)

    audio = builder.build(project)

    (mix,) = mixes(runner)
    graph = graph_of(mix)
    assert "narration_1.wav" in " ".join(mix) and "volume=0.800" in graph and "adelay=2000:all=1" in graph
    assert audio.warnings == ()
    assert len(synthesizer.requests) == asked  # a prévia nunca sintetiza


def test_a_narration_not_yet_synthesized_stays_out_with_a_warning_and_the_mix_changes_when_it_arrives(
    tmp_path,
):
    synthesizer = FakeSynthesizer()
    builder, runner, narrator = narrated_builder(tmp_path, synthesizer)
    project = make_project(tmp_path, **NARRATED)
    before = builder.key(project)

    audio = builder.build(project)

    assert synthesizer.requests == []  # nem tentou falar
    assert audio.warnings == ("A narração 1 ainda não foi sintetizada e fica fora da prévia.",)
    assert "narration_1.wav" not in " ".join(mixes(runner)[0])

    narrator(runner).render("Fala pronta.", tmp_path / "pronta.wav", None)
    assert builder.key(project) != before  # com a fala pronta a chave muda e a mixagem é refeita


# ---------- audio_mode: voz isolada em cache ----------


class FakeSeparator:
    model_id = "fake:1"

    def __init__(self) -> None:
        self.calls = 0

    def separate(self, wav: Path, out_dir: Path, on_progress=None) -> Stems:
        self.calls += 1
        stems = Stems.in_directory(out_dir)
        stems.vocals.write_bytes(b"voz")
        stems.background.write_bytes(b"fundo")
        return stems


def test_audio_mode_voice_plays_the_isolated_stem_and_separates_once(tmp_path):
    separator = FakeSeparator()
    runner = RecordingRunner(on_run=fake_ffmpeg_output, capture_stderr=LOUDNORM_JSON)
    isolator = IsolationService(separator, runner, cache_dir=tmp_path / "stems")
    builder = PreviewAudioBuilder(
        runner=runner,
        prober=make_prober,
        offset_finder=no_audio_link,
        isolator=isolator,
        cache_dir=tmp_path / "preview-audio",
        jobs_dir=tmp_path / "jobs",
    )
    spec = {
        "timeline": [{"type": "clip", "src": "cam2.mp4", "start": 5, "end": 15, "audio_mode": "voice"}],
        "audio": {"normalize": "off"},
    }
    project = make_project(tmp_path, **spec)
    builder.build(project)
    (piece,) = pieces(runner)
    assert [Path(p).name for p, _ in inputs_of(piece)] == ["vocals.wav"]
    assert separator.calls == 1

    other = make_project(tmp_path, **{**spec, "audio": {"normalize": "off", "voice_gain": 0.5}})
    builder.build(other)  # outra mixagem, mesmo trecho: o pedaço e os stems vêm do cache
    assert separator.calls == 1 and len(pieces(runner)) == 1


# ---------- cache em disco ----------


def test_old_mixes_are_dropped_but_the_newest_stay(tmp_path):
    builder, _ = make_builder(tmp_path)
    keys = []
    for gain in (0.5, 0.6, 0.7, 0.8, 0.9):
        spec = {**SESSION, "audio": {**SESSION["audio"], "voice_gain": gain}}
        keys.append(builder.build(make_project(tmp_path, **spec)).key)
        time.sleep(0.02)  # mtimes distintos
    left = sorted(p.name for p in (tmp_path / "preview-audio").glob("*.m4a"))
    assert len(left) == 4 and not any(keys[0] in name for name in left)
    assert not (tmp_path / "preview-audio" / f"sessao__{keys[0]}.json").exists()


# ---------- tarefas em segundo plano ----------


def wait_for(status, state: str, timeout: float = 10.0) -> None:
    end = time.time() + timeout
    while status.state != state and time.time() < end:
        time.sleep(0.01)
    assert status.state == state, status.error


def test_tasks_build_in_the_background_and_then_serve_the_cache(tmp_path):
    builder, runner = make_builder(tmp_path)
    tasks = PreviewAudioTasks()
    project = make_project(tmp_path, **SESSION)

    status = tasks.request(project, lambda real_runner, log: builder)
    assert status.key == builder.key(project)
    wait_for(status, "ready")
    assert status.audio is not None and status.audio.path.exists()
    done = len(runner.commands)

    assert tasks.request(project, lambda real_runner, log: builder) is status  # a mesma, sem refazer
    assert tasks.status(project.name, status.key, builder) is status
    assert len(runner.commands) == done
    assert tasks.status(project.name, "chave-desconhecida", builder) is None

    fresh = PreviewAudioTasks()  # servidor reiniciado: a mixagem em disco ainda vale
    assert fresh.request(project, lambda real_runner, log: builder).state == "ready"


def test_tasks_report_the_failure_and_try_again_on_the_next_request(tmp_path):
    builder, runner = make_builder(tmp_path)
    tasks = PreviewAudioTasks()
    broken = make_project(tmp_path, timeline=[{"type": "clip", "src": "cam1.mp4", "start": 0, "end": 4}])
    original = runner.on_run
    runner.on_run = lambda command: (_ for _ in ()).throw(RuntimeError("disco cheio"))

    status = tasks.request(broken, lambda real_runner, log: builder)
    wait_for(status, "failed")
    assert "disco cheio" in (status.error or "")

    runner.on_run = original
    retry = tasks.request(broken, lambda real_runner, log: builder)
    assert retry is not status
    wait_for(retry, "ready")


def gated_runner(runner: RecordingRunner):
    """Faz o ffmpeg falso esperar um portão, e anota quantos comandos rodam ao mesmo tempo."""
    gate = threading.Event()
    started = threading.Event()
    running: list[int] = []
    original = runner.on_run

    def slow(command):
        running.append(1)
        started.set()
        assert len(running) == 1, "duas mixagens do mesmo projeto rodaram juntas"
        gate.wait(5)
        original(command)
        running.pop()

    runner.on_run = slow
    return gate, started


def spec_with_gain(gain: float) -> dict:
    return {**SESSION, "audio": {**SESSION["audio"], "voice_gain": gain}}


def test_mixes_of_the_same_project_wait_for_each_other(tmp_path):
    builder, runner = make_builder(tmp_path)
    tasks = PreviewAudioTasks()
    gate, started = gated_runner(runner)
    first = tasks.request(make_project(tmp_path, **SESSION), lambda r, log: builder)
    assert started.wait(5)  # a primeira já está dentro do ffmpeg
    second = tasks.request(make_project(tmp_path, **spec_with_gain(0.5)), lambda r, log: builder)
    time.sleep(0.1)
    assert first.state == "building" and second.state == "building"
    gate.set()
    wait_for(first, "ready")
    wait_for(second, "ready")


def test_a_queued_mix_is_dropped_when_a_newer_edit_of_the_project_arrives(tmp_path):
    builder, runner = make_builder(tmp_path)
    tasks = PreviewAudioTasks()
    gate, started = gated_runner(runner)
    first = tasks.request(make_project(tmp_path, **SESSION), lambda r, log: builder)
    assert started.wait(5)
    superseded = tasks.request(make_project(tmp_path, **spec_with_gain(0.5)), lambda r, log: builder)
    newest = tasks.request(make_project(tmp_path, **spec_with_gain(0.7)), lambda r, log: builder)
    gate.set()
    wait_for(first, "ready")  # a que já rodava termina e fica no cache
    wait_for(superseded, "failed")
    assert "mais nova" in (superseded.error or "")
    wait_for(newest, "ready")
    assert builder.cached("sessao", superseded.key) is None  # a intermediária nunca foi mixada
    assert builder.cached("sessao", newest.key) is not None


def test_a_graph_too_long_for_the_command_line_goes_to_a_file(tmp_path):
    """Um projeto com centenas de trechos passa dos ~32 mil caracteres que a linha de comando do Windows aceita:
    o grafo longo vai para um arquivo da pasta do trabalho, o curto continua inline."""
    from types import SimpleNamespace

    from dmaker.filtergraph.common import Inputs
    from dmaker.pipeline.assembly import INLINE_GRAPH_LIMIT, graph_args

    ctx = SimpleNamespace(job_dir=tmp_path)
    inputs = Inputs()
    inputs.add("a.wav")
    assert graph_args(ctx, inputs, ["[0:a]anull[a]"], "g.txt") == [
        "-i",
        "a.wav",
        "-filter_complex",
        "[0:a]anull[a]",
    ]

    lines = [f"[{i % 3}:a]anull[a{i}]" for i in range(INLINE_GRAPH_LIMIT // 10)]
    args = graph_args(ctx, inputs, lines, "g.txt")
    assert "-filter_complex" not in args and args[-1] == str(tmp_path / "g.txt")
    assert (tmp_path / "g.txt").read_text(encoding="utf-8") == ";".join(lines)


def test_cache_directory_lives_under_the_data_dir():
    assert config.PREVIEW_AUDIO_DIR.is_relative_to(config.CACHE_DIR)
    assert re.fullmatch(r"preview-audio", config.PREVIEW_AUDIO_DIR.name)
