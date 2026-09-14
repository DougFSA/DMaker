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
