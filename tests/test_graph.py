from dataclasses import dataclass
from pathlib import Path

import pytest

from dmaker.domain.presets import SafeZone, get_preset
from dmaker.domain.spec import AudioSettings, ClipSegment, Music, MusicSpan, Reframe, Transition
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
    resolve_span,
    still_mezzanine,
    timeline_graph,
)
from dmaker.filtergraph.audio import music_stream
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
    assert str(tmp_path / "bg.png") in cmd.args and "[1:v][rf_fg]overlay=" in fc


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


def test_image_overlay_can_ignore_the_safe_zone(tmp_path: Path):
    from dmaker.domain.spec import ImageOverlay
    from dmaker.filtergraph.overlays import ResolvedImageOverlay, image_overlay_graph

    logo = tmp_path / "logo.png"
    logo.write_bytes(b"png")
    safe = SafeZone(220, 420, 60, 150)

    def graph(safe_zone: bool) -> str:
        lines: list[str] = []
        ov = ImageOverlay(src=str(logo), position="top-right", margin=24, safe_zone=safe_zone)
        image_overlay_graph(
            lines, Inputs(), "[v]", [ResolvedImageOverlay(ov, logo, 0, 5)], 1080, 1920, 30, 5, 1.0, safe
        )
        return ";".join(lines)

    assert "overlay=x=W-w-174:y=244" in graph(True)  # margem + zona segura
    assert "overlay=x=W-w-24:y=24" in graph(False)  # só a margem: cola no canto


def test_encode_args_by_platform():
    p = get_preset("youtube/video")
    args = encode_args(p, "high", "x264", 30)
    assert "libx264" in args and "-maxrate" in args and args[args.index("-crf") + 1] == str(p.crf)
    assert args[args.index("-b:a") + 1] == "256k" and "+faststart" in args
    assert "ultrafast" in encode_args(p, "draft", "x264", 30)
    assert "h264_nvenc" in encode_args(p, "high", "nvenc", 30)


def test_encoder_resolution_and_quality_levels():
    from dmaker.filtergraph.encode import resolve_encoder

    assert resolve_encoder("auto", "qsv") == "qsv" and resolve_encoder("auto", None) == "x264"
    assert resolve_encoder("x264", "qsv") == "x264"
    p = get_preset("instagram/reels")
    assert "slow" in encode_args(p, "max", "x264", 30) and "medium" in encode_args(p, "high", "x264", 30)
    assert "h264_qsv" in encode_args(p, "high", "qsv", 30)


def test_clip_mezzanine_session_in_point_and_tracks(tmp_path):
    from dmaker.filtergraph import TrackSlice

    seg = ClipSegment(source="cam2", start=20, end=30, volume=0.3)
    tracks = (
        TrackSlice(Path("altar.wav"), in_point=5.0, volume=1.0),
        TrackSlice(Path("dj.wav"), in_point=-1.5, volume=0.5, audio_stream=1),  # gravador ligou 1,5 s depois
    )
    cmd = clip_mezzanine(
        seg,
        _info(dur=60),
        Path("cam2.mp4"),
        10.0,
        1080,
        1920,
        30,
        tmp_path / "m.mov",
        in_point=7.5,
        tracks=tracks,
    )
    args = cmd.args
    assert args[:4] == ["-ss", "7.500", "-t", "10.000"]  # 20 s da sessão = 7,5 s no arquivo da câmera 2
    fc = _filter_complex(args)
    assert "[0:a:0]asetpts=PTS-STARTPTS,volume=0.300" in fc
    assert "-ss" in args and "5.000" in args and "0.000" in args  # faixa negativa entra do início do arquivo
    assert "[2:a:1]asetpts=PTS-STARTPTS,adelay=1500:all=1,volume=0.500" in fc
    assert "amix=inputs=3:duration=longest" in fc


def test_clip_mezzanine_muted_camera_keeps_tracks(tmp_path):
    from dmaker.filtergraph import TrackSlice

    seg = ClipSegment(source="cam1", start=0, end=5, mute=True, speed=2)
    cmd = clip_mezzanine(
        seg,
        _info(),
        Path("cam1.mp4"),
        2.5,
        1080,
        1920,
        30,
        tmp_path / "m.mov",
        in_point=0,
        tracks=(TrackSlice(Path("rec.wav"), 0.0),),
    )
    fc = _filter_complex(cmd.args)
    assert "[mz_cam]" not in fc and "[mz_trk0]atempo=2" in fc and "anullsrc" not in " ".join(cmd.args)


def test_audio_graph_music_spans_play_only_in_their_windows():
    """Trilha só na abertura (0-20 s) e no encerramento (100 s até o fim): duas entradas, a segunda
    atrasada até o instante em que entra e com fade de saída no fim do vídeo."""
    inputs = Inputs()
    inputs.add("a.mov")
    lines: list[str] = []
    music = Music(
        src="m.m4a",
        volume=0.3,
        ducking=False,
        spans=[
            MusicSpan(start=0, end=20, fade_in=0, fade_out=6),
            MusicSpan(start=100, end=None, start_at=170, fade_in=4, fade_out=5),
        ],
    )
    audio_graph(lines, inputs, "[ta0]", AudioSettings(music=music, normalize="off"), Path("m.m4a"), 130.0)
    text = ";".join(lines)
    assert inputs.count == 3
    assert "atrim=start=0.000:duration=20.000" in text and "afade=t=out:st=14.000:d=6.000" in text
    assert "atrim=start=170.000:duration=30.000" in text and "adelay=100000:all=1" in text
    assert "afade=t=in:st=0:d=4.000" in text and "afade=t=out:st=25.000:d=5.000" in text
    assert "[mus0][mus1]amix=inputs=2:duration=longest" in text and "[ta0][mus]amix=inputs=2" in text


# ---------- resolve_span (from_end / tail) ----------


def test_resolve_span_without_from_end_or_tail_is_a_passthrough():
    span = MusicSpan(start=10, end=40, start_at=2.0)
    assert resolve_span(span, total=130.0) == (10.0, 40.0, 2.0)


def test_resolve_span_from_end_counts_from_the_end_of_the_video():
    span = MusicSpan(start=33.5, end=None, from_end=True)
    assert resolve_span(span, total=130.0) == (96.5, None, 0.0)


def test_resolve_span_from_end_with_explicit_end_also_counts_from_the_end():
    span = MusicSpan(start=40, end=10, from_end=True)
    assert resolve_span(span, total=130.0) == (90.0, 120.0, 0.0)


def test_resolve_span_tail_anchors_start_at_on_the_end_of_the_music():
    span = MusicSpan(start=33.5, end=None, from_end=True, tail=True, start_at=0.5)
    start, end, start_at = resolve_span(span, total=130.0, music_duration=200.0)
    assert (start, end) == (96.5, None)
    assert start_at == 200.0 - 33.5 - 0.5  # duração - comprimento da janela - folga


def test_resolve_span_tail_without_music_duration_keeps_raw_start_at():
    """Sem duração da música (vista da linha do tempo, por exemplo), tail não é ancorado: a folga
    bruta passa direto, sem levantar erro (quem exige a duração é `music_stream`)."""
    span = MusicSpan(start=10, tail=True, start_at=0.5)
    assert resolve_span(span, total=130.0) == (10.0, None, 0.5)


def test_music_span_from_end_end_must_be_smaller_than_start():
    with pytest.raises(ValueError, match="from_end"):
        MusicSpan(start=10, end=40, from_end=True)


def test_music_stream_resolves_from_end_and_tail_spans():
    """Reproduz a janela de encerramento do template casamento-pascom: começa 33.5 s antes do fim e
    toca o final da trilha, com 0.5 s de folga."""
    inputs = Inputs()
    lines: list[str] = []
    music = Music(
        src="m.m4a",
        volume=0.8,
        loop=False,
        ducking=False,
        spans=[MusicSpan(start=33.5, from_end=True, tail=True, start_at=0.5, fade_in=5, fade_out=5)],
    )
    music_stream(lines, inputs, music, Path("m.m4a"), total=130.0, music_duration=200.0)
    text = ";".join(lines)
    assert "atrim=start=166.000:duration=33.500" in text
    assert "adelay=96500:all=1" in text


def test_music_stream_raises_clear_error_when_tail_has_no_music_duration():
    inputs = Inputs()
    music = Music(src="m.m4a", spans=[MusicSpan(start=10, tail=True)])
    with pytest.raises(ValueError, match="tail"):
        music_stream([], inputs, music, Path("m.m4a"), total=60.0)


# ---------- narração no barramento de voz ----------


@dataclass(frozen=True)
class _Narration:
    path: Path
    start: float = 0.0
    volume: float = 1.0


def test_audio_graph_mixes_narration_into_the_voice_before_ducking():
    inputs = Inputs()
    inputs.add("a.mov")
    lines: list[str] = []
    audio = AudioSettings(music=Music(src="m.mp3", volume=0.2, ducking=True))
    narrations = [_Narration(Path("n1.wav"), start=0.5, volume=1.5), _Narration(Path("n2.wav"), start=4.0)]
    audio_graph(lines, inputs, "[ta0]", audio, Path("m.mp3"), 12.0, narrations=narrations)
    text = ";".join(lines)
    assert inputs.args[2:] == ["-i", "n1.wav", "-i", "n2.wav", "-stream_loop", "-1", "-i", "m.mp3"]
    assert (
        "[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume=1.500,adelay=500:all=1[nar0]"
        in text
    )
    assert "volume=1.000,adelay=4000:all=1[nar1]" in text
    assert "[ta0][nar0][nar1]amix=inputs=3:duration=first" in text
    # a música abaixa sob o barramento que já inclui a narração, e o loudnorm vem depois de tudo
    assert text.index("[a_narrated]asplit=2[voice][sc]") < text.index("sidechaincompress")
    assert text.index("sidechaincompress") < text.index("loudnorm")


def test_audio_graph_narration_without_delay_or_volume():
    inputs = Inputs()
    lines: list[str] = []
    audio_graph(
        lines,
        inputs,
        "[ta0]",
        AudioSettings(normalize="off"),
        None,
        5.0,
        narrations=[_Narration(Path("n.wav")), _Narration(Path("mudo.wav"), volume=0.0)],
    )
    text = ";".join(lines)
    assert "adelay" not in text and "mudo.wav" not in " ".join(inputs.args)
    assert "[ta0][nar0]amix=inputs=2" in text


def test_audio_graph_narration_replaces_the_voice_when_clips_are_muted():
    """Vídeo só de cartões e imagens (clipes mudos): a narração é a voz e a música ainda abaixa sob ela."""
    inputs = Inputs()
    lines: list[str] = []
    audio = AudioSettings(mute_clips=True, music=Music(src="m.mp3"))
    audio_graph(lines, inputs, "[ta0]", audio, Path("m.mp3"), 6.0, narrations=[_Narration(Path("n.wav"))])
    text = ";".join(lines)
    assert "[ta0]volume=0[a_mute]" in text and "[a_mute][nar0]amix=inputs=2" in text
    assert "sidechaincompress" in text

    lines_without: list[str] = []
    audio_graph(lines_without, Inputs(), "[ta0]", audio, Path("m.mp3"), 6.0)
    assert "sidechaincompress" not in ";".join(lines_without)  # sem narração, mudo continua sem ducking


def test_audio_graph_without_narration_is_unchanged():
    lines: list[str] = []
    audio_graph(lines, Inputs(), "[ta0]", AudioSettings(normalize="off"), None, 5.0)
    assert "narrated" not in ";".join(lines) and "[nar" not in ";".join(lines)


def test_image_overlay_by_center_ignores_position_and_the_safe_zone(tmp_path: Path):
    """x/y (que o `region` resolve) põem o CENTRO da imagem, qualquer que seja o `position` guardado."""
    from dmaker.domain.spec import ImageOverlay
    from dmaker.filtergraph.overlays import ResolvedImageOverlay, image_overlay_graph, overlay_center_position

    assert overlay_center_position(0.5, 0.25, 1080, 1920) == ("540.00-w/2", "480.00-h/2")
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"png")
    lines: list[str] = []
    ov = ImageOverlay(src=str(logo), position="top-right", x=0.5, y=0.25, width=0.5)
    image_overlay_graph(
        lines,
        Inputs(),
        "[v]",
        [ResolvedImageOverlay(ov, logo, 0, 5)],
        1080,
        1920,
        30,
        5,
        1.0,
        SafeZone(220, 420, 60, 150),
    )
    text = ";".join(lines)
    assert "overlay=x=540.00-w/2:y=480.00-h/2" in text and "scale=540:-2" in text
