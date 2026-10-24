"""Renderiza de verdade com ffmpeg (clipes sintéticos). Pula se o ffmpeg não estiver instalado."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dmaker.domain.spec import Project
from dmaker.media.probe import probe
from dmaker.pipeline import RenderOptions, RenderPipeline, contact_sheet

from .conftest import requires_ffmpeg

pytestmark = requires_ffmpeg


def _project(media: dict[str, Path], tmp_path: Path, **overrides) -> Project:
    data = {
        "name": "teste_integracao",
        "output": {"preset": "instagram/reels", "quality": "medium"},
        "brand": "medlycare",
        "timeline": [
            {"type": "card", "title": "Teste do DMaker", "subtitle": "cartão gerado", "duration": 1.5},
            {
                "type": "clip",
                "src": str(media["clip_a"]),
                "start": 0.5,
                "end": 2.5,
                "transition": {"type": "fade", "duration": 0.4},
                "reframe": {"mode": "blur"},
            },
            {
                "type": "clip",
                "src": str(media["clip_b"]),
                "end": 1.5,
                "transition": {"type": "cut"},
                "speed": 1.5,
            },
            {
                "type": "image",
                "src": str(media["photo"]),
                "duration": 1.5,
                "motion": "zoom-in",
                "transition": {"type": "wipeleft", "duration": 0.3},
            },
        ],
        "overlays": [
            {"type": "image", "src": "logo", "position": "top-right", "width": 0.25},
            {"type": "text", "text": "Gancho no topo", "role": "hook", "start": 0, "end": 3},
            {"type": "text", "text": "medlycare.com.br", "role": "cta", "start": 3, "end": 6},
            {"type": "progress-bar"},
        ],
        "captions": {"source": str(media["srt"]), "style": {"mode": "karaoke"}},
        "audio": {
            "music": {"src": str(media["music"]), "volume": 0.2, "ducking": True},
            "normalize": "two-pass",
        },
    }
    data.update(overrides)
    p = Project.model_validate(data)
    p.base_dir = tmp_path
    return p


def test_dry_run_lists_commands(synthetic_media, tmp_path):
    project = _project(synthetic_media, tmp_path)
    result = RenderPipeline(project, RenderOptions(dry_run=True, out=tmp_path / "x.mp4")).run()
    assert len(result.commands) >= 5  # 4 mezaninos + montagem
    assert any("libx264" in c for c in result.commands)
    assert result.job_dir and (result.job_dir / "graph.txt").exists()
    # duração: 1.5 + (2.0 - 0.4) + 1.0 + (1.5 - 0.3) = 5.3
    assert abs(result.duration - 5.3) < 0.01


def test_preview_render(synthetic_media, tmp_path):
    project = _project(synthetic_media, tmp_path)
    out = tmp_path / "preview.mp4"
    result = RenderPipeline(project, RenderOptions(preview=True, out=out, quiet=True)).run()
    assert out.exists() and result.size_bytes > 10_000
    info = probe(out)
    assert (info.width, info.height) == (540, 960)
    assert info.has_audio and abs(info.duration - 5.3) < 0.25
    assert result.thumbnail and result.thumbnail.exists()
    sheet = contact_sheet(out, tmp_path / "sheet.png", 3, 2, 200)
    assert sheet.exists()


def test_full_render_with_two_pass_loudnorm_and_export_preset(synthetic_media, tmp_path):
    project = _project(synthetic_media, tmp_path)
    out = tmp_path / "final.mp4"
    result = RenderPipeline(project, RenderOptions(out=out, quiet=True, preset="youtube/shorts")).run()
    assert out.exists()
    info = probe(out)
    assert (info.width, info.height) == (1080, 1920) and info.has_audio
    assert result.job_dir and (result.job_dir / "loudnorm.json").exists()
    assert result.preset.id == "youtube/shorts"


def test_landscape_preset_with_pad_and_no_extras(synthetic_media, tmp_path):
    data = {
        "name": "teste_yt",
        "output": {"preset": "youtube/video"},
        "timeline": [
            {
                "type": "clip",
                "src": str(synthetic_media["clip_b"]),
                "end": 1.0,
                "reframe": {"mode": "pad", "pad_color": "#101010"},
            },
        ],
        "audio": {"normalize": "fast"},
    }
    project = Project.model_validate(data)
    project.base_dir = tmp_path
    out = tmp_path / "yt.mp4"
    RenderPipeline(project, RenderOptions(preview=True, out=out, quiet=True, thumbnail=False)).run()
    info = probe(out)
    assert info.width > info.height


def test_proxy_build_generates_playable_540p_file(synthetic_media, tmp_path):
    from dmaker.media.ffmpeg import SubprocessRunner
    from dmaker.pipeline.proxies import ProxyBuilder

    project = Project.model_validate(
        {"name": "teste_proxy", "timeline": [{"type": "clip", "src": str(synthetic_media["clip_a"])}]}
    )
    project.base_dir = tmp_path
    builder = ProxyBuilder(SubprocessRunner(quiet=True))
    statuses = builder.build(project)
    assert len(statuses) == 1 and statuses[0].ready
    proxy = statuses[0].proxy
    assert proxy.exists()
    info = probe(proxy)
    assert info.height == 540 and info.width > 0
    assert info.video_codec == "h264" and info.has_audio


def test_waveform_builder_reflects_tone_and_silence(tmp_path):
    """Um wav real (ffmpeg de verdade) com 1s de tom e 1s de silêncio: os picos calculados devem
    refletir isso, altos no trecho do tom e ~0 no trecho de silêncio."""
    from dmaker.media import ffmpeg
    from dmaker.media.ffmpeg import SubprocessRunner
    from dmaker.media.waveform import WaveformBuilder

    media = tmp_path / "tom_e_silencio.wav"
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=2",
            "-af",
            "volume=0:enable='gte(t,1)'",
            "-c:a",
            "pcm_s16le",
            str(media),
        ],
        quiet=True,
    )
    waveform = WaveformBuilder(SubprocessRunner(quiet=True)).build(media)
    assert waveform.duration == pytest.approx(2.0, abs=0.05)
    half = len(waveform.peaks) // 2
    assert min(waveform.peaks[: half - 2]) > 0.5  # primeiro segundo: tom
    assert max(waveform.peaks[half + 2 :]) < 0.05  # segundo segundo: silêncio


def test_missing_source_fails_clearly(tmp_path):
    project = Project.model_validate({"name": "x", "timeline": [{"type": "clip", "src": "nao_existe.mp4"}]})
    project.base_dir = tmp_path
    with pytest.raises(FileNotFoundError):
        RenderPipeline(project, RenderOptions(dry_run=True)).run()


def _write_event_wav(path: Path, seconds: float, seed: int = 5) -> None:
    """Áudio de evento (rajadas aleatórias) para a sincronização ter o que correlacionar."""
    import wave

    import numpy as np

    rate = 16000
    rng = np.random.default_rng(seed)
    n = int(seconds * rate)
    signal = rng.normal(0, 0.02, n).astype(np.float32)
    for start in rng.uniform(0, seconds - 0.5, size=int(seconds * 2)):
        i = int(start * rate)
        burst = (rng.normal(0, 0.4, int(0.15 * rate)) * np.hanning(int(0.15 * rate))).astype(np.float32)
        signal[i : i + len(burst)] += burst
    pcm = (np.clip(signal, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())


def test_multicam_sync_and_render(tmp_path):
    from dmaker.media import ffmpeg

    master_wav = tmp_path / "evento.wav"
    _write_event_wav(master_wav, 40)
    cam1 = tmp_path / "cam1.mp4"
    cam2 = tmp_path / "cam2.mp4"
    rec = tmp_path / "gravador.wav"
    video = ["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30"]
    encode = ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac"]
    ffmpeg.run([*video, "-i", str(master_wav), "-t", "40", *encode, str(cam1)], quiet=True)
    # câmera 2 ligou 2,0 s depois (o -ss vale só para a entrada seguinte); gravador ligou 0,5 s depois
    ffmpeg.run([*video, "-ss", "2.0", "-i", str(master_wav), "-t", "36", *encode, str(cam2)], quiet=True)
    ffmpeg.run(["-ss", "0.5", "-i", str(master_wav), "-t", "38", "-c:a", "pcm_s16le", str(rec)], quiet=True)

    project = Project.model_validate(
        {
            "name": "multicam_teste",
            "output": {"preset": "youtube/video"},
            "sources": {
                "cam1": {"src": str(cam1)},
                "cam2": {"src": str(cam2), "sync": "auto"},
                "rec": {"src": str(rec), "sync": "auto"},
            },
            "timeline": [
                {"type": "clip", "source": "cam1", "start": 5, "end": 8},
                {"type": "clip", "source": "cam2", "start": 8, "end": 11, "transition": {"type": "cut"}},
            ],
            "audio": {"tracks": [{"source": "rec"}], "normalize": "fast"},
        }
    )
    project.base_dir = tmp_path
    out = tmp_path / "multicam.mp4"
    result = RenderPipeline(project, RenderOptions(preview=True, out=out, quiet=True, thumbnail=False)).run()
    sync = json.loads((tmp_path / "sync.json").read_text(encoding="utf-8"))
    assert sync["cam2"]["offset"] == pytest.approx(2.0, abs=0.02)
    assert sync["rec"]["offset"] == pytest.approx(0.5, abs=0.02)
    assert sync["cam2"]["confidence"] > 4
    info = probe(out)
    assert abs(info.duration - 6.0) < 0.25 and info.has_audio and result.duration == pytest.approx(6.0)


def test_picture_in_picture_render(synthetic_media, tmp_path):
    """Tela (clip_a, 16:9) com webcam (clip_b) em círculo no canto e em retângulo com slide."""
    from PIL import Image

    from dmaker.media import ffmpeg

    project = Project.model_validate(
        {
            "name": "pip_teste",
            "output": {"preset": "youtube/video"},
            "timeline": [{"type": "clip", "src": str(synthetic_media["clip_a"]), "end": 3.0}],
            "overlays": [
                {
                    "type": "video",
                    "src": str(synthetic_media["clip_a"]),  # tem áudio (senoide)
                    "start": 0.5,
                    "end": 2.5,
                    "shape": "circle",
                    "width": 0.22,
                    "position": "bottom-right",
                    "border": 8,
                    "volume": 0.5,
                },
                {
                    "type": "video",
                    "src": str(synthetic_media["clip_b"]),
                    "start": 1.0,
                    "end": 3.0,
                    "shape": "rounded",
                    "aspect": "16:9",
                    "width": 0.3,
                    "position": "top-left",
                    "animation": "slide",
                    "shadow": False,
                },
            ],
            "audio": {"normalize": "fast"},
        }
    )
    project.base_dir = tmp_path
    out = tmp_path / "pip.mp4"
    result = RenderPipeline(project, RenderOptions(preview=True, out=out, quiet=True, thumbnail=False)).run()
    info = probe(out)
    assert abs(info.duration - 3.0) < 0.25 and result.job_dir
    assert (result.job_dir / "pip0_mask.png").exists() and (result.job_dir / "pip0_frame.png").exists()
    graph = (result.job_dir / "graph.txt").read_text(encoding="utf-8")
    assert "alphamerge" in graph and "tpad=start_duration=0.500" in graph and "eval=frame" in graph
    assert "amix=inputs=2" in graph  # áudio do PiP misturado (o segundo PiP não tem áudio)
    # no meio do vídeo o canto inferior direito tem o PiP (barras coloridas), não o padrão da tela
    frame = tmp_path / "pip_frame.jpg"
    ffmpeg.run(["-ss", "1.5", "-i", str(out), "-frames:v", "1", str(frame)], quiet=True)
    img = Image.open(frame).convert("RGB")
    w, h = img.size
    mask = Image.open(result.job_dir / "pip0_mask.png")
    assert mask.size[0] == mask.size[1]  # círculo é 1:1
    assert img.getpixel((w - 40, h - 40)) != img.getpixel((w // 2, 10))


def test_matte_render_with_real_model(synthetic_media, tmp_path):
    """Recorte de pessoa de verdade (RVM): o clipe sintético não tem pessoa, então o que se verifica é
    o encadeamento decodificador -> modelo -> codificador e a duração exata do trecho."""
    from dmaker.media.matting import model_path

    if not model_path("mobilenetv3").exists():
        pytest.skip("modelo do RVM não baixado (é baixado no primeiro uso de `matte`)")
    project = Project.model_validate(
        {
            "name": "matte_teste",
            "output": {"preset": "instagram/reels"},
            "timeline": [
                {
                    "type": "clip",
                    "src": str(synthetic_media["clip_a"]),
                    "start": 0.5,
                    "end": 1.5,
                    "matte": {"background": "#FFFFFF", "model": "mobilenetv3"},
                }
            ],
            "audio": {"normalize": "off"},
        }
    )
    project.base_dir = tmp_path
    out = tmp_path / "matte.mp4"
    result = RenderPipeline(project, RenderOptions(preview=True, out=out, quiet=True)).run()
    assert out.exists() and abs(result.duration - 1.0) < 0.01
    info = probe(out)
    assert info.has_audio and abs(info.duration - 1.0) < 0.15


@pytest.mark.parametrize("extension", ["wav", "mp3", "m4a"])
def test_narration_concat_joins_parts_with_pauses(tmp_path, extension):
    import numpy as np

    from dmaker.filtergraph.voice import narration_concat_command
    from dmaker.media.ffmpeg import SubprocessRunner
    from dmaker.media.wavio import write_wav

    tone = np.sin(2 * np.pi * 440 * np.arange(24000) / 24000).astype(np.float32) * 0.3  # 1 s a 24 kHz
    first = write_wav(tmp_path / "a.wav", tone, 24000)
    second = write_wav(tmp_path / "b.wav", tone[:12000], 24000)  # 0,5 s
    out = tmp_path / f"narracao.{extension}"

    SubprocessRunner(quiet=True).run(narration_concat_command([(first, 0.5), (second, 0.0)], out))

    info = probe(out)
    assert info.has_audio and info.sample_rate == 48000 and info.channels == 1
    assert abs(info.duration - 2.0) < 0.08  # 1,0 + 0,5 de pausa + 0,5 (mp3/m4a acrescentam um pouco)


class _SilencingSeparator:
    """Separador falso para o ffmpeg de verdade: a voz sai muda e o fundo é a própria entrada."""

    model_id = "teste:mudo"

    def separate(self, wav, out_dir, on_progress=None):
        import numpy as np

        from dmaker.media.separation import Stems
        from dmaker.media.wavio import read_wav_channels, write_wav_channels

        samples, rate = read_wav_channels(wav)
        stems = Stems.in_directory(out_dir)
        write_wav_channels(stems.vocals, np.zeros_like(samples), rate)
        write_wav_channels(stems.background, samples, rate)
        return stems


def _mean_volume_db(path: Path) -> float:
    import re

    from dmaker.media.ffmpeg import SubprocessRunner

    report = SubprocessRunner(quiet=True).capture(
        ["-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"]
    )
    return float(re.search(r"mean_volume: (-?[\d.]+|-inf) dB", report).group(1))


@pytest.mark.parametrize(("mode", "audible"), [("original", True), ("background", True), ("voice", False)])
def test_audio_mode_swaps_the_camera_audio_for_the_isolated_stem(synthetic_media, tmp_path, mode, audible):
    """O clipe de teste tem um tom de 440 Hz; com o separador falso, `voice` fica mudo e `background`
    mantém o tom: prova que o stem entra no mezanino de verdade."""
    from dmaker.media.ffmpeg import SubprocessRunner
    from dmaker.pipeline.isolation import IsolationService

    project = Project.model_validate(
        {
            "name": f"audio_mode_{mode}",
            "output": {"preset": "instagram/reels"},
            "timeline": [
                {
                    "type": "clip",
                    "src": str(synthetic_media["clip_a"]),
                    "start": 0.5,
                    "end": 2.5,
                    "audio_mode": mode,
                }
            ],
            "audio": {"normalize": "off"},
        }
    )
    project.base_dir = tmp_path
    runner = SubprocessRunner(quiet=True)
    isolator = IsolationService(_SilencingSeparator(), runner, cache_dir=tmp_path / "stems")
    out = tmp_path / f"{mode}.mp4"
    RenderPipeline(
        project, RenderOptions(preview=True, out=out, quiet=True), isolator=isolator, runner=runner
    ).run()

    level = _mean_volume_db(out)
    assert (level > -40) if audible else (level < -60)


def _segment_db(path: Path, start: float, end: float) -> float:
    import re

    from dmaker.media.ffmpeg import SubprocessRunner

    report = SubprocessRunner(quiet=True).capture(
        [
            "-ss",
            str(start),
            "-t",
            str(end - start),
            "-i",
            str(path),
            "-vn",
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ]
    )
    return float(re.search(r"mean_volume: (-?[\d.]+|-inf) dB", report).group(1))


def test_speech_splice_replaces_only_the_region_and_keeps_length_and_video(tmp_path):
    """Original com tom de 220 Hz em 6 s; a região 2 a 4 s vira fundo mudo mais uma fala de 880 Hz entre
    2,5 e 3,5 s. Fora da região o original continua; dentro, só a fala; o vídeo é copiado sem recodificar."""
    import numpy as np

    from dmaker.filtergraph.speech_edit import speech_splice_command
    from dmaker.media import ffmpeg
    from dmaker.media.ffmpeg import SubprocessRunner
    from dmaker.media.wavio import write_wav, write_wav_channels
    from dmaker.voice.speech_edit import SplicePlan

    source = tmp_path / "original.mp4"
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x240:rate=25",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:sample_rate=48000",
        ]
        + [
            "-t",
            "6",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source),
        ],
        quiet=True,
    )
    background = write_wav_channels(tmp_path / "bg.wav", np.zeros((6 * 44100, 2), dtype=np.float32), 44100)
    tone = (0.3 * np.sin(2 * np.pi * 880 * np.arange(24000) / 24000)).astype(np.float32)
    speech = write_wav(tmp_path / "fala.wav", tone, 24000)
    plan = SplicePlan(2.0, 4.0, 2.5, 1.0, 1.0, 0.03, "teste")
    out = tmp_path / "corrigido.mp4"

    SubprocessRunner(quiet=True).run(
        speech_splice_command(source, background, speech, out, plan, 0.0, has_video=True, source_duration=6.0)
    )

    info, original = probe(out), probe(source)
    assert abs(info.duration - original.duration) < 0.1  # o arquivo não encolhe nem estica
    assert info.video_codec == original.video_codec and (info.width, info.height) == (320, 240)
    assert _segment_db(out, 0.2, 1.8) > -25  # antes da região: o original (220 Hz)
    assert _segment_db(out, 4.2, 5.8) > -25  # depois dela: o original de novo
    assert _segment_db(out, 2.1, 2.4) < -60  # entre a emenda e a fala: só o fundo, mudo
    assert -25 < _segment_db(out, 2.6, 3.4) < -5  # a fala nova, no volume em que foi gerada


def test_dub_mix_places_each_speech_over_the_background_and_keeps_length_and_video(tmp_path):
    """Fundo de 110 Hz em 6 s; fala A de 880 Hz em 1 s e fala B de 1320 Hz em 3,5 s (cortada em 0,5 s, com
    fade). Cada fala toca na sua posição, o fundo continua inteiro, o vídeo é copiado e o comprimento não muda."""
    import numpy as np

    from dmaker.filtergraph.dub import DubClip, dub_mix_command
    from dmaker.media import ffmpeg
    from dmaker.media.ffmpeg import SubprocessRunner
    from dmaker.media.wavio import write_wav, write_wav_channels

    source = tmp_path / "original.mp4"
    ffmpeg.run(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x240:rate=25",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:sample_rate=48000",
        ]
        + [
            "-t",
            "6",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source),
        ],
        quiet=True,
    )
    t = np.arange(6 * 44100) / 44100
    hum = (0.05 * np.sin(2 * np.pi * 110 * t)).astype(np.float32)
    background = write_wav_channels(tmp_path / "fundo.wav", np.stack([hum, hum], axis=1), 44100)
    speech_t = np.arange(2 * 24000) / 24000  # 2 s a 24 kHz, mono (o formato da síntese)
    first = write_wav(
        tmp_path / "a.wav", (0.3 * np.sin(2 * np.pi * 880 * speech_t)).astype(np.float32), 24000
    )
    second = write_wav(
        tmp_path / "b.wav", (0.3 * np.sin(2 * np.pi * 1320 * speech_t)).astype(np.float32), 24000
    )
    clips = [DubClip(first, 1.0, gain_db=0.0), DubClip(second, 3.5, gain_db=0.0, max_seconds=0.5)]
    out = tmp_path / "dublado.mp4"
    graph_file = tmp_path / "grafo.txt"

    mix = dub_mix_command(source, background, clips, out, graph_file, 6.0, True)
    graph_file.write_text(mix.graph, encoding="utf-8")
    SubprocessRunner(quiet=True).run(mix.command)

    info, original = probe(out), probe(source)
    assert abs(info.duration - original.duration) < 0.1
    assert info.video_codec == original.video_codec and (info.width, info.height) == (320, 240)
    assert info.has_audio and info.sample_rate == 48000 and info.channels == 2
    assert _segment_db(out, 0.2, 0.8) < -20  # antes das falas: só o fundo, baixo
    assert _segment_db(out, 0.2, 0.8) > -50  # mas presente: a música de fundo não some
    assert _segment_db(out, 1.2, 2.8) > _segment_db(out, 0.2, 0.8) + 10  # fala A, na posição pedida
    assert _segment_db(out, 3.0, 3.4) < _segment_db(out, 1.2, 2.8) - 10  # antes da fala B, só o fundo
    assert _segment_db(out, 3.55, 3.95) > _segment_db(out, 3.0, 3.4) + 10  # fala B começa em 3,5 s
    assert _segment_db(out, 4.2, 5.8) < -20  # B foi cortada em 0,5 s: depois dela, só o fundo
    assert _segment_db(out, 4.2, 5.8) > -50  # e o fundo segue até o fim


def test_dub_stems_have_the_video_duration_and_sum_to_the_mix_before_the_finish(tmp_path):
    """Fundo curto (5,9 s) e voz original longa (6,1 s) saem em 6 s exatos; a fala B (cortada em 0,5 s) e a fala
    A tocam onde a mixagem as põe; voz dublada + fundo reproduzem a mixagem sem limitador, a menos do
    arredondamento de 16 bits."""
    import numpy as np

    from dmaker.filtergraph.dub import DubClip, dub_mix_graph
    from dmaker.filtergraph.dub_stems import StemOutputs, dub_stems_command
    from dmaker.media.ffmpeg import FFmpegCommand, SubprocessRunner
    from dmaker.media.wavio import read_wav_channels, wav_duration, write_wav, write_wav_channels

    def tone(seconds: float, rate: int, hertz: int, level: float) -> np.ndarray:
        t = np.arange(round(seconds * rate)) / rate
        return (level * np.sin(2 * np.pi * hertz * t)).astype(np.float32)

    hum = tone(5.9, 44100, 110, 0.05)
    background = write_wav_channels(tmp_path / "fundo-in.wav", np.stack([hum, hum], axis=1), 44100)
    voice = tone(6.1, 44100, 220, 0.2)
    original = write_wav_channels(tmp_path / "voz-in.wav", np.stack([voice, voice], axis=1), 44100)
    first = write_wav(tmp_path / "a.wav", tone(2.0, 24000, 880, 0.3), 24000)
    second = write_wav(tmp_path / "b.wav", tone(2.0, 24000, 1320, 0.3), 24000)
    clips = [
        DubClip(first, 1.0, gain_db=-3.0),
        DubClip(second, 3.5, gain_db=2.0, tempo=1.25, max_seconds=0.5),
    ]
    duration = 6.0
    runner = SubprocessRunner(quiet=True)

    outputs = StemOutputs(tmp_path / "voz-dublada.wav", tmp_path / "fundo.wav", tmp_path / "voz-original.wav")
    built = dub_stems_command(background, original, clips, outputs, tmp_path / "trilhas.txt", duration)
    (tmp_path / "trilhas.txt").write_text(built.graph, encoding="utf-8")
    runner.run(built.command)

    premix = tmp_path / "premix.wav"
    (tmp_path / "premix.txt").write_text(
        dub_mix_graph(clips, 1, 0, duration, limit_peaks=False), encoding="utf-8"
    )
    args = ["-i", str(background), *[a for c in clips for a in ("-i", str(c.path))]]
    runner.run(
        FFmpegCommand([*args, "-/filter_complex", str(tmp_path / "premix.txt"), "-map", "[out]", str(premix)])
    )

    for path in (outputs.voice_dubbed, outputs.background, outputs.voice_original):
        info = probe(path)
        assert info.sample_rate == 48000 and info.channels == 2
        assert wav_duration(path) == duration  # a duração do vídeo, ao quadro de áudio
    voice_dubbed, _ = read_wav_channels(outputs.voice_dubbed)
    rate = 48000
    assert np.abs(voice_dubbed[: int(0.95 * rate)]).max() == 0  # alinhada no zero: nada antes da fala A
    assert np.abs(voice_dubbed[int(1.1 * rate) : int(2.9 * rate)]).max() > 0.1  # fala A na posição pedida
    assert np.abs(voice_dubbed[int(4.1 * rate) :]).max() == 0  # B foi cortada em 0,5 s; depois, silêncio
    background_out, _ = read_wav_channels(outputs.background)
    assert np.abs(background_out[int(5.95 * rate) :]).max() == 0  # o fundo curto foi completado com silêncio
    original_out, _ = read_wav_channels(outputs.voice_original)
    assert abs(float(np.abs(original_out).max()) - 0.2) < 0.01  # a voz original sai sem atenuar

    mix, _ = read_wav_channels(premix)
    summed = voice_dubbed + background_out
    difference = summed - mix[: len(summed)]
    assert abs(len(mix) - len(summed)) <= 1
    assert float(np.abs(difference).max()) < 2e-4  # ~6 passos de 16 bits (-74 dB); o limitador não participa
