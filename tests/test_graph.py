from pathlib import Path

from dmaker.domain.presets import SafeZone, get_preset
from dmaker.domain.spec import AudioSettings, ClipSegment, Music, Reframe, Transition
from dmaker.domain.timeline import timeline_spans, timeline_total
from dmaker.filtergraph import (
    Inputs,
    atempo_chain,
    audio_graph,
    clip_mezzanine,
    encode_args,
    ffq,
    frames_mezzanine,
    overlay_position,
    reframe_graph,
    resolve_reframe_mode,
    still_mezzanine,
    timeline_graph,
)
from dmaker.media.probe import MediaInfo


def _info(w=1920, h=1080, dur=10.0, audio=True) -> MediaInfo:
    return MediaInfo(Path("x.mp4"), dur, w, h, 30, True, audio, False)


def _filter_complex(args: list[str]) -> str:
    return args[args.index("-filter_complex") + 1]


def test_atempo_chain():
    assert atempo_chain(1.5) == "atempo=1.5"
    assert atempo_chain(4) == "atempo=2,atempo=2"
    assert atempo_chain(0.25) == "atempo=0.5,atempo=0.5"


def test_ffq_escapes_windows_paths():
    assert ffq(r"D:\a b\c.ass") == r"'D\:/a b/c.ass'"


def test_reframe_mode_auto():
    assert resolve_reframe_mode("auto", 1920, 1080, 1080, 1920) == "blur"  # 16:9 -> 9:16
    assert resolve_reframe_mode("auto", 1920, 1080, 1080, 1920, has_brand=True) == "brand"
    assert resolve_reframe_mode("auto", 1080, 1350, 1080, 1080) == "crop"  # 4:5 -> 1:1
    assert resolve_reframe_mode("pad", 1920, 1080, 1080, 1920) == "pad"


def test_reframe_graph_variants():
    crop = reframe_graph("[a]", "[b]", 1920, 1080, 1080, 1920, Reframe(mode="crop", focus=(0.3, 0.5)))
    assert "force_original_aspect_ratio=increase" in crop and "crop=1080:1920:(iw-ow)*0.3000" in crop
    pad = reframe_graph("[a]", "[b]", 1920, 1080, 1080, 1920, Reframe(mode="pad", pad_color="#112233"))
    assert "pad=1080:1920" in pad and "color=#112233" in pad
    blur = reframe_graph("[a]", "[b]", 1920, 1080, 1080, 1920, Reframe(mode="blur"))
    assert "split=2" in blur and "gblur" in blur and "overlay=(W-w)/2:(H-h)/2" in blur
    brand = reframe_graph(
        "[a]", "[b]", 1000, 620, 1080, 1920, Reframe(mode="brand", margin=0.05), True, "[2:v]"
    )
    assert "[2:v][rf_fg]overlay=54:659" in brand and "scale=972:602" in brand
    # sem fundo disponível cai no desfoque
    assert "gblur" in reframe_graph("[a]", "[b]", 1000, 620, 1080, 1920, Reframe(mode="brand"), True, None)


def test_timeline_total_and_spans():
    fade = Transition(type="fade", duration=0.5)
    assert timeline_total([5, 4, 6], [None, fade, Transition(type="cut")]) == 14.5
    assert timeline_total([5, 4], [None, None]) == 9
    # transição maior que metade do trecho é encurtada
    assert timeline_total([1, 1], [None, Transition(type="fade", duration=2)]) == 1.5
    assert timeline_spans([5, 4, 6], [None, fade, Transition(type="cut")]) == [
        (0.0, 5.0),
        (4.5, 8.5),
        (8.5, 14.5),
    ]


def test_timeline_graph_offsets_and_runs():
    fade = Transition(type="fade", duration=0.5)
    g = timeline_graph(3, [5, 4, 6], [None, fade, Transition(type="cut")], 30)
    text = ";".join(g.lines)
    assert "concat=n=2:v=1:a=1" in text  # trechos 1 e 2 em corte seco
    assert "xfade=transition=fade:duration=0.500:offset=4.500" in text
    assert "acrossfade=d=0.500" in text
    assert g.total == 14.5 and g.video == "[xv1]" and g.audio == "[xa1]"


def test_timeline_graph_audio_only():
    g = timeline_graph(2, [3, 3], [None, None], 30, want_video=False)
    assert g.video is None and "concat=n=2:v=0:a=1" in ";".join(g.lines)


def test_clip_mezzanine_command(tmp_path):
    seg = ClipSegment(src="x.mp4", start=2, end=6, speed=2, volume=0.5, fade_in=0.2)
    cmd = clip_mezzanine(seg, _info(), Path("x.mp4"), 2.0, 1080, 1920, 30, tmp_path / "m.mov")
    assert cmd.total == 2.0 and cmd.frames is None
    assert cmd.args[:4] == ["-ss", "2.000", "-t", "4.000"]
    fc = _filter_complex(cmd.args)
    assert "setpts=(PTS-STARTPTS)/2" in fc and "atempo=2" in fc and "volume=0.500" in fc and "fade=t=in" in fc
    assert "pcm_s16le" in cmd.args and cmd.args[-1] == str(tmp_path / "m.mov")


def test_clip_mezzanine_silent_and_brand(tmp_path):
    seg = ClipSegment(src="x.mp4", reframe=Reframe(mode="brand"))
    cmd = clip_mezzanine(
        seg,
        _info(audio=False),
        Path("x.mp4"),
        10.0,
        1080,
        1920,
        30,
        tmp_path / "m.mov",
        backdrop=tmp_path / "bg.png",
        has_brand=True,
    )
    fc = _filter_complex(cmd.args)
    assert "anullsrc=r=48000:cl=stereo" in cmd.args
    assert str(tmp_path / "bg.png") in cmd.args and "[2:v][rf_fg]overlay=" in fc


def test_still_and_frames_mezzanine(tmp_path):
    seg = ClipSegment(src="x.mp4")  # só para pegar um ColorAdjust padrão
    still = still_mezzanine(tmp_path / "a.png", seg.color, 0, 0.5, 3.0, 30, tmp_path / "s.mov")
    assert "-loop" in still.args and "fade=t=out:st=2.500" in _filter_complex(still.args)
    frames = frames_mezzanine(iter([b"\x00" * 12]), 2, 2, seg.color, 0, 0, 1.0, 30, tmp_path / "f.mov")
    assert "rawvideo" in frames.args and "pipe:0" in frames.args and frames.frames is not None
    assert frames.args[frames.args.index("-s") + 1] == "2x2"


def test_audio_graph_music_ducking_and_loudnorm():
    inputs = Inputs()
    inputs.add("a.mov")
    lines: list[str] = []
    audio = AudioSettings(music=Music(src="m.mp3", volume=0.2, ducking=True), voice_gain=1.2)
    out = audio_graph(lines, inputs, "[ta0]", audio, Path("m.mp3"), 12.0)
    text = ";".join(lines)
    assert out == "[aout]"
    assert "-stream_loop" in inputs.args and inputs.count == 2
    assert "volume=1.200" in text and "sidechaincompress" in text and "amix=inputs=2" in text
    assert "loudnorm=I=-14:TP=-1.5:LRA=11" in text and "aresample=48000" in text

    lines2: list[str] = []
    audio_graph(lines2, Inputs(), "[ta0]", AudioSettings(normalize="off"), None, 5.0)
    assert "loudnorm" not in ";".join(lines2)


def test_audio_graph_two_pass_uses_measured_values():
    lines: list[str] = []
    measured = {
        "input_i": "-20.1",
        "input_tp": "-3.0",
        "input_lra": "6.0",
        "input_thresh": "-30.5",
        "target_offset": "0.2",
    }
    audio_graph(lines, Inputs(), "[ta0]", AudioSettings(), None, 5.0, measured=measured)
    assert "measured_I=-20.1" in ";".join(lines) and "linear=true" in ";".join(lines)


def test_overlay_position_respects_safe_zone():
    x, y = overlay_position("top-right", 1080, 1920, 40, SafeZone(220, 420, 60, 150))
    assert (x, y) == ("W-w-190", "260")
    x, y = overlay_position("bottom", 1080, 1920, 40, SafeZone(220, 420, 60, 150))
    assert (x, y) == ("(W-w)/2", "H-h-460")


def test_encode_args_by_platform():
    p = get_preset("youtube/video")
    args = encode_args(p, "high", "x264", 30)
    assert "libx264" in args and "-maxrate" in args and args[args.index("-crf") + 1] == str(p.crf)
    assert args[args.index("-b:a") + 1] == "256k" and "+faststart" in args
    assert "ultrafast" in encode_args(p, "draft", "x264", 30)
    assert "h264_nvenc" in encode_args(p, "high", "nvenc", 30)
