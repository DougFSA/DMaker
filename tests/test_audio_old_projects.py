"""Projeto de vídeo antigo continua igual: o mesmo hash de mezanino, o mesmo grafo de áudio e a mesma spec salva.

Os valores fixos abaixo foram tirados da `develop` antes do chamado do projeto só de áudio (DMK-64); se um deles
mudar, a receita de um projeto que já existe mudou e o `MEZZ_VERSION` tem de subir com uma justificativa.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from dmaker.domain.spec import AudioSettings, ClipSegment, Music, MusicSpan, Project
from dmaker.filtergraph.audio import audio_graph
from dmaker.filtergraph.common import Inputs
from dmaker.pipeline.preview_audio import mix_recipe, piece_recipe
from dmaker.pipeline.segments import MEZZ_VERSION

# o que o `model_dump` de um clipe entrega ao hash do mezanino: nenhum campo novo entrou
CLIP_HASH_FIELDS = [
    "audio_fade",
    "audio_mode",
    "color",
    "end",
    "fade_in",
    "fade_out",
    "label",
    "look",
    "matte",
    "mute",
    "reframe",
    "source",
    "speed",
    "src",
    "start",
    "transition",
    "type",
    "volume",
]
MIX_GRAPH_SHA256 = "d6df6377c39512cb179a756e3e201befb8601cc393f3e5c5515f1d69e8af47c3"


class Voice:
    def __init__(self, name: str, start: float = 0.0):
        self.path, self.start, self.volume = Path(name), start, 1.0
        self.offset, self.duration = 0.5, 5.0


def test_the_mezzanine_recipe_version_did_not_move():
    assert MEZZ_VERSION == "m7"


def test_the_segment_dump_that_feeds_the_mezzanine_hash_has_no_new_field():
    clip = ClipSegment(src="take.mp4", start=1, end=5)
    assert sorted(clip.model_dump(mode="json")) == CLIP_HASH_FIELDS
    assert sorted(piece_recipe(clip)) == sorted(
        [
            "type",
            "src",
            "source",
            "start",
            "end",
            "speed",
            "volume",
            "mute",
            "fade_in",
            "fade_out",
            "audio_fade",
            "audio_mode",
        ]
    )


def test_the_audio_graph_of_a_video_project_is_the_same_string_as_before():
    audio = AudioSettings(
        music=Music(src="m.wav", spans=[MusicSpan(start=0, end=10, fade_out=2)]), target_lufs=-14
    )
    inputs, lines = Inputs(), []
    inputs.add("clips.mov")
    lines.append("[0:a]aresample=48000[ta0]")
    audio_graph(
        lines,
        inputs,
        "[ta0]",
        audio,
        Path("m.wav"),
        30.0,
        measured={
            "input_i": "-23.5",
            "input_tp": "-4.0",
            "input_lra": "7.0",
            "input_thresh": "-33.9",
            "target_offset": "0.3",
        },
        narrations=[Voice("n.wav", 2)],
        voice_files=[Voice("v.wav", 1)],
    )
    assert len(lines) == 12
    assert hashlib.sha256(";".join(lines).encode()).hexdigest() == MIX_GRAPH_SHA256


def test_an_old_spec_saves_the_same_bytes_and_the_preview_recipe_has_no_new_key():
    project = Project.model_validate(
        {
            "name": "antigo",
            "timeline": [{"type": "clip", "src": "take.mp4"}],
            "audio": {"music": {"src": "m.wav"}, "target_lufs": -14},
        }
    )
    text = project.to_bytes().decode("utf-8")
    assert "audio_format" not in text and '"metadata"' not in text and "markers" not in text
    assert Project.model_validate_json(text).to_bytes() == project.to_bytes()
    assert sorted(mix_recipe(project)) == ["audio", "overlays", "sources", "timeline"]
