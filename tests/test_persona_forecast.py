"""A previsão do tempo das personas realistas de um projeto: funções puras, sem motor e sem disco."""

from __future__ import annotations

from dmaker.domain.persona import estimate_speech_seconds
from dmaker.domain.spec import Project
from dmaker.persona.forecast import forecast_message, realistic_clip_seconds, total_estimate_seconds


def project_of(timeline: list[dict], overlays: list[dict] | None = None) -> Project:
    return Project.model_validate(
        {
            "name": "p",
            "output": {"preset": "instagram/reels"},
            "timeline": timeline,
            "overlays": overlays or [],
        }
    )


def kind_of(persona_id: str) -> str:
    return "realistic" if persona_id.startswith("real") else "2d"


def no_audio(_name: str) -> float | None:
    return None


SIX_SECONDS = "x" * 90  # uns 6 s de fala pela régua do QA


def test_only_realistic_personas_count_and_the_tail_and_fixed_duration_follow_the_segment():
    project = project_of(
        [
            {"type": "persona", "persona": "real-ana", "speech": {"text": SIX_SECONDS}, "tail": 0.5},
            {"type": "persona", "persona": "real-bia", "speech": {"text": SIX_SECONDS}, "duration": 9.0},
            {"type": "persona", "persona": "cartoon", "speech": {"text": SIX_SECONDS}},
        ],
        [{"type": "persona", "persona": "real-ana", "speech": {"text": "y" * 45}, "start": 1.0, "end": 3.0}],
    )
    assert realistic_clip_seconds(project, kind_of, no_audio) == [
        estimate_speech_seconds(SIX_SECONDS) + 0.5,
        9.0,
        2.0,
    ]


def test_the_same_speech_of_the_same_persona_is_one_clip_because_the_second_comes_from_the_cache():
    speech = {"text": SIX_SECONDS}
    project = project_of(
        [
            {"type": "persona", "persona": "real-ana", "speech": speech},
            {"type": "persona", "persona": "real-ana", "speech": speech},
        ]
    )
    assert len(realistic_clip_seconds(project, kind_of, no_audio)) == 1


def test_a_given_audio_file_uses_its_real_duration():
    project = project_of(
        [{"type": "persona", "persona": "real-ana", "speech": {"audio": "fala.wav"}, "tail": 0}]
    )
    assert realistic_clip_seconds(project, kind_of, lambda name: 4.0) == [4.0]


def test_each_clip_pays_its_own_fixed_cost():
    assert total_estimate_seconds([6.0, 6.0], has_gpu=True) == 2 * (150 + 4.5 * 150)


def test_the_message_is_a_ceiling_and_says_the_device_and_none_without_realistic_personas():
    assert forecast_message([], has_gpu=True) is None
    gpu = forecast_message([6.0], has_gpu=True) or ""
    assert gpu.startswith("persona realista: até 13 min 45 s no total (1 clipe, GPU integrada)")
    assert "se nada estiver em cache" in gpu and "programas pesados" in gpu
    cpu = forecast_message([6.0, 6.0], has_gpu=False) or ""
    assert "2 clipes" in cpu and "só CPU" in cpu
