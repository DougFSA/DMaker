"""Audiograma (DMK-34): a sobreposição `audiogram`, a voz vinda de arquivo de áudio (`audio.voiceover`), o grafo
de cada estilo e o modelo "audiograma". Sem ffmpeg: o que se executa de verdade está em `test_audiogram_render.py`."""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError

from dmaker.config import TEMPLATES_DIR
from dmaker.domain.audiogram import (
    BAR_COUNT,
    BARS_PER_HALF,
    STYLE_ASPECT,
    RingLayout,
    audiogram_size,
    bars_layout,
    project_has_voice,
    resolve_follow,
)
from dmaker.domain.audiogram_template import BLURRED_COVER_FILTER, prepare_audiogram
from dmaker.domain.presets import SafeZone, get_preset
from dmaker.domain.regions import region_pixels, resolve_region
from dmaker.domain.spec import AudiogramOverlay, ImageOverlay, Project, VoiceoverClip
from dmaker.domain.templates import TemplateError, find_template, render_template, template_summary
from dmaker.filtergraph import audiogram as audiogram_module
from dmaker.filtergraph.audio import AudioTaps, audio_graph, voice_file_streams
from dmaker.filtergraph.audiogram import (
    STYLES,
    AudiogramStyle,
    DrawContext,
    ResolvedAudiogram,
    audiogram_graph,
    audiogram_style,
    normalization_gain_db,
    smoothing_frames,
)
from dmaker.filtergraph.common import Inputs
from dmaker.media.ffmpeg import FFmpegCommand, RecordingRunner
from dmaker.media.probe import MediaInfo
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline.lint import lint
from dmaker.pipeline.projects import describe_templates, with_media_durations
from dmaker.pipeline.voicefiles import (
    PreparedVoiceFile,
    play_length,
    prepare_voice_files,
    voice_file_playtimes,
    voice_file_warnings,
)
from dmaker.text.captions import Cue, Word
from dmaker.text.transcribe import Transcript
from dmaker.visuals.audiogram import bars_ramp, ring_assets, style_assets

MINIMAL = {"name": "ag", "timeline": [{"type": "card", "flat": True, "duration": 10}]}


def _project(**overrides) -> Project:
    return Project.model_validate({**MINIMAL, **overrides})


# ---------- a spec e o contrato com o schema ----------


def test_the_audiogram_overlay_has_sensible_defaults_and_is_part_of_the_overlay_union():
    project = _project(overlays=[{"type": "audiogram"}])
    overlay = project.overlays[0]
    assert isinstance(overlay, AudiogramOverlay)
    assert (overlay.style, overlay.follow, overlay.color, overlay.position) == ("bars", "auto", None, None)
    assert overlay.height is None and overlay.inner_radius == 0.6 and overlay.end is None


@pytest.mark.parametrize(
    ("overlay", "message"),
    [
        ({"x": 0.5}, "juntos"),
        ({"region": "r", "x": 0.5, "y": 0.5}, "region"),
        ({"region": "r", "position": "top"}, "region"),
        ({"start": 5, "end": 3}, "end precisa ser maior"),
        ({"style": "pizza"}, "style"),
        ({"follow": "tudo"}, "follow"),
        ({"inner_radius": 1.2}, "inner_radius"),
    ],
)
def test_the_audiogram_overlay_rejects_inconsistent_fields(overlay, message):
    regions = {"r": {"x": 0.5, "y": 0.5, "width": 0.5, "height": 0.2}}
    with pytest.raises(ValidationError, match=message):
        _project(overlays=[{"type": "audiogram", **overlay}], regions=regions)


def test_an_audiogram_has_no_entry_sound():
    """O brief: o audiograma não leva `sound` (extra = forbid)."""
    with pytest.raises(ValidationError, match="sound"):
        _project(overlays=[{"type": "audiogram", "sound": True}])


def test_a_voiceover_clip_needs_a_path_and_a_coherent_range():
    clip = VoiceoverClip(src="fala.mp3")
    assert (clip.start, clip.offset, clip.end, clip.volume) == (0.0, 0.0, None, 1.0)
    with pytest.raises(ValidationError, match="end.*offset"):
        VoiceoverClip(src="fala.mp3", offset=5, end=3)
    with pytest.raises(ValidationError):
        VoiceoverClip(src="")


def test_the_json_schema_publishes_the_new_fields():
    """O `spec_schema` do MCP sai daqui: quem monta a spec descobre o audiograma e o voiceover pelo esquema."""
    defs = Project.model_json_schema()["$defs"]
    assert {
        "style",
        "follow",
        "color",
        "position",
        "x",
        "y",
        "region",
        "width",
        "height",
        "inner_radius",
    } <= set(defs["AudiogramOverlay"]["properties"])
    assert defs["AudiogramOverlay"]["properties"]["style"]["enum"] == ["wave", "bars", "circle"]
    assert defs["AudiogramOverlay"]["properties"]["follow"]["enum"] == ["auto", "voice", "mix"]
    assert "sound" not in defs["AudiogramOverlay"]["properties"]
    assert set(defs["VoiceoverClip"]["properties"]) == {"src", "start", "offset", "end", "volume"}
    assert "voiceover" in defs["AudioSettings"]["properties"]
    assert defs["ImageOverlay"]["properties"]["shape"]["enum"] == ["rect", "circle"]


def test_the_mcp_schema_tool_publishes_the_new_fields():
    from dmaker.mcp_server import spec_schema

    defs = spec_schema()["$defs"]
    assert "AudiogramOverlay" in defs and "VoiceoverClip" in defs
    overlay_types = [
        option["$ref"].rsplit("/", 1)[-1]
        for option in spec_schema()["properties"]["overlays"]["items"]["oneOf"]
    ]
    assert "AudiogramOverlay" in overlay_types


def test_a_saved_project_with_an_audiogram_and_a_voiceover_reopens_equal(tmp_path):
    project = _project(
        regions={"anel": {"x": 0.5, "y": 0.4, "width": 0.7, "height": 0.4}},
        overlays=[
            {"type": "image", "src": "capa.png", "shape": "circle"},
            {
                "type": "audiogram",
                "style": "circle",
                "follow": "voice",
                "color": "accent",
                "region": "anel",
                "inner_radius": 0.55,
                "end": 9,
            },
        ],
        audio={"voiceover": [{"src": "fala.mp3", "start": 1, "offset": 2, "end": 8, "volume": 0.8}]},
    )
    path = project.save(tmp_path / "spec.json")
    again = Project.load(path)
    assert again.overlays == project.overlays and again.audio == project.audio
    assert json.loads(path.read_text(encoding="utf-8"))["audio"]["voiceover"][0]["offset"] == 2


def test_the_ui_api_loads_and_saves_a_project_with_an_audiogram_and_a_voiceover_without_losing_fields():
    """Abrir na interface um projeto com audiograma e voiceover não quebra: a API o carrega e o salva por
    inteiro (a interface edita o JSON cru que a API devolve)."""
    from fastapi.testclient import TestClient

    from dmaker import config
    from dmaker.ui import server

    spec = {
        "name": "ui-audiograma",
        "output": {"preset": "instagram/reels"},
        "regions": {"anel": {"x": 0.5, "y": 0.4, "width": 0.7, "height": 0.4}},
        "timeline": [{"type": "card", "flat": True, "duration": 10, "motion": "none"}],
        "overlays": [
            {"type": "image", "src": "capa.png", "shape": "circle"},
            {
                "type": "audiogram",
                "style": "circle",
                "follow": "voice",
                "region": "anel",
                "inner_radius": 0.55,
            },
        ],
        "audio": {"voiceover": [{"src": "fala.mp3", "start": 1, "offset": 2, "end": 8}], "normalize": "off"},
    }
    with TestClient(server.app) as client:
        assert client.put("/api/projects/ui-audiograma", json=spec).json()["ok"]
        got = client.get("/api/projects/ui-audiograma").json()["spec"]
        assert got["overlays"][1]["type"] == "audiogram" and got["overlays"][1]["inner_radius"] == 0.55
        assert got["overlays"][0]["shape"] == "circle"
        assert got["audio"]["voiceover"] == [
            {"src": "fala.mp3", "start": 1.0, "offset": 2.0, "end": 8.0, "volume": 1.0}
        ]
        assert client.put("/api/projects/ui-audiograma", json=got).json()[
            "ok"
        ]  # o que a tela devolve salva igual
        assert client.get("/api/projects/ui-audiograma").json()["spec"] == got
        assert (
            client.post("/api/projects/ui-audiograma/timeline", json={}).status_code == 200
        )  # a vista multitrilha abre
        summary = client.post("/api/projects/ui-audiograma/validate").json()
        assert any(
            "audio.voiceover[0].src: arquivo de áudio não encontrado" in w for w in summary["warnings"]
        )
    folder = config.PROJECTS_DIR / "ui-audiograma"
    for f in folder.glob("*"):
        f.unlink()
    folder.rmdir()


# ---------- o áudio que o desenho segue ----------


@pytest.mark.parametrize(
    ("follow", "has_voice", "expected"),
    [
        ("auto", True, "voice"),
        ("auto", False, "mix"),
        ("voice", False, "voice"),
        ("voice", True, "voice"),
        ("mix", True, "mix"),
        ("mix", False, "mix"),
    ],
)
def test_follow_auto_is_the_voice_when_there_is_one_and_the_mix_when_there_is_not(
    follow, has_voice, expected
):
    assert resolve_follow(follow, has_voice) == expected


CLIP = {"type": "clip", "src": "a.mp4"}


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"timeline": [CLIP]}, True),  # o áudio da câmera é voz
        ({"timeline": [{**CLIP, "mute": True}]}, False),
        ({"timeline": [{**CLIP, "volume": 0}]}, False),
        ({"timeline": [CLIP], "audio": {"mute_clips": True}}, False),
        ({"audio": {"voiceover": [{"src": "f.mp3"}]}}, True),
        ({"audio": {"voiceover": [{"src": "f.mp3", "volume": 0}]}}, False),
        ({"audio": {"narration": [{"text": "oi"}]}}, True),
        ({"audio": {"music": {"src": "m.mp3"}}}, False),  # só música: visualizador de música
        ({"audio": {"tracks": [{"source": "rec"}]}, "sources": {"rec": {"src": "r.wav"}}}, True),
        ({"overlays": [{"type": "video", "src": "pip.mp4", "volume": 1}]}, True),
        ({"overlays": [{"type": "video", "src": "pip.mp4", "volume": 0}]}, False),
    ],
)
def test_a_project_has_voice_when_some_voice_source_is_audible(overrides, expected):
    assert project_has_voice(_project(**overrides)) is expected


def test_a_clip_whose_source_has_no_audio_stream_is_not_voice():
    project = _project(timeline=[CLIP, CLIP])
    assert project_has_voice(project, [False, False]) is False
    assert project_has_voice(project, [False, True]) is True


# ---------- tamanho e geometria ----------


def test_audiogram_size_follows_the_style_proportion_unless_the_height_is_given():
    for style, aspect in STYLE_ASPECT.items():
        overlay = AudiogramOverlay(style=style, width=0.8)
        width, height = audiogram_size(overlay, 1080, 1920)
        assert width == 864 and width % 2 == 0 and height % 2 == 0
        assert (width, height) == (864, 864) if style == "circle" else abs(width / height - aspect) < 0.05
    explicit = audiogram_size(AudiogramOverlay(style="wave", width=0.5, height=0.1), 1080, 1920)
    assert explicit == (540, 192)


def test_the_circle_is_a_square_of_the_smaller_side_of_the_box():
    assert audiogram_size(AudiogramOverlay(style="circle", width=0.8, height=0.2), 1080, 1920) == (384, 384)


def test_a_region_gives_the_audiogram_its_box():
    project = _project(
        regions={"onda": {"x": 0.5, "y": 0.62, "width": 0.7222, "height": 0.1}},
        overlays=[{"type": "audiogram", "style": "wave", "region": "onda"}],
    )
    resolved = resolve_region(project.overlays[0], project.regions, 1080, 1920)
    assert (resolved.x, resolved.y, resolved.width, resolved.height, resolved.region) == (
        0.5,
        0.62,
        0.7222,
        0.1,
        None,
    )
    assert audiogram_size(resolved, 1080, 1920) == (780, 192)


def test_bars_layout_gives_every_bar_a_whole_number_of_columns():
    layout = bars_layout(907, 230)
    assert layout.pitch == 18 and layout.width == layout.pitch * BAR_COUNT == 864
    assert 0 < layout.gap < layout.pitch and layout.rest_fraction == pytest.approx(2 / 115)


def test_the_ring_layout_places_the_bars_between_the_inner_and_the_outer_radius():
    ring = RingLayout(780, 0.6)
    assert ring.outer == 389 and ring.inner == pytest.approx(233.4) and ring.span == pytest.approx(155.6)
    assert 0 < ring.rest_fraction < 0.05


# ---------- as imagens estáticas ----------


def test_the_bars_ramp_is_zero_at_the_centre_full_at_the_edges_and_blocks_the_gaps():
    layout = bars_layout(432, 100)
    ramp = np.asarray(bars_ramp(layout))
    assert ramp.shape == (100, layout.width)
    middle_column = layout.pitch // 2  # no meio da primeira barra
    assert ramp[49, middle_column] <= 3 and ramp[0, middle_column] >= 250 and ramp[99, middle_column] >= 250
    assert np.all(np.diff(ramp[50:, middle_column].astype(int)) >= 0)  # cresce do centro para a borda
    assert np.all(ramp[:, 0] == 255)  # a primeira coluna é vão: nenhuma altura a alcança
    in_bar = ramp[:, layout.gap : layout.pitch - layout.gap]
    assert in_bar.min() < 255


def test_the_ring_assets_cover_only_the_ring_and_name_every_bar():
    ring = RingLayout(200, 0.6)
    assets = ring_assets(ring)
    assert set(assets) == {"xmap", "radial", "ring"}
    xmap, radial, cover = (np.asarray(assets[name]) for name in ("xmap", "radial", "ring"))
    assert xmap.dtype == np.uint16 and xmap.shape == (200, 200)
    assert int(xmap.min()) == 0 and int(xmap.max()) == BAR_COUNT - 1  # todas as barras aparecem
    assert xmap[0, 99] == 0 or xmap[0, 100] == 0  # o setor 0 começa no topo
    assert cover[100, 100] == 0 and cover[2, 2] == 0  # dentro do raio interno e fora do anel: nada
    assert cover.max() == 255 and 0 < (cover > 0).mean() < 0.5
    assert radial[100, 100] == 0 and radial[0, 100] == 255  # a rampa radial cresce do raio interno ao externo


def test_every_style_declares_the_static_images_its_graph_reads():
    assert style_assets("wave", 800, 160, 0.6) == {}
    assert set(style_assets("bars", 864, 200, 0.6)) == {"ramp"}
    assert set(style_assets("circle", 200, 200, 0.6)) == {"xmap", "radial", "ring"}
    assert set(STYLES) == {"wave", "bars", "circle"}


# ---------- o ganho de nível e a média no tempo ----------


def test_the_visual_gain_is_the_one_the_loudnorm_applies_limited_by_the_true_peak():
    quiet = {"input_i": "-30.0", "input_tp": "-20.0"}
    assert normalization_gain_db(quiet, -14) == pytest.approx(16.0)  # o pico ainda cabe: vale o alvo
    loud_peak = {"input_i": "-22.46", "input_tp": "-6.02"}
    assert normalization_gain_db(loud_peak, -14) == pytest.approx(4.52)  # o pico (-1,5 dBTP) limita o ganho
    assert normalization_gain_db({"input_i": "-10", "input_tp": "-1"}, -14) == pytest.approx(-4.0)  # abaixa


@pytest.mark.parametrize(
    "measured",
    [
        None,
        {},
        {"input_i": "-inf", "input_tp": "-inf"},
        {"input_i": "nan", "input_tp": "0"},
        {"input_i": "x"},
    ],
)
def test_the_visual_gain_is_zero_without_a_usable_measurement(measured):
    assert normalization_gain_db(measured, -14) == 0.0


def test_smoothing_is_a_centred_odd_window_in_time_not_in_frames():
    assert [smoothing_frames(fps) for fps in (15, 24, 25, 30, 60)] == [3, 5, 5, 5, 11]


def test_without_a_smoothing_window_the_bars_are_not_averaged(monkeypatch):
    monkeypatch.setattr(audiogram_module, "SMOOTHING_SECONDS", 0)
    assert smoothing_frames(30) == 1
    assert "tmix" not in "\n".join(_graph_lines("bars"))


# ---------- a voz vinda de arquivo no barramento de áudio ----------


class _Voice:
    def __init__(self, path="fala.mp3", start=0.0, offset=0.0, duration=12.0, volume=1.0):
        self.path, self.start, self.offset, self.duration, self.volume = (
            Path(path),
            start,
            offset,
            duration,
            volume,
        )


def test_a_voice_file_is_trimmed_zeroed_resampled_gained_and_delayed():
    lines: list[str] = []
    inputs = Inputs()
    labels = voice_file_streams(lines, inputs, [_Voice(start=2.5, offset=1.25, duration=8.0, volume=0.8)])
    assert labels == ["[vf0]"]
    assert lines == [
        "[0:a]atrim=start=1.250:duration=8.000,asetpts=PTS-STARTPTS,aresample=48000,"
        "aformat=sample_fmts=fltp:channel_layouts=stereo,volume=0.800,adelay=2500:all=1[vf0]"
    ]
    assert inputs.args == ["-i", "fala.mp3"]


def test_a_voice_file_without_volume_or_audio_gets_no_input():
    lines: list[str] = []
    inputs = Inputs()
    assert voice_file_streams(lines, inputs, [_Voice(volume=0), _Voice(duration=0)]) == []
    assert lines == [] and inputs.args == []


def _audio_lines(*, music=True, mute_clips=False, taps=None, voice_files=(), narrations=()) -> list[str]:
    project = _project(
        audio={
            "music": {"src": "m.mp3", "volume": 0.2} if music else None,
            "mute_clips": mute_clips,
            "normalize": "two-pass",
        }
    )
    lines: list[str] = []
    audio_graph(
        lines,
        Inputs(),
        "[xa]",
        project.audio,
        Path("m.mp3") if music else None,
        10.0,
        measured={
            "input_i": "-23",
            "input_tp": "-4",
            "input_lra": "5",
            "input_thresh": "-33",
            "target_offset": "0.1",
        },
        voice_files=voice_files,
        taps=taps,
        narrations=narrations,
    )
    return lines


def test_the_voice_files_join_the_voice_bus_before_the_music_and_the_music_ducks_under_them():
    lines = _audio_lines(mute_clips=True, voice_files=[_Voice()])
    text = ";".join(lines)
    voice_mix = text.index("[a_narrated]")
    assert text.index("[vf0]") < voice_mix < text.index("sidechaincompress")
    assert "asplit=2[voice][sc]" in text  # o ducking vale porque há voz, mesmo com os clipes mudos


def test_without_voice_files_or_taps_the_audio_graph_is_what_it_always_was():
    assert _audio_lines() == _audio_lines(voice_files=(), taps=None)
    text = ";".join(_audio_lines())
    assert "a_narrated" not in text and "_tap" not in text


def test_the_voice_tap_is_taken_after_the_voice_files_and_before_the_music():
    taps = AudioTaps(frozenset({"voice"}))
    text = ";".join(_audio_lines(taps=taps, voice_files=[_Voice()]))
    assert taps.labels == {"voice": "[a_voice_tap]"}
    split = text.index("asplit=2[a_voice_main][a_voice_tap]")
    assert text.index("[a_narrated]") < split < text.index("[a_voice_main]") < text.index("sidechaincompress")
    # a cópia só sai do ramo: o que segue para a música e para a saída é o outro lado
    assert text.count("[a_voice_tap]") == 1


def test_the_mix_tap_is_taken_after_the_music_and_before_the_normalization():
    taps = AudioTaps(frozenset({"mix"}))
    text = ";".join(_audio_lines(taps=taps))
    assert taps.labels == {"mix": "[a_mix_tap]"}
    assert text.index("[amix]") < text.index("asplit=2[a_mix_main][a_mix_tap]") < text.index("loudnorm")
    assert "[a_mix_main]loudnorm" in text


def test_both_taps_can_coexist():
    taps = AudioTaps(frozenset({"voice", "mix"}))
    text = ";".join(_audio_lines(taps=taps))
    assert set(taps.labels) == {"voice", "mix"}
    assert text.index("a_voice_tap") < text.index("a_mix_tap")


# ---------- o grafo do desenho ----------

FPS = 30.0


def _item(style="bars", **fields) -> ResolvedAudiogram:
    overlay = AudiogramOverlay(style=style, x=0.5, y=0.6, **fields.pop("overlay", {}))
    size = {"wave": (864, 172), "bars": (864, 216), "circle": (780, 780)}[style]
    assets = {
        "wave": {},
        "bars": {"ramp": Path("a0_ramp.png")},
        "circle": {"xmap": Path("a0_xmap.png"), "radial": Path("a0_radial.png"), "ring": Path("a0_ring.png")},
    }[style]
    return ResolvedAudiogram(
        overlay, *size, fields.get("color", "#75B9A2"), 0.0, 9.0, fields.get("follow", "voice"), assets
    )


def _graph_lines(style="bars", follow="voice", gain_db=4.5, fps=FPS, items=None) -> list[str]:
    items = items or [_item(style, follow=follow)]
    lines: list[str] = []
    taps = AudioTaps(
        frozenset(item.follow for item in items), {"voice": "[a_voice_tap]", "mix": "[a_mix_tap]"}
    )
    out = audiogram_graph(
        lines, Inputs(), "[v0]", items, taps, gain_db, 1080, 1920, fps, 9.0, 1.0, SafeZone(220, 420, 60, 150)
    )
    assert out == f"[viza{len(items) - 1}]"
    return lines


def test_the_wave_draws_the_low_voice_with_showwaves_in_p2p_mode_and_never_compresses():
    text = "\n".join(_graph_lines("wave"))
    assert "[a_voice_tap]volume=4.50dB,pan=mono|c0=0.5*c0+0.5*c1,lowpass=f=500,volume=7dB," in text
    assert "showwaves=s=864x172:mode=p2p:rate=30:scale=lin:draw=full:colors=white" in text
    assert "dilation,dilation" in text and "gblur" in text
    # o nível vem só do ganho fixo: nada que levante o ruído das pausas
    assert not re.search(r"dynaudnorm|acompressor|compand|loudnorm", text)


def test_the_bars_average_the_spectrum_bands_in_time_and_compare_them_with_the_ramp():
    text = "\n".join(_graph_lines("bars"))
    assert (
        "showfreqs=s=128x256:mode=bar:ascale=sqrt:fscale=lin:win_size=256:win_func=hann:overlap=0.875:rate=30"
        in text
    )
    assert f"scale={BARS_PER_HALF}:1:flags=area,format=gray16le,tmix=frames=5:weights='1 2 3 2 1'" in text
    assert "hflip" in text and "hstack" in text  # graves no meio
    assert "lut2=c0='clip((x-y)*108,0,255)':shortest=1" in text  # a meia altura (216 / 2)
    expanded = re.search(r"scale=(\d+):216:flags=neighbor", text)
    assert expanded and int(expanded.group(1)) == bars_layout(864, 216).width


def test_the_circle_maps_the_bar_heights_to_polar_coordinates_with_remap():
    text = "\n".join(_graph_lines("circle"))
    assert f"scale={BAR_COUNT}:{BAR_COUNT}:flags=neighbor,format=gray16le" in text
    assert re.search(r"\[vizfieldin0\]\[vizxa0\]\[vizxb0\]remap", text)
    assert "lut2=c0='clip((x-y)*155.6,0,255)'" in text and "blend=all_mode=multiply:shortest=1" in text


@pytest.mark.parametrize("style", ["wave", "bars", "circle"])
@pytest.mark.parametrize("fps", [24.0, 30.0, 60.0])
def test_the_listening_copy_is_advanced_by_the_delay_of_the_drawing(style, fps):
    """O desenho atrasa o som (janela, carimbo do quadro, média no tempo); a cópia anda adiantada o mesmo tanto
    para o pico da fala e o do desenho caírem no mesmo quadro."""
    text = "\n".join(_graph_lines(style, fps=fps))
    advance = float(re.search(r"atrim=start=([\d.]+),asetpts=PTS-STARTPTS", text).group(1))
    assert advance == pytest.approx(STYLES[style].lag(fps), abs=5e-5)
    assert 0.02 < advance < 0.2


def test_the_drawing_is_painted_with_the_colour_and_overlaid_only_between_start_and_end():
    text = "\n".join(_graph_lines("wave"))
    assert (
        "colorchannelmixer=rr=0:rg=0:rb=0:ra=0.4588:gr=0:gg=0:gb=0:ga=0.7255:br=0:bg=0:bb=0:ba=0.6353" in text
    )
    assert "ar=1:ag=0:ab=0:aa=0[vizlayer0]" in text  # a luminância da máscara vira o alfa
    assert (
        "[v0][vizlayer0]overlay=x=540.00-w/2:y=1152.00-h/2:format=auto:enable='between(t,0.000,9.000)'[viza0]"
        in text
    )


def test_an_audiogram_without_coordinates_uses_the_position_and_the_safe_zone():
    item = _item("bars", overlay={"position": "bottom"})
    item.overlay = item.overlay.model_copy(update={"x": None, "y": None})
    lines: list[str] = []
    taps = AudioTaps(frozenset({"voice"}), {"voice": "[a_voice_tap]"})
    audiogram_graph(
        lines, Inputs(), "[v0]", [item], taps, 0.0, 1080, 1920, FPS, 9.0, 1.0, SafeZone(220, 420, 60, 150)
    )
    assert "overlay=x=(W-w)/2:y=H-h-460:" in "\n".join(lines)  # a margem de 40 px mais a faixa de 420


def test_audiograms_that_follow_the_same_audio_share_the_copy_and_the_others_do_not():
    items = [_item("bars", follow="voice"), _item("wave", follow="voice"), _item("circle", follow="mix")]
    text = "\n".join(_graph_lines(items=items))
    assert "[a_voice_tap]asplit=2[a_viz_voice0][a_viz_voice1]" in text
    assert text.count("a_mix_tap") == 1 and "asplit=1" not in text
    assert text.index("[a_viz_voice0]volume=") < text.index("[a_viz_voice1]volume=")
    assert text.count("[vizlayer") == 6  # três desenhos, cada um com rótulo de criação e de uso


def test_a_new_style_enters_by_registration_without_touching_the_graph_builder():
    @audiogram_style("dots", lag=lambda fps: 0.0)
    def _dots(ctx: DrawContext) -> str:
        ctx.lines.append(f"{ctx.source}anullsink")
        return "[maskdots]"

    try:
        assert isinstance(STYLES["dots"], AudiogramStyle)
        item = _item("wave")
        item.overlay = item.overlay.model_copy(update={"style": "dots"})
        lines: list[str] = []
        taps = AudioTaps(frozenset({"voice"}), {"voice": "[a_voice_tap]"})
        audiogram_graph(lines, Inputs(), "[v0]", [item], taps, 0.0, 1080, 1920, FPS, 9.0, 1.0, SafeZone())
        assert lines[0] == "[a_voice_tap]anullsink" and "[maskdots]format=rgba" in lines[1]
    finally:
        del STYLES["dots"]


# ---------- arquivos de voz: duração, aviso e preparo ----------


def _audio_info(path: Path, duration: float = 12.0, has_audio: bool = True) -> MediaInfo:
    return MediaInfo(path, duration, 0, 0, 0.0, False, has_audio, False)


def test_play_length_is_the_window_between_offset_and_end_inside_the_file():
    assert play_length(VoiceoverClip(src="f.mp3"), 12.0) == 12.0
    assert play_length(VoiceoverClip(src="f.mp3", offset=2, end=8), 12.0) == 6.0
    assert play_length(VoiceoverClip(src="f.mp3", offset=2, end=30), 12.0) == 10.0  # `end` além do arquivo
    assert play_length(VoiceoverClip(src="f.mp3", offset=15), 12.0) == 0.0  # `offset` além do arquivo


def test_prepare_voice_files_measures_each_file_and_says_which_field_is_wrong(tmp_path):
    (tmp_path / "fala.mp3").write_bytes(b"x")
    project = _project(audio={"voiceover": [{"src": "fala.mp3", "start": 1, "offset": 2}]})
    project.base_dir = tmp_path
    prepared = prepare_voice_files(project, lambda path: _audio_info(path, 10.0))
    assert prepared == [PreparedVoiceFile(tmp_path / "fala.mp3", 1.0, 2.0, 8.0, 1.0, "fala.mp3")]
    assert prepared[0].end == 9.0

    missing = _project(audio={"voiceover": [{"src": "fala.mp3"}, {"src": "nao-existe.mp3"}]})
    missing.base_dir = tmp_path
    with pytest.raises(FileNotFoundError, match=r"audio\.voiceover\[1\]\.src"):
        prepare_voice_files(missing, lambda path: _audio_info(path))
    with pytest.raises(ValueError, match=r"audio\.voiceover\[0\]\.src.*não tem áudio"):
        prepare_voice_files(project, lambda path: _audio_info(path, has_audio=False))


def test_the_lint_warns_when_the_voiceover_goes_past_the_end_and_when_the_file_is_missing(tmp_path):
    (tmp_path / "longo.mp3").write_bytes(b"x")
    (tmp_path / "curto.mp3").write_bytes(b"x")
    project = _project(
        audio={
            "voiceover": [
                {"src": "longo.mp3"},
                {"src": "curto.mp3", "start": 4},
                {"src": "fantasma.mp3"},
                {"src": "curto.mp3", "start": 30},
                {"src": "longo.mp3", "offset": 40},
            ]
        }
    )
    project.base_dir = tmp_path
    durations = {"longo.mp3": 14.0, "curto.mp3": 3.0}
    playtimes = voice_file_playtimes(project, lambda path: _audio_info(path, durations[path.name]))
    assert playtimes == [14.0, 3.0, None, 3.0, 0.0]
    warnings = voice_file_warnings(project, 10.0, playtimes)
    assert any(
        w.startswith("audio.voiceover[0]: termina em 14.0s, depois do fim do vídeo (10.0s)") for w in warnings
    )
    assert any(w.startswith("audio.voiceover[2].src: arquivo de áudio não encontrado") for w in warnings)
    assert any(w.startswith("audio.voiceover[3]: começa em 30s") for w in warnings)
    assert any(w.startswith("audio.voiceover[4]: o offset (40s) passa do fim do arquivo") for w in warnings)
    assert not any(w.startswith("audio.voiceover[1]") for w in warnings)  # 4 + 3 = 7 s cabe nos 10 s
    assert voice_file_warnings(project, 10.0, [])[0].startswith(
        "audio.voiceover[2].src"
    )  # sem duração, só a existência


def _lint(project: Project, total: float = 10.0, **kwargs) -> list[str]:
    from dmaker.domain.brand import load_theme

    return lint(
        project, load_theme(None, None), get_preset("instagram/reels"), total, [total], [None], **kwargs
    )


def test_the_lint_is_quiet_about_a_voiceover_that_fits_and_does_not_nag_about_mute_clips_with_one(tmp_path):
    (tmp_path / "fala.mp3").write_bytes(b"x")
    project = _project(
        audio={"voiceover": [{"src": "fala.mp3"}], "mute_clips": True}, captions={"source": "auto"}
    )
    project.base_dir = tmp_path
    assert _lint(project, voiceover_playtimes=[9.0]) == []
    without = _project(audio={"mute_clips": True}, captions={"source": "auto"})
    assert any("mute_clips" in w for w in _lint(without))  # sem voiceover o aviso de antes continua


def test_the_lint_warns_when_an_audiogram_follows_a_voice_the_project_does_not_have():
    silent = _project(
        overlays=[{"type": "audiogram", "follow": "voice"}, {"type": "audiogram", "follow": "auto"}]
    )
    warnings = [w for w in _lint(silent) if "audiograma" in w]
    assert len(warnings) == 1 and warnings[0].startswith("overlays[0]: o audiograma segue a voz")
    voiced = _project(
        overlays=[{"type": "audiogram", "follow": "voice"}], audio={"voiceover": [{"src": "f.mp3"}]}
    )
    assert not [w for w in _lint(voiced) if "audiograma" in w]


# ---------- o pipeline, com ffmpeg, probe e transcritor falsos ----------

LOUDNORM = json.dumps(
    {
        "input_i": "-23.5",
        "input_tp": "-4.0",
        "input_lra": "7.0",
        "input_thresh": "-33.9",
        "target_offset": "0.3",
    }
)


class _Transcriber:
    def __init__(self):
        self.calls = 0
        self.last_wav: Path | None = None

    def transcribe(self, wav: Path, language: str, initial_prompt: str | None = None) -> Transcript:
        self.calls += 1
        self.last_wav = wav
        words = [Word(0.5, 1.0, "bem-vindos"), Word(1.0, 1.4, "ao"), Word(1.4, 2.2, "podcast")]
        return Transcript([Cue(0.5, 2.2, "bem-vindos ao podcast", words)], {"language": language})


def _prober(path: Path) -> MediaInfo:
    if path.suffix == ".png":
        return MediaInfo(path, 0.0, 900, 700, 0.0, True, False, True)
    if path.suffix in (".wav", ".mp3"):
        return _audio_info(path, 12.0)
    return MediaInfo(path, 8.0, 1920, 1080, 30.0, True, True, False)


def _touch_output(command: FFmpegCommand) -> None:
    out = Path(command.args[-1])
    if out.suffix in (".mov", ".mp4", ".wav", ".jpg"):
        if command.cwd and not out.is_absolute():
            out = command.cwd / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00" * 1024)


def _render_unit(tmp_path: Path, spec: dict, *, transcriber=None, **options):
    """Renderiza com tudo falso. Os arquivos de entrada só são criados se faltam: reescrevê-los mudaria o
    `mtime`, que a chave de cache da transcrição enxerga."""
    for name, content in (("fala.wav", b"fala"), ("trilha.mp3", b"trilha")):
        if not (tmp_path / name).exists():
            (tmp_path / name).write_bytes(content)
    if not (tmp_path / "capa.png").exists():
        Image.new("RGB", (900, 700), "#3366CC").save(tmp_path / "capa.png")
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    runner = RecordingRunner(on_run=_touch_output, capture_stderr=LOUDNORM)
    transcriber = transcriber or _Transcriber()
    result = RenderPipeline(
        project,
        RenderOptions(preview=True, quiet=True, out=tmp_path / "out.mp4", **options),
        runner=runner,
        prober=_prober,
        transcriber_factory=lambda captions: transcriber,
        cache_dir=tmp_path / "mez",
        jobs_dir=tmp_path / "jobs",
        output_dir=tmp_path / "output",
    ).run()
    return result, runner, transcriber


def _podcast_spec(**audio) -> dict:
    return {
        "name": "podcast",
        "timeline": [{"type": "card", "flat": True, "duration": 13.0, "motion": "none", "logo": False}],
        "regions": {"anel": {"x": 0.5, "y": 0.4, "width": 0.72, "height": 0.405}},
        "overlays": [
            {"type": "image", "src": "capa.png", "x": 0.5, "y": 0.4, "width": 0.4, "shape": "circle"},
            {"type": "audiogram", "style": "circle", "region": "anel"},
        ],
        "captions": {"source": "auto", "language": "pt"},
        "audio": {"voiceover": [{"src": "fala.wav", "start": 0.5}], "normalize": "two-pass", **audio},
    }


def test_a_background_with_a_voiceover_renders_the_audiogram_and_transcribes_the_file(tmp_path):
    result, runner, transcriber = _render_unit(tmp_path, _podcast_spec())
    graph = (result.job_dir / "graph.txt").read_text(encoding="utf-8")
    # o desenho do círculo e a foto recortada entram no mesmo grafo da montagem, que segue a voz (sem música)
    assert "remap" in graph and "showfreqs" in graph and "[a_voice_tap]" in graph and "alphamerge" in graph
    assert "[a_mix_tap]" not in graph
    assert (result.job_dir / "audiogram0_xmap.png").exists() and (result.job_dir / "image0_mask.png").exists()
    # a legenda automática transcreve o áudio do voiceover, no tempo certo (começa em 0,5 s)
    transcription = next(c for c in runner.commands if "-ac" in c and "16000" in c)
    command = " ".join(transcription)
    assert (
        "fala.wav" in command and "atrim=start=0.000:duration=12.000" in command and "adelay=500" in command
    )
    assert transcriber.last_wav and transcriber.last_wav.name == "voice.wav"
    ass = (result.job_dir / "overlay.ass").read_text(encoding="utf-8-sig")
    assert "BEM-VINDOS" in ass.upper() or "bem-vindos" in ass.lower()
    # a medição de loudness e a da voz (para os efeitos) contam o arquivo de voz
    measurements = [
        c for c in runner.commands if "loudnorm" in " ".join(c) and "print_format=json" in " ".join(c)
    ]
    assert measurements and all("fala.wav" in " ".join(c) for c in measurements)
    assert result.warnings == []


def test_the_visual_gain_is_the_loudnorm_gain_taken_from_the_measurement(tmp_path):
    result, _, _ = _render_unit(tmp_path, _podcast_spec())
    graph = (result.job_dir / "graph.txt").read_text(encoding="utf-8")
    # medido -23,5 LUFS e -4,0 dBTP: levar a -14 pede 9,5 dB, mas o teto de -1,5 dBTP deixa só 2,5 dB
    assert "[a_voice_tap]volume=2.50dB" in graph


def test_auto_follows_the_mix_when_the_project_has_no_voice_and_the_voice_when_it_has(tmp_path):
    only_music = {
        "name": "musica",
        "timeline": [{"type": "card", "flat": True, "duration": 12.0, "motion": "none", "logo": False}],
        "overlays": [{"type": "audiogram", "style": "bars", "x": 0.5, "y": 0.5}],
        "audio": {"music": {"src": "trilha.mp3"}, "normalize": "two-pass"},
    }
    graph = (_render_unit(tmp_path, only_music)[0].job_dir / "graph.txt").read_text(encoding="utf-8")
    assert "[a_mix_tap]" in graph and "[a_voice_tap]" not in graph
    other = tmp_path / "outro"
    other.mkdir()
    with_voice = {
        **only_music,
        "name": "musica2",
        "audio": {**only_music["audio"], "voiceover": [{"src": "fala.wav"}]},
    }
    graph = (_render_unit(other, with_voice)[0].job_dir / "graph.txt").read_text(encoding="utf-8")
    assert "[a_voice_tap]" in graph and "[a_mix_tap]" not in graph


def test_the_transcription_cache_follows_the_voice_file(tmp_path):
    _, _, transcriber = _render_unit(tmp_path, _podcast_spec())
    assert transcriber.calls == 1
    _, _, again = _render_unit(tmp_path, _podcast_spec(), transcriber=transcriber)
    assert again.calls == 1  # o mesmo áudio: a transcrição veio do cache
    (tmp_path / "fala.wav").write_bytes(b"outra fala, de outro tamanho")
    _render_unit(tmp_path, _podcast_spec(), transcriber=transcriber)
    assert transcriber.calls == 2  # o arquivo mudou: transcreve de novo


def test_a_voiceover_with_mute_clips_still_gets_automatic_captions(tmp_path):
    result, _, transcriber = _render_unit(tmp_path, _podcast_spec(mute_clips=True))
    assert transcriber.calls == 1 and result.captions_file is not None


def test_a_voiceover_that_goes_past_the_end_is_reported_before_the_render_and_the_file_must_exist(tmp_path):
    spec = _podcast_spec()
    spec["audio"]["voiceover"] = [{"src": "fala.wav", "start": 5}]  # 5 + 12 s de arquivo, num vídeo de 13 s
    result, _, _ = _render_unit(tmp_path, spec)
    assert any(w.startswith("audio.voiceover[0]: termina em 17.0s") for w in result.warnings)
    spec["audio"]["voiceover"] = [{"src": "sumiu.wav"}]
    with pytest.raises(FileNotFoundError, match=r"audio\.voiceover\[0\]\.src"):
        _render_unit(tmp_path, spec)


def test_a_partial_render_ignores_the_voiceover_like_it_does_with_the_narration(tmp_path):
    spec = _podcast_spec()
    spec["captions"] = None
    result, _, _ = _render_unit(tmp_path, spec, segments=(0, 0))
    graph = (result.job_dir / "graph.txt").read_text(encoding="utf-8")
    assert "fala.wav" not in graph and "[a_voice_tap]" not in graph


# ---------- sem audiograma e sem voiceover, o grafo é o de antes ----------

# Gravado a partir do código da `develop` antes do DMK-34 (o mesmo projeto, a mesma montagem): o caminho dos
# fontes do ASS é o único trecho que varia com a máquina e é trocado por FONTS.
GRAPH_BEFORE_DMK_34 = (
    "[0:v]fps=30,settb=AVTB,format=yuv420p,setsar=1[tv0];[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[ta0];"
    "[1:v]fps=30,settb=AVTB,format=yuv420p,setsar=1[tv1];[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[ta1];"
    "[2:v]fps=30,settb=AVTB,format=yuv420p,setsar=1[tv2];[2:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[ta2];"
    "[tv1][ta1][tv2][ta2]concat=n=2:v=1:a=1[rv1_][ra1];[rv1_]fps=30,settb=AVTB[rv1];"
    "[tv0][rv1]xfade=transition=fade:duration=0.400:offset=0.600[xv1];[ta0][ra1]acrossfade=d=0.400:c1=tri:c2=tri[xa1];"
    "[3:v]format=rgba,scale=54:-2:flags=lanczos,fade=t=in:st=0.000:d=0.300:alpha=1[ov0];"
    "[xv1][ov0]overlay=x=W-w-95:y=130:enable='between(t,0.000,3.600)':format=auto[vo0];"
    "[vo0]ass=filename='overlay.ass':fontsdir='FONTS'[v_ass];[v_ass]format=yuv420p[vout];"
    "[4:a]atrim=start=0.000:duration=3.600,asetpts=PTS-STARTPTS,aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
    "volume=0.200,afade=t=in:st=0:d=1.000,afade=t=out:st=1.600:d=2.000[mus0];"
    "[xa1]asplit=2[voice][sc];[mus0][sc]sidechaincompress=threshold=0.0200:ratio=6:attack=20:release=350:makeup=1:level_sc=1[musd];"
    "[voice][musd]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[amix];"
    "[amix]loudnorm=I=-14:TP=-1.5:LRA=11:measured_I=-23.5:measured_TP=-4.0:measured_LRA=7.0:measured_thresh=-33.9:offset=0.3:linear=true,aresample=48000[a_norm];"
    "[a_norm]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[aout]"
)


def test_a_project_without_audiogram_and_without_voiceover_builds_the_same_assembly_graph_as_before(tmp_path):
    spec = {
        "name": "unit",
        "output": {"preset": "instagram/reels"},
        "brand": "medlycare",
        "timeline": [
            {"type": "card", "title": "Abertura", "duration": 1.0, "motion": "none"},
            {
                "type": "clip",
                "src": "take.mp4",
                "start": 1,
                "end": 3,
                "transition": {"type": "fade", "duration": 0.4},
            },
            {
                "type": "image",
                "src": "print.png",
                "duration": 1.0,
                "motion": "zoom-in",
                "transition": {"type": "cut"},
            },
        ],
        "overlays": [
            {"type": "image", "src": "logo:symbol", "position": "top-right", "width": 0.1},
            {"type": "text", "text": "Gancho", "role": "hook", "start": 0, "end": 0.9},
            {"type": "progress-bar"},
        ],
        "captions": {"source": "auto", "language": "pt"},
        "audio": {"normalize": "two-pass", "music": {"src": "trilha.mp3", "volume": 0.2}},
    }
    (tmp_path / "take.mp4").write_bytes(b"x")
    (tmp_path / "print.png").write_bytes(b"x")
    Image.new("RGB", (1000, 620), "#3366CC").save(tmp_path / "print.png")
    result, _, _ = _render_unit(tmp_path, spec)
    graph = re.sub(
        r"fontsdir='[^']*'", "fontsdir='FONTS'", (result.job_dir / "graph.txt").read_text(encoding="utf-8")
    )
    assert graph == GRAPH_BEFORE_DMK_34


# ---------- o modelo "audiograma" ----------

TEMPLATE_PARAMS = {"audio": "fala.mp3", "capa": "capa.jpg", "duracao": 30, "titulo": "Saúde em dia"}


def _from_template(**params) -> Project:
    return Project.model_validate(render_template(find_template("audiograma"), {**TEMPLATE_PARAMS, **params}))


def test_the_template_is_listed_with_its_parameters_and_no_dash():
    template = find_template("audiograma")
    assert set(template.params) >= {"audio", "capa", "duracao", "titulo", "estilo", "seguir", "cor", "fundo"}
    assert template.params["duracao"].duration_of == "audio"
    summary = template_summary(template)
    assert "padrão: a duração de audio" in summary and "—" not in summary and "–" not in summary
    described = next(t for t in describe_templates() if t["name"] == "audiograma")
    assert described["params"]["duracao"]["required"] is False  # o motor mede o arquivo quando se omite
    assert (TEMPLATES_DIR / "audiograma.json").read_text(encoding="utf-8").count("—") == 0


def test_the_template_builds_the_podcast_layout_with_the_circle_around_the_photo():
    project = _from_template(marca="medlycare")
    assert project.output.preset == "instagram/reels" and project.brand == "medlycare"
    assert project.timeline[0].duration == 30 and project.timeline[0].type == "card"
    kinds = [
        (type(o).__name__, getattr(o, "style", None), getattr(o, "region", None)) for o in project.overlays
    ]
    assert ("AudiogramOverlay", "circle", "anel") in kinds and ("ImageOverlay", None, "foto") in kinds
    assert not any(isinstance(o, AudiogramOverlay) and o.region == "onda" for o in project.overlays)
    photo = next(o for o in project.overlays if isinstance(o, ImageOverlay))
    assert photo.shape == "circle"
    assert project.audio.voiceover == [VoiceoverClip(src="fala.mp3")]
    assert project.captions and project.captions.source == "auto" and project.captions.language == "pt"
    for where, text in project.texts():
        assert "—" not in text and "–" not in text, where


@pytest.mark.parametrize("style", ["bars", "wave", "barras", "onda"])
def test_the_line_and_bar_styles_go_below_the_photo(style):
    project = _from_template(estilo=style)
    audiograms = [o for o in project.overlays if isinstance(o, AudiogramOverlay)]
    assert len(audiograms) == 1 and audiograms[0].region == "onda"
    assert audiograms[0].style == {"barras": "bars", "onda": "wave"}.get(style, style)


def test_the_template_passes_the_follow_and_the_colour_to_the_drawing_and_can_drop_the_title_and_captions():
    project = _from_template(seguir="mix", cor="#FF0000", titulo="", legendas=False)
    drawing = next(o for o in project.overlays if isinstance(o, AudiogramOverlay))
    assert (drawing.follow, drawing.color) == ("mix", "#FF0000")
    assert project.captions is None and not any(o.type == "text" for o in project.overlays)
    assert next(o for o in _from_template().overlays if isinstance(o, AudiogramOverlay)).color is None


def test_the_template_backgrounds_are_a_flat_card_a_colour_an_image_or_the_blurred_cover():
    assert _from_template().timeline[0].background == "#0F172A"  # escuro: o padrão
    assert _from_template(fundo="#102030").timeline[0].background == "#102030"
    image = _from_template(fundo="mesa.png").timeline[0]
    assert image.type == "image" and image.src == "mesa.png" and image.reframe.mode == "crop"
    cover = _from_template(fundo="capa").timeline[0]
    assert cover.type == "image" and cover.src == "capa.jpg" and cover.motion == "none"
    assert cover.color.extra == BLURRED_COVER_FILTER and cover.reframe.mode == "crop"


def test_the_template_regions_respect_the_reels_safe_zone_and_the_ring_wraps_the_photo():
    preset = get_preset("instagram/reels")
    safe, width, height = preset.safe, preset.width, preset.height
    project = _from_template()
    for name in ("titulo", "foto", "anel", "onda"):
        left, top, w, h = region_pixels(project.regions[name], width, height)
        assert left >= safe.left and left + w <= width - safe.right, name
        assert top >= safe.top and top + h <= height - safe.bottom, name
    photo = region_pixels(project.regions["foto"], width, height)
    ring = region_pixels(project.regions["anel"], width, height)
    assert photo[2] == photo[3] and ring[2] == ring[3]  # quadrados: o círculo é redondo de verdade
    assert (photo[0] + photo[2] / 2, photo[1] + photo[3] / 2) == (
        ring[0] + ring[2] / 2,
        ring[1] + ring[3] / 2,
    )
    drawing = next(o for o in project.overlays if isinstance(o, AudiogramOverlay) and o.style == "circle")
    inner = RingLayout(ring[2], drawing.inner_radius).inner
    assert photo[2] / 2 < inner < photo[2] / 2 + 30  # as barras nascem logo depois da foto


def test_the_template_preparer_explains_what_is_wrong():
    with pytest.raises(ValueError, match="estilo.*desconhecido"):
        prepare_audiogram({"estilo": "pizza", "duracao": 10})
    for bad in (None, 0, -3, "10", True):
        with pytest.raises(ValueError, match="duracao"):
            prepare_audiogram({"estilo": "circle", "duracao": bad})
    with pytest.raises(TemplateError, match="audiograma.*estilo"):
        _from_template(estilo="pizza")


def test_the_duration_of_the_audio_fills_the_omitted_duration_parameter(tmp_path):
    template = find_template("audiograma")
    audio = tmp_path / "episodio.mp3"
    audio.write_bytes(b"x")
    filled = with_media_durations(
        template, {"audio": str(audio), "capa": "c.png"}, lambda path: _audio_info(path, 61.2345)
    )
    assert filled["duracao"] == 61.234 or filled["duracao"] == 61.235
    assert (
        with_media_durations(
            template, {"audio": str(audio), "duracao": 20}, lambda path: _audio_info(path, 99)
        )["duracao"]
        == 20
    )  # o que o pedido disse vale
    with pytest.raises(FileNotFoundError, match='"audio"'):
        with_media_durations(template, {"audio": str(tmp_path / "sumiu.mp3")}, lambda path: _audio_info(path))
    assert "duracao" not in with_media_durations(template, {"capa": "c.png"}, lambda path: _audio_info(path))
