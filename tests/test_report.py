"""Relatório de QA: checagens estáticas (spec) e sobre a saída renderizada, tudo com fakes (sem ffmpeg)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dmaker.domain.presets import get_preset
from dmaker.domain.spec import Project
from dmaker.media.ffmpeg import RecordingRunner
from dmaker.media.probe import MediaInfo
from dmaker.pipeline.layout import project_layout
from dmaker.pipeline.report import (
    STATIC_CHECKS,
    Finding,
    OutputInspector,
    QAReport,
    build_report,
    check_captions,
    check_contrast,
    check_lint,
    check_overlap,
    check_sources,
    check_text_pacing,
    check_text_safe_zone,
    contrast_ratio,
    parse_blackdetect,
    parse_loudnorm_json,
    parse_silencedetect,
)

VIDEO_INFO = MediaInfo(Path("take.mp4"), 8.0, 1920, 1080, 30.0, True, True, False)
SMALL_IMAGE_INFO = MediaInfo(Path("print.png"), 0.0, 200, 150, 0.0, True, False, True)


def make_prober(overrides: dict[str, MediaInfo]):
    """Prober falso: usa `overrides` por nome de arquivo, senão um vídeo padrão 1920x1080 com áudio."""

    def prober(path: Path) -> MediaInfo:
        info = overrides.get(path.name, VIDEO_INFO)
        return MediaInfo(
            path,
            info.duration,
            info.width,
            info.height,
            info.fps,
            info.has_video,
            info.has_audio,
            info.is_image,
        )

    return prober


def _touch(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    p.write_bytes(b"x")
    return p


def _project(tmp_path: Path, spec: dict) -> Project:
    project = Project.model_validate(spec)
    project.base_dir = tmp_path
    return project


def _layout(project: Project, prober):
    return project_layout(project, prober)


# ---------- contraste ----------


def test_contrast_ratio_known_values():
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0, abs=0.05)
    assert contrast_ratio("#FFFFFF", "#FFFFFF") == pytest.approx(1.0, abs=0.001)


# ---------- parsing do stderr do ffmpeg ----------


def test_parse_blackdetect():
    stderr = (
        "[blackdetect @ 0x1] black_start:1.000000 black_end:2.500000 black_duration:1.500000\n"
        "[blackdetect @ 0x1] black_start:5.000000 black_end:5.600000 black_duration:0.600000\n"
    )
    assert parse_blackdetect(stderr) == [(1.0, 2.5), (5.0, 5.6)]
    assert parse_blackdetect("nada por aqui") == []


def test_parse_silencedetect():
    stderr = (
        "[silencedetect @ 0x1] silence_start: 3.2\n"
        "[silencedetect @ 0x1] silence_end: 6.4 | silence_duration: 3.2\n"
    )
    assert parse_silencedetect(stderr) == [(3.2, 6.4)]
    assert parse_silencedetect("nada por aqui") == []


def test_parse_loudnorm_json():
    stderr = (
        "algo antes na tela\n"
        '{ "input_i" : "-23.50", "input_tp" : "-4.00", "input_lra" : "7.00", '
        '"input_thresh" : "-33.90", "output_i" : "-14.00", "output_tp" : "-2.00", '
        '"output_lra" : "5.00", "output_thresh" : "-24.10", "normalization_type" : "dynamic", '
        '"target_offset" : "0.30" }\n'
    )
    data = parse_loudnorm_json(stderr)
    assert data["input_i"] == "-23.50" and data["input_tp"] == "-4.00"
    assert parse_loudnorm_json("sem json nenhum") == {}


# ---------- check_lint ----------


def test_check_lint_flags_duration_over_preset(tmp_path):
    _touch(tmp_path, "take.mp4")
    spec = {
        "name": "p",
        "output": {"preset": "whatsapp/status"},  # limite de 30s
        "timeline": [{"type": "clip", "src": "take.mp4", "start": 0, "end": 8}] * 5,  # 40s
        "audio": {"normalize": "off"},
    }
    project = _project(tmp_path, spec)
    layout = _layout(project, make_prober({}))
    findings = check_lint(project, layout)
    assert any("passa do limite" in f.message for f in findings)


def test_check_lint_clean_project(tmp_path):
    _touch(tmp_path, "take.mp4")
    spec = {
        "name": "p",
        "output": {"preset": "instagram/reels"},
        "timeline": [{"type": "clip", "src": "take.mp4", "start": 0, "end": 4}],
        "audio": {"normalize": "off"},
    }
    project = _project(tmp_path, spec)
    layout = _layout(project, make_prober({}))
    assert check_lint(project, layout) == []


# ---------- check_text_safe_zone ----------


def test_check_text_safe_zone_flags_overlay_pinned_to_top_edge(tmp_path):
    _touch(tmp_path, "take.mp4")
    spec = {
        "name": "p",
        "output": {"preset": "instagram/reels"},
        "timeline": [{"type": "clip", "src": "take.mp4", "start": 0, "end": 4}],
        "overlays": [
            {
                "type": "text",
                "text": "Um texto colado bem no topo do quadro",
                "role": "hook",
                "y": 0.0,
                "start": 0,
                "end": 3,
            }
        ],
        "audio": {"normalize": "off"},
    }
    project = _project(tmp_path, spec)
    findings = check_text_safe_zone(project, _layout(project, make_prober({})))
    assert any("área coberta" in f.message for f in findings)


def test_check_text_safe_zone_default_position_is_clean(tmp_path):
    _touch(tmp_path, "take.mp4")
    spec = {
        "name": "p",
        "output": {"preset": "instagram/reels"},
        "timeline": [{"type": "clip", "src": "take.mp4", "start": 0, "end": 4}],
        "overlays": [{"type": "text", "text": "Gancho curto", "role": "hook", "start": 0, "end": 3}],
        "audio": {"normalize": "off"},
    }
    project = _project(tmp_path, spec)
    assert check_text_safe_zone(project, _layout(project, make_prober({}))) == []


def test_check_text_safe_zone_flags_word_wider_than_area(tmp_path):
    _touch(tmp_path, "take.mp4")
    spec = {
        "name": "p",
        "output": {"preset": "instagram/reels"},
        "timeline": [{"type": "clip", "src": "take.mp4", "start": 0, "end": 4}],
        "overlays": [
            {
                "type": "text",
                "text": "Supercalifragilisticexpialidocious",
                "role": "title",
                "start": 0,
                "end": 3,
                "style": {"max_width": 0.05},
            }
        ],
        "audio": {"normalize": "off"},
    }
    project = _project(tmp_path, spec)
    findings = check_text_safe_zone(project, _layout(project, make_prober({})))
    assert any("cortada" in f.message for f in findings)


def test_check_text_safe_zone_flags_tall_card_title(tmp_path):
    spec = {
        "name": "p",
        "output": {"preset": "whatsapp/status"},
        "timeline": [{"type": "card", "title": " ".join(["palavra"] * 40), "duration": 3}],
        "audio": {"normalize": "off"},
    }
    project = _project(tmp_path, spec)
    findings = check_text_safe_zone(project, _layout(project, make_prober({})))
    assert any("não caber na altura" in f.message for f in findings)


# ---------- check_text_pacing ----------


def test_check_text_pacing_flags_fast_hook(tmp_path):
    _touch(tmp_path, "take.mp4")
    spec = {
        "name": "p",
        "output": {"preset": "instagram/reels"},
        "timeline": [{"type": "clip", "src": "take.mp4", "start": 0, "end": 4}],
        "overlays": [
            {
                "type": "text",
                "text": "um dois tres quatro cinco seis sete oito nove dez onze doze",
                "role": "hook",
                "start": 0,
                "end": 1,
            }
        ],
        "audio": {"normalize": "off"},
    }
    project = _project(tmp_path, spec)
    findings = check_text_pacing(project, _layout(project, make_prober({})))
    assert any("rápido demais" in f.message for f in findings)


def test_check_text_pacing_clean_for_normal_pace(tmp_path):
    _touch(tmp_path, "take.mp4")
    spec = {
        "name": "p",
        "output": {"preset": "instagram/reels"},
        "timeline": [{"type": "clip", "src": "take.mp4", "start": 0, "end": 4}],
        "overlays": [{"type": "text", "text": "Gancho curto e claro", "role": "hook", "start": 0, "end": 3}],
        "audio": {"normalize": "off"},
    }
    project = _project(tmp_path, spec)
    assert check_text_pacing(project, _layout(project, make_prober({}))) == []


def test_check_text_pacing_flags_long_card_title(tmp_path):
    spec = {
        "name": "p",
        "output": {"preset": "instagram/reels"},
        "timeline": [
            {
                "type": "card",
                "title": "Um título de cartão absurdamente longo que passa fácil de sessenta caracteres",
                "duration": 2,
            }
        ],
        "audio": {"normalize": "off"},
    }
    project = _project(tmp_path, spec)
    findings = check_text_pacing(project, _layout(project, make_prober({})))
    assert any("título com" in f.message for f in findings)


# ---------- check_overlap ----------


def test_check_overlap_flags_overlay_after_total(tmp_path):
    _touch(tmp_path, "take.mp4")
    spec = {
        "name": "p",
        "output": {"preset": "instagram/reels"},
        "timeline": [{"type": "clip", "src": "take.mp4", "start": 0, "end": 2}],
        "overlays": [{"type": "text", "text": "Tarde demais", "role": "title", "start": 5, "end": 6}],
        "audio": {"normalize": "off"},
    }
    project = _project(tmp_path, spec)
    findings = check_overlap(project, _layout(project, make_prober({})))
    assert any("depois do fim" in f.message for f in findings)


def test_check_overlap_flags_same_role_and_position(tmp_path):
    _touch(tmp_path, "take.mp4")
    spec = {
        "name": "p",
        "output": {"preset": "instagram/reels"},
        "timeline": [{"type": "clip", "src": "take.mp4", "start": 0, "end": 4}],
        "overlays": [
            {"type": "text", "text": "Primeiro", "role": "title", "start": 0, "end": 3},
            {"type": "text", "text": "Segundo", "role": "title", "start": 1, "end": 2},
        ],
        "audio": {"normalize": "off"},
    }
    project = _project(tmp_path, spec)
    findings = check_overlap(project, _layout(project, make_prober({})))
    assert any("mesmo lugar" in f.message for f in findings)


def test_check_overlap_clean_when_sequential(tmp_path):
    _touch(tmp_path, "take.mp4")
    spec = {
        "name": "p",
        "output": {"preset": "instagram/reels"},
        "timeline": [{"type": "clip", "src": "take.mp4", "start": 0, "end": 4}],
        "overlays": [
            {"type": "text", "text": "Primeiro", "role": "title", "start": 0, "end": 1.5},
            {"type": "text", "text": "Segundo", "role": "title", "start": 1.5, "end": 3},
        ],
        "audio": {"normalize": "off"},
    }
    project = _project(tmp_path, spec)
    assert check_overlap(project, _layout(project, make_prober({}))) == []


# ---------- check_contrast ----------


def test_check_contrast_flags_low_contrast_card(tmp_path):
    spec = {
        "name": "p",
        "output": {"preset": "instagram/reels"},
        "timeline": [{"type": "card", "title": "Contraste ruim", "duration": 2, "background": "#FFFFFF"}],
        "audio": {"normalize": "off"},
    }
    project = _project(tmp_path, spec)
    findings = check_contrast(project, _layout(project, make_prober({})))
    assert any("contraste baixo" in f.message for f in findings)


def test_check_contrast_flags_overlay_box_same_colors(tmp_path):
    _touch(tmp_path, "take.mp4")
    spec = {
        "name": "p",
        "output": {"preset": "instagram/reels"},
        "timeline": [{"type": "clip", "src": "take.mp4", "start": 0, "end": 4}],
        "overlays": [
            {
                "type": "text",
                "text": "Saiba mais",
                "role": "cta",
                "start": 0,
                "end": 3,
                "style": {"color": "#222222", "box_color": "#262626"},
            }
        ],
        "audio": {"normalize": "off"},
    }
    project = _project(tmp_path, spec)
    findings = check_contrast(project, _layout(project, make_prober({})))
    assert any("contraste baixo" in f.message for f in findings)


def test_check_contrast_clean_for_brand_card(tmp_path):
    spec = {
        "name": "p",
        "output": {"preset": "instagram/reels"},
        "brand": "medlycare",
        "timeline": [{"type": "card", "title": "Abertura", "duration": 2}],
        "audio": {"normalize": "off"},
    }
    project = _project(tmp_path, spec)
    assert check_contrast(project, _layout(project, make_prober({}))) == []


# ---------- check_captions ----------


def test_check_captions_no_store_is_clean(tmp_path):
    _touch(tmp_path, "take.mp4")
    spec = {
        "name": "p",
        "output": {"preset": "instagram/reels"},
        "timeline": [{"type": "clip", "src": "take.mp4", "start": 0, "end": 4}],
        "captions": {"source": "auto"},
        "audio": {"normalize": "off"},
    }
    project = _project(tmp_path, spec)
    assert check_captions(project, _layout(project, make_prober({}))) == []


def test_check_captions_flags_long_short_and_long_duration_cues(tmp_path):
    _touch(tmp_path, "take.mp4")
    spec = {
        "name": "p",
        "output": {"preset": "instagram/reels"},
        "timeline": [{"type": "clip", "src": "take.mp4", "start": 0, "end": 6}],
        "captions": {"source": "auto", "vocabulary": ["Whisper"]},
        "audio": {"normalize": "off"},
    }
    project = _project(tmp_path, spec)
    long_text = "x" * 60
    data = {
        "language": "pt",
        "cues": [
            {
                "start": 0.0,
                "end": 0.8,
                "text": long_text,
                "words": [{"start": 0.0, "end": 0.8, "text": long_text}],
            },
            {"start": 1.0, "end": 1.05, "text": "oi", "words": [{"start": 1.0, "end": 1.05, "text": "oi"}]},
            {
                "start": 1.2,
                "end": 9.0,
                "text": "linha muito longa no tempo",
                "words": [{"start": 1.2, "end": 9.0, "text": "linha"}],
            },
            {
                "start": 9.1,
                "end": 9.3,
                "text": "wisper",
                "words": [{"start": 9.1, "end": 9.3, "text": "wisper"}],
            },
        ],
    }
    (tmp_path / "captions.auto.json").write_text(json.dumps(data), encoding="utf-8")
    findings = check_captions(project, _layout(project, make_prober({})))
    messages = [f.message for f in findings]
    assert sum("cue longa" in m for m in messages) >= 2  # texto longo e duração longa
    assert any("cue curta" in m for m in messages)
    assert any("Whisper" in m for m in messages)


def test_check_captions_flags_speech_gap(tmp_path):
    _touch(tmp_path, "take.mp4")
    spec = {
        "name": "p",
        "output": {"preset": "instagram/reels"},
        "timeline": [{"type": "clip", "src": "take.mp4", "start": 0, "end": 6}],
        "captions": {"source": "auto"},
        "audio": {"normalize": "off"},
    }
    project = _project(tmp_path, spec)
    data = {"language": "pt", "cues": [{"start": 0.0, "end": 0.5, "text": "oi", "words": []}]}
    (tmp_path / "captions.auto.json").write_text(json.dumps(data), encoding="utf-8")
    findings = check_captions(project, _layout(project, make_prober({})))
    assert any("sem legenda em fala" in f.message for f in findings)


# ---------- check_sources ----------


def test_check_sources_flags_no_audio_at_all(tmp_path):
    _touch(tmp_path, "take.mp4")
    spec = {
        "name": "p",
        "output": {"preset": "instagram/reels"},
        "timeline": [{"type": "clip", "src": "take.mp4", "start": 0, "end": 4, "mute": True}],
        "audio": {"normalize": "off"},
    }
    project = _project(tmp_path, spec)
    findings = check_sources(project, _layout(project, make_prober({})))
    assert any("sem áudio" in f.message for f in findings)


def test_check_sources_clean_with_music(tmp_path):
    _touch(tmp_path, "take.mp4")
    _touch(tmp_path, "song.mp3")
    spec = {
        "name": "p",
        "output": {"preset": "instagram/reels"},
        "timeline": [{"type": "clip", "src": "take.mp4", "start": 0, "end": 4, "mute": True}],
        "audio": {"normalize": "off", "music": {"src": "song.mp3"}},
    }
    project = _project(tmp_path, spec)
    findings = check_sources(project, _layout(project, make_prober({})))
    assert not any("sem áudio" in f.message for f in findings)


def test_check_sources_flags_small_image_upscale(tmp_path):
    _touch(tmp_path, "print.png")
    spec = {
        "name": "p",
        "output": {"preset": "instagram/reels"},  # 1080x1920
        "timeline": [{"type": "image", "src": "print.png", "duration": 2}],
        "audio": {"normalize": "off"},
    }
    project = _project(tmp_path, spec)
    findings = check_sources(project, _layout(project, make_prober({"print.png": SMALL_IMAGE_INFO})))
    assert any("precisa ampliar" in f.message for f in findings)


def test_check_sources_clean_for_big_image(tmp_path):
    _touch(tmp_path, "print.png")
    spec = {
        "name": "p",
        "output": {"preset": "instagram/reels"},
        "timeline": [{"type": "image", "src": "print.png", "duration": 2}],
        "audio": {"normalize": "off"},
    }
    project = _project(tmp_path, spec)
    big = MediaInfo(Path("print.png"), 0.0, 2000, 3000, 0.0, True, False, True)
    assert check_sources(project, _layout(project, make_prober({"print.png": big}))) == []


# ---------- OutputInspector ----------


def test_output_inspector_flags_black_silence_and_loudness(tmp_path):
    video = tmp_path / "out.mp4"
    video.write_bytes(b"x")
    prober = lambda p: MediaInfo(p, 10.0, 1080, 1920, 30.0, True, True, False)  # noqa: E731
    stderr = (
        "[blackdetect @ 0x1] black_start:2.000000 black_end:3.000000 black_duration:1.000000\n"
        "[silencedetect @ 0x1] silence_start: 4.0\n"
        "[silencedetect @ 0x1] silence_end: 8.0 | silence_duration: 4.0\n"
        '{ "input_i" : "-20.00", "input_tp" : "-0.50" }\n'
    )
    runner = RecordingRunner(capture_stderr=stderr)
    inspector = OutputInspector(runner, prober)
    findings = inspector.inspect(video, 10.0, get_preset("instagram/reels"), -14.0)
    messages = [f.message for f in findings]
    assert any("quadros pretos" in m for m in messages)
    assert any("silêncio" in m for m in messages)
    assert any("loudness integrado" in m for m in messages)
    assert any("pico verdadeiro" in m for m in messages)


def test_output_inspector_flags_duration_and_resolution_mismatch(tmp_path):
    video = tmp_path / "out.mp4"
    video.write_bytes(b"x")
    prober = lambda p: MediaInfo(p, 3.0, 640, 480, 30.0, True, True, False)  # noqa: E731
    inspector = OutputInspector(RecordingRunner(capture_stderr=""), prober)
    findings = inspector.inspect(video, 10.0, get_preset("instagram/reels"), -14.0)
    levels_by_where = {(f.level, f.where) for f in findings}
    assert ("erro", "saída") in levels_by_where
    assert any("duração" in f.message for f in findings)
    assert any("resolução" in f.message for f in findings)


def test_output_inspector_clean_output(tmp_path):
    video = tmp_path / "out.mp4"
    video.write_bytes(b"x")
    preset = get_preset("instagram/reels")
    prober = lambda p: MediaInfo(p, 10.0, preset.width, preset.height, preset.fps, True, True, False)  # noqa: E731
    inspector = OutputInspector(RecordingRunner(capture_stderr=""), prober)
    assert inspector.inspect(video, 10.0, preset, -14.0) == []


# ---------- QAReport.to_text / to_dict ----------


def test_qa_report_to_text_format():
    findings = [
        Finding("erro", "saída", "duração diferente", 12.3),
        Finding("aviso", "overlays[0].text", "contraste baixo", 1.0),
        Finding("info", "legendas", "trecho sem legenda", None),
    ]
    report = QAReport(
        "meu-projeto", 42.0, findings, checks=["checagem a", "checagem b"], preset="instagram/reels"
    )
    text = report.to_text()
    assert text.startswith("QA meu-projeto (instagram/reels, 00:42): 1 erro(s), 1 aviso(s), 1 info(s)")
    assert "[00:12] erro: saída: duração diferente" in text
    assert "info: legendas: trecho sem legenda" in text
    assert "Checagens feitas: checagem a; checagem b" in text
    assert "—" not in text  # sem travessão em texto para o usuário


def test_qa_report_to_dict_roundtrip():
    findings = [Finding("aviso", "audio", "sem áudio")]
    report = QAReport("p", 1.0, findings, checks=["c"], preset="instagram/reels")
    data = report.to_dict()
    assert data["findings"] == [{"level": "aviso", "where": "audio", "message": "sem áudio", "at": None}]
    assert data["project"] == "p" and data["preset"] == "instagram/reels"


# ---------- build_report ----------


def test_build_report_static_only(tmp_path):
    _touch(tmp_path, "take.mp4")
    spec = {
        "name": "meu-projeto",
        "output": {"preset": "instagram/reels"},
        "timeline": [{"type": "clip", "src": "take.mp4", "start": 0, "end": 4}],
        "audio": {"normalize": "off"},
    }
    project = _project(tmp_path, spec)
    report = build_report(project, prober=make_prober({}))
    assert report.project == "meu-projeto" and report.preset == "instagram/reels"
    assert len(report.checks) == len(STATIC_CHECKS)
    assert "Checagens feitas" in report.to_text()


def test_build_report_with_output_adds_output_checks(tmp_path):
    _touch(tmp_path, "take.mp4")
    spec = {
        "name": "meu-projeto",
        "output": {"preset": "instagram/reels"},
        "timeline": [{"type": "clip", "src": "take.mp4", "start": 0, "end": 4}],
        "audio": {"normalize": "off"},
    }
    project = _project(tmp_path, spec)
    video = tmp_path / "out.mp4"
    video.write_bytes(b"x")
    preset = get_preset("instagram/reels")
    prober = make_prober(
        {"out.mp4": MediaInfo(video, 4.0, preset.width, preset.height, preset.fps, True, True, False)}
    )
    runner = RecordingRunner(capture_stderr="")
    report = build_report(project, prober=prober, output=video, runner=runner)
    assert len(report.checks) == len(STATIC_CHECKS) + 1
    assert any("saída renderizada" in c for c in report.checks)
