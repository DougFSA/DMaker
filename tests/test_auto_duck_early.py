"""A chave do Auto Duck medida antes dos mezaninos (DMK-69): a conta pura da câmera por clipe e o plano com `RecordingRunner`,
probe falso e sintetizador falso, sem ffmpeg de verdade."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.domain.auto_duck import AutoDuck, camera_runs, clip_runs
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.pipeline.narration import NarrationService
from dmaker.pipeline.preview_audio import PreviewAudioBuilder
from dmaker.pipeline.voiceover import narration_text

from .conftest import fake_ffmpeg_output
from .test_narration import FakeSynthesizer
from .test_pipeline_unit import LOUDNORM_JSON
from .test_preview_audio import graph_of, make_prober, make_project, no_audio_link, pieces

# ---------- as contas puras ----------


def test_a_clip_hears_only_the_part_of_the_file_it_plays_and_the_speed_squeezes_it():
    file_runs = [(10.0, 14.0), (20.0, 22.0)]
    # o clipe cai em 2..6 s da linha do tempo, ouve o arquivo a partir de 12 s, na velocidade normal
    assert clip_runs(file_runs, 2.0, 6.0, 12.0, 1.0) == [(2.0, 4.0)]
    # a 2x ele consome 8 s de fonte (12 a 20) em 4 s: o trecho de 12 a 14 vira 1 s
    assert clip_runs(file_runs, 2.0, 6.0, 12.0, 2.0) == [(2.0, 3.0)]
    assert clip_runs(file_runs, 2.0, 6.0, 30.0, 1.0) == []


def test_the_camera_key_waits_for_the_lead_of_a_shifted_sound():
    file_runs = [(0.0, 2.0)]
    # o som deslocado começa 1 s depois do clipe (lead = 1 s de fonte): o trecho de 0 a 2 s do arquivo cai em 3..5 s
    assert camera_runs(file_runs, (2.0, 8.0), 1.0, 0.0, lead=1.0) == [(3.0, 5.0)]
    assert camera_runs(file_runs, (2.0, 8.0), 1.0, 0.0) == [(2.0, 4.0)]
    # a 2x o silêncio de 1 s de fonte dura 0,5 s da linha do tempo
    assert camera_runs([(0.0, 4.0)], (2.0, 8.0), 2.0, 0.0, lead=1.0) == [(2.5, 4.5)]


def test_a_clip_that_starts_the_file_late_maps_back_to_its_own_start():
    assert camera_runs([(100.0, 103.0)], (10.0, 20.0), 1.0, 101.0) == [(10.0, 12.0)]


def test_only_the_rules_that_need_the_mix_wait_for_it():
    early = [("A2", "A1"), ("MUS", "A1"), ("A1", "NAR"), ("MUS", "A2"), ("A2", "NAR"), ("A2", "SFX")]
    # a chave A1 e a externa vêm de arquivo, e MUS/NAR/VO/SFX sob um fundo externo vêm de uma cópia que não usa os mezaninos
    expected = [True, True, False, True, True, True]
    assert [AutoDuck(background=b, key=k).measured_early for b, k in early] == expected
    assert not AutoDuck(background="MUS", key="VO").measured_early
    assert not AutoDuck(background="SFX", key="NAR").measured_early


# ---------- o plano ----------


def report(bursts: list[tuple[float, float]], seconds: float, level: float = -10.0) -> str:
    """Um relatório do `astats` com uma linha por janela de 20 ms: `level` dentro das rajadas e muito baixo fora."""
    lines = []
    for window in range(round(seconds * 50)):
        instant = window * 0.02
        inside = any(first <= instant < last for first, last in bursts)
        lines.append(f"lavfi.astats.Overall.RMS_level={level if inside else -80.0}")
    return "\n".join(lines)


class LevelRunner(RecordingRunner):
    """Devolve o relatório de nível que o arquivo medido tem (pelo nome dele no comando) e registra a ordem das passadas."""

    def __init__(self, reports: dict[str, str], default: str):
        super().__init__(on_run=fake_ffmpeg_output, capture_stderr=LOUDNORM_JSON)
        self.reports = reports
        self.default = default

    def capture(self, args, label="ffmpeg"):
        self.commands.append(["ffmpeg", *args, f"#{label}"])
        if "Auto Duck" not in label:
            return self.capture_stderr
        text = " ".join(args)
        for name, content in self.reports.items():
            if name in text:
                return content
        return self.default

    def level_passes(self) -> list[int]:
        """As posições, na lista de comandos, das passadas de nível."""
        return [i for i, c in enumerate(self.commands) if c[-1].startswith("#nível")]


def project_with(tmp_path: Path, ducks: list[dict], clips: list[dict] | None = None, **audio):
    return make_project(
        tmp_path,
        sources={"cam1": {"src": "cam1.mp4"}, "mesa": {"src": "mesa.wav", "sync": 0.0}},
        timeline=clips
        or [
            {"type": "clip", "source": "cam1", "start": 0, "end": 4},
            {"type": "clip", "source": "cam1", "start": 4, "end": 8, "transition": {"type": "cut"}},
        ],
        audio={"tracks": [{"source": "mesa"}], "normalize": "off", "ducks": ducks, **audio},
    )


def builder_for(tmp_path: Path, runner: RecordingRunner, **kwargs) -> PreviewAudioBuilder:
    return PreviewAudioBuilder(
        runner=runner,
        prober=make_prober,
        offset_finder=no_audio_link,
        cache_dir=tmp_path / "preview-audio",
        jobs_dir=tmp_path / "jobs",
        **kwargs,
    )


def ducked_pieces(runner: RecordingRunner) -> list[int]:
    """Quais pedaços (clipes) levam a curva do Auto Duck no grafo."""
    return [i for i, command in enumerate(pieces(runner)) if "pow(10" in graph_of(command)]


RULE = {"background": "A2", "key": "A1", "amount_db": -12}


def test_an_external_track_ducks_under_the_camera_inside_each_clip_piece(tmp_path):
    runner = LevelRunner({"cam1.mp4": report([(2.0, 3.0), (5.0, 6.0)], 400)}, report([], 400))
    builder_for(tmp_path, runner).build(project_with(tmp_path, [RULE]))
    assert ducked_pieces(runner) == [
        0,
        1,
    ]  # a chave soa em 2..3 s e 5..6 s: cada clipe recebe o pedaço da curva dele
    # a curva do primeiro clipe: desce 0,5 s antes de 2 s e a chave dura até 3 s; ele só tem a ponta antes de 4 s
    first = graph_of(pieces(runner)[0])
    assert "volume='pow(10" in first


def test_a_clip_the_key_never_reaches_keeps_the_same_piece_as_without_a_rule(tmp_path):
    runner = LevelRunner({"cam1.mp4": report([(2.0, 3.0)], 400)}, report([], 400))
    builder_for(tmp_path, runner).build(project_with(tmp_path, [RULE]))
    assert ducked_pieces(runner) == [
        0
    ]  # o segundo clipe (4..8 s) não ouve a chave: sem filtro, com o hash de sempre
    plain = LevelRunner({}, report([], 400))
    builder_for(tmp_path / "x", plain).build(project_with(tmp_path, []))
    assert Path(pieces(plain)[1][-1]).name == Path(pieces(runner)[1][-1]).name


def test_the_key_is_measured_before_any_piece_exists(tmp_path):
    runner = LevelRunner({"cam1.mp4": report([(2.0, 3.0)], 400)}, report([], 400))
    builder_for(tmp_path, runner).build(project_with(tmp_path, [RULE]))
    first_piece = next(i for i, c in enumerate(runner.commands) if Path(c[-1]).parent.name == "pieces")
    assert runner.level_passes()[0] < first_piece


def test_the_same_camera_file_used_by_two_clips_and_two_rules_is_measured_once(tmp_path):
    runner = LevelRunner({"cam1.mp4": report([(2.0, 3.0)], 400)}, report([], 400))
    ducks = [RULE, {"background": "MUS", "key": "A1"}]
    project = project_with(tmp_path, ducks, music={"src": "musica.mp3", "volume": 0.3})
    builder_for(tmp_path, runner).build(project)
    camera_passes = [c for c in runner.commands if c[-1].startswith("#nível") and "cam1.mp4" in " ".join(c)]
    assert len(camera_passes) == 1


def test_a_muted_clip_is_not_a_key(tmp_path):
    clips = [{"type": "clip", "source": "cam1", "start": 0, "end": 4, "mute": True}]
    runner = LevelRunner({"cam1.mp4": report([(0.0, 4.0)], 400)}, report([], 400))
    builder_for(tmp_path, runner).build(project_with(tmp_path, [RULE], clips=clips))
    assert ducked_pieces(runner) == []
    assert not any("cam1.mp4" in " ".join(c) for c in runner.commands if c[-1].startswith("#nível"))


def test_without_a_rule_nothing_is_measured(tmp_path):
    runner = LevelRunner({}, report([], 400))
    builder_for(tmp_path, runner).build(project_with(tmp_path, []))
    assert runner.level_passes() == []
    assert ducked_pieces(runner) == []


@pytest.mark.parametrize(
    ("key", "audio"),
    [
        ("VO", {"voiceover": [{"src": "locucao.wav", "start": 0.0}]}),
        ("MUS", {"music": {"src": "musica.mp3", "volume": 0.3, "ducking": False}}),
        ("NAR", {"narration": [{"text": "Olá, este é o DMaker.", "start": 0.0}]}),
    ],
)
def test_the_recorded_voice_the_music_and_the_narration_duck_an_external_track_before_the_pieces(
    tmp_path, key, audio
):
    runner = LevelRunner({}, report([(1.0, 2.0)], 400))  # o relatório vale para a cópia da chave pedida
    extra = {}
    if key == "NAR":
        extra["narrator"] = lambda narration_runner: NarrationService(
            FakeSynthesizer(), narration_runner, cache_dir=tmp_path / "voice-cache"
        )
    project = project_with(
        tmp_path,
        [{"background": "A2", "key": key, "amount_db": -12}],
        clips=[{"type": "clip", "source": "cam1", "start": 0, "end": 4, "mute": True}],
        **audio,
    )
    builder = builder_for(tmp_path, runner, **extra)
    if key == "NAR":  # a prévia só usa a narração que já foi falada
        narration = project.audio.narration[0]
        builder._narration().render(
            narration_text(project, narration),
            tmp_path / "falada.wav",
            None,
            language=narration.language,
            speed=narration.speed,
            instruct=narration.instruct,
            seed=narration.seed,
            brand=project.brand,
        )
    builder.build(project)
    assert ducked_pieces(runner) == [0]
    first_piece = next(i for i, c in enumerate(runner.commands) if Path(c[-1]).parent.name == "pieces")
    assert runner.level_passes()[0] < first_piece


def test_a_rule_that_does_not_need_the_pieces_but_ducks_a_mix_track_still_waits_for_the_mix(tmp_path):
    runner = LevelRunner({}, report([(1.0, 2.0)], 400))
    ducks = [{"background": "MUS", "key": "VO", "amount_db": -12}]
    audio = {
        "music": {"src": "musica.mp3", "volume": 0.3},
        "voiceover": [{"src": "locucao.wav", "start": 0.0}],
    }
    builder_for(tmp_path, runner).build(project_with(tmp_path, ducks, **audio))
    first_piece = next(i for i, c in enumerate(runner.commands) if Path(c[-1]).parent.name == "pieces")
    assert runner.level_passes()[0] > first_piece  # como antes: a medida lê a mixagem depois dos pedaços


def test_the_effects_key_is_measured_with_the_spec_volume_before_leveling(tmp_path):
    from dmaker.domain.spec import Project
    from dmaker.filtergraph.sfx import FALLBACK_VOICE_PEAK_DB, sfx_gain_db
    from dmaker.pipeline.context import RenderContext, RenderOptions
    from dmaker.pipeline.sfx import unleveled_effects

    (tmp_path / "estalo.wav").write_bytes(b"x")
    project = Project.model_validate(
        {
            "name": "efeitos",
            "timeline": [{"type": "card", "title": "x", "duration": 5.0}],
            "audio": {"sfx": [{"sound": "estalo.wav", "at": 1.0, "volume": 0.5}], "sfx_gain_db": -3.0},
        }
    )
    project.base_dir = tmp_path
    ctx = RenderContext.__new__(RenderContext)
    ctx.project, ctx.options, ctx.log = project, RenderOptions(dry_run=True), lambda message: None
    tracks = unleveled_effects(ctx, [(0.0, 5.0)])
    assert [(t.at, round(t.gain_db, 3)) for t in tracks] == [
        (1.0, round(sfx_gain_db(0.5, FALLBACK_VOICE_PEAK_DB) - 3.0, 3))
    ]
