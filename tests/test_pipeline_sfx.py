"""Efeitos sonoros no pipeline, com ffmpeg falso: do plano da spec à medição da voz e ao grafo da montagem."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from dmaker import config
from dmaker.domain.spec import Project
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.sfx import SfxNotFound

from .test_pipeline_unit import LOUDNORM_JSON, SILENT_JSON, fake_prober, touch_output

# voz a -24 LUFS com pico em -8 dBTP: o ganho para -14 LUFS (+10 dB) levaria o pico a +2, acima do teto de
# -1,5, então a régua dos efeitos é -1,5 - 10 = -11,5 dBFS
VOICE_JSON = json.dumps(
    {
        "input_i": "-24.0",
        "input_tp": "-8.0",
        "input_lra": "5.0",
        "input_thresh": "-34.0",
        "target_offset": "0.1",
    }
)
REFERENCE_DB = -11.5
EXPECTED_GAIN_DB = REFERENCE_DB - 6.0 + 3.0  # 6 dB abaixo da régua, partindo do pico de -3 dBFS da biblioteca


def _spec(**audio) -> dict:
    return {
        "name": "sfx_unit",
        "output": {"preset": "instagram/reels"},
        "timeline": [
            {"type": "clip", "src": "take.mp4", "start": 0, "end": 6},
            {
                "type": "card",
                "title": "Parte dois",
                "duration": 4,
                "motion": "none",
                "transition": {"type": "fade", "duration": 0.5, "sound": True},
            },
        ],
        "overlays": [{"type": "text", "text": "Gancho", "start": 2.0, "end": 5.0, "sound": "pop"}],
        "audio": {"normalize": "two-pass", **audio},
    }


def _pipeline(tmp_path: Path, spec: dict, runner: RecordingRunner, **options) -> RenderPipeline:
    (tmp_path / "take.mp4").write_bytes(b"x")  # o probe é falso; só precisa existir
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    return RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=tmp_path / "out.mp4", no_captions=True, **options),
        runner=runner,
        prober=fake_prober,
        cache_dir=tmp_path / "mez",
        jobs_dir=tmp_path / "jobs",
        output_dir=tmp_path / "output",
    )


def _graph(result) -> str:
    return (result.job_dir / "graph.txt").read_text(encoding="utf-8")


def _captures(runner: RecordingRunner) -> list[list[str]]:
    """Os comandos das passadas de medição (as que passam por `capture`): a voz sozinha e a mixagem."""
    return [command for command in runner.commands if "null" in command and "-filter_complex" in command]


def _filters(command: list[str]) -> str:
    return command[command.index("-filter_complex") + 1]


def test_every_sound_source_reaches_the_final_graph_at_its_exact_sample(tmp_path):
    spec = _spec(sfx=[{"sound": "whoosh", "at": 3.25}])
    runner = RecordingRunner(on_run=touch_output, capture_stderr=VOICE_JSON)
    result = _pipeline(tmp_path, spec, runner).run()
    graph = _graph(result)
    delays = re.findall(r"volume=(-?\d+\.\d+)dB,adelay=(\d+)S:all=1\[sfx\d+\]", graph)
    # 2 s do texto, 3,25 s do whoosh solto e 5,5 s do começo da transição (o cartão entra 0,5 s antes dos 6 s)
    assert [int(samples) for _, samples in delays] == [96_000, 156_000, 264_000]
    assert {float(db) for db, _ in delays} == {EXPECTED_GAIN_DB}
    assert "[a_fx]loudnorm" in graph and "amix=inputs=4:duration=first" in graph


def test_the_voice_is_measured_alone_and_the_loudness_pass_includes_the_effects(tmp_path):
    (tmp_path / "musica.wav").write_bytes(b"x")
    runner = RecordingRunner(on_run=touch_output, capture_stderr=VOICE_JSON)
    spec = _spec(music={"src": "musica.wav"}, sfx=[{"sound": "click", "at": 1.0}])
    _pipeline(tmp_path, spec, runner).run()
    voice_pass, loudness_pass = _captures(runner)
    assert "[vmeas]" in _filters(voice_pass) and "sidechaincompress" not in _filters(voice_pass)
    assert not any("musica.wav" in arg or str(config.SFX_DIR) in arg for arg in voice_pass)  # só a voz
    assert "[ameas]" in _filters(loudness_pass) and "sidechaincompress" in _filters(loudness_pass)
    assert any(str(config.SFX_DIR) in arg for arg in loudness_pass)  # o loudnorm final mede com os efeitos


def test_no_effects_means_no_extra_measurement_and_the_same_commands(tmp_path):
    spec = _spec()
    spec["overlays"][0].pop("sound")
    spec["timeline"][1]["transition"].pop("sound")
    runner = RecordingRunner(on_run=touch_output, capture_stderr=LOUDNORM_JSON)
    result = _pipeline(tmp_path, spec, runner).run()
    assert len(_captures(runner)) == 1  # só a medição de loudness de sempre
    assert "sfx" not in _graph(result) and "a_fx" not in _graph(result)


def test_without_normalization_the_reference_is_the_measured_peak(tmp_path):
    runner = RecordingRunner(on_run=touch_output, capture_stderr=VOICE_JSON)
    spec = _spec(sfx=[{"sound": "whoosh", "at": 1.0}], normalize="off")
    result = _pipeline(tmp_path, spec, runner).run()
    gains = {float(db) for db in re.findall(r"volume=(-?\d+\.\d+)dB,adelay", _graph(result))}
    assert gains == {-8.0 - 6.0 + 3.0}  # sem loudnorm não há limitador: vale o pico medido, -8 dBTP


def test_a_silent_voice_falls_back_to_a_typical_peak(tmp_path):
    runner = RecordingRunner(on_run=touch_output, capture_stderr=SILENT_JSON)
    result = _pipeline(tmp_path, _spec(sfx=[{"sound": "whoosh", "at": 1.0}]), runner).run()
    gains = {float(db) for db in re.findall(r"volume=(-?\d+\.\d+)dB,adelay", _graph(result))}
    assert gains == {-6.0 - 6.0 + 3.0}


def test_a_dry_run_measures_nothing_and_uses_the_typical_peak(tmp_path):
    runner = RecordingRunner()
    result = _pipeline(tmp_path, _spec(sfx=[{"sound": "impact", "at": 1.0}]), runner, dry_run=True).run()
    assert _captures(runner) == []
    gains = {float(db) for db in re.findall(r"volume=(-?\d+\.\d+)dB,adelay", _graph(result))}
    assert gains == {-9.0}


def test_a_missing_sound_fails_before_any_heavy_work_and_names_the_spec_entry(tmp_path):
    spec = _spec(sfx=[{"sound": "nao-existe.wav", "at": 1.0}])
    runner = RecordingRunner(on_run=touch_output, capture_stderr=VOICE_JSON)
    with pytest.raises(SfxNotFound, match=r"audio\.sfx\[0\].*nao-existe\.wav"):
        _pipeline(tmp_path, spec, runner).run()
    assert runner.commands == []  # nenhum mezanino foi gerado


def test_a_sound_by_path_is_relative_to_the_project(tmp_path):
    (tmp_path / "meu.wav").write_bytes(b"x")
    runner = RecordingRunner(on_run=touch_output, capture_stderr=VOICE_JSON)
    _pipeline(tmp_path, _spec(sfx=[{"sound": "meu.wav", "at": 1.0}]), runner).run()
    assert str(tmp_path / "meu.wav") in " ".join(runner.commands[-2])  # entrada da montagem final


def test_a_partial_render_drops_the_absolute_effects(tmp_path):
    spec = _spec(sfx=[{"sound": "whoosh", "at": 3.25}])
    spec["timeline"].append({"type": "card", "title": "Fim", "duration": 2, "motion": "none"})
    runner = RecordingRunner(on_run=touch_output, capture_stderr=VOICE_JSON)
    result = _pipeline(tmp_path, spec, runner, segments=(0, 1)).run()
    graph = _graph(result)
    assert "156000S" not in graph  # os 3,25 s da spec não valem num recorte
    assert "264000S" in graph  # o som da transição acompanha o trecho e continua valendo


def test_lint_warns_about_an_effect_after_the_end(tmp_path):
    spec = _spec(sfx=[{"sound": "whoosh", "at": 90}, {"sound": "pop", "at": 1, "volume": 0}])
    runner = RecordingRunner(on_run=touch_output, capture_stderr=VOICE_JSON)
    result = _pipeline(tmp_path, spec, runner).run()
    assert any("audio.sfx[0]" in w and "depois do fim" in w for w in result.warnings)
    assert any("audio.sfx[1]" in w and "volume 0" in w for w in result.warnings)
