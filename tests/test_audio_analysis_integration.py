"""Os analisadores e as conferências do QA com ffmpeg de verdade: arquivos sintéticos gerados no teste, com a resposta
conhecida de antemão (o estouro inserido em 0,40 s, a batida a cada 0,5 s, a fala 25 dB acima do fundo).

O som passa pelo caminho real: o ffmpeg decodifica o arquivo (ou o `EffectProcessor` o processa), o analisador mede e, nos
que marcam, a operação `marker_group_set` grava o resultado na spec salva."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dmaker import config
from dmaker.domain.spec import Project
from dmaker.media import ffmpeg
from dmaker.media.ffmpeg import SubprocessRunner
from dmaker.media.probe import probe
from dmaker.media.wavio import write_wav_channels
from dmaker.pipeline.audio_analysis import AnalysisRequest, AudioAnalysisService, analyze_project
from dmaker.pipeline.audio_checks import audio_findings, voice_contrast_findings
from dmaker.pipeline.beat_cut import cut_on_beat
from dmaker.pipeline.layout import project_layout
from dmaker.pipeline.projects import load_project
from dmaker.pipeline.report import build_report

from .conftest import requires_ffmpeg
from .test_audio_effects_integration import make_video_with_tone, no_sync

pytestmark = requires_ffmpeg

RATE = 48000


def tone(hz: float, seconds: float, amp: float) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return amp * np.sin(2 * np.pi * hz * t)


def rms_amplitude(db: float) -> float:
    return 10 ** (db / 20) * np.sqrt(2)


def write_mono(path: Path, samples: np.ndarray) -> Path:
    return write_wav_channels(path, samples.reshape(-1, 1).astype(np.float32), RATE)


def click_track(bpm: float = 120.0, seconds: float = 8.0, offset: float = 0.25) -> np.ndarray:
    samples = np.zeros(int(seconds * RATE))
    click = tone(1000.0, 0.005, 0.8) * np.hanning(int(0.005 * RATE))
    for k in range(int((seconds - offset) / (60.0 / bpm))):
        start = int((offset + k * 60.0 / bpm) * RATE)
        samples[start : start + len(click)] += click
    return samples


def clipped_voice() -> tuple[np.ndarray, list[tuple[float, float]]]:
    spans = [(0.400, 0.4005), (1.000, 1.002), (1.500, 1.5008)]
    samples = tone(220.0, 2.5, 0.4)
    for start, end in spans:
        samples[int(start * RATE) : int(end * RATE)] = 1.0
    return samples, spans


def make_project(folder: Path, name: str = "analise", **fields) -> Project:
    data = {
        "name": name,
        "output": {"preset": "instagram/reels", "quality": "draft"},
        "timeline": [{"type": "clip", "src": "video.mp4", "start": 0, "end": 8, "mute": True}],
        **fields,
    }
    data.setdefault("audio", {})["normalize"] = "off"
    project = Project.model_validate(data)
    project.base_dir = folder
    return project


@pytest.fixture
def work(tmp_path) -> Path:
    make_video_with_tone(tmp_path / "video.mp4", seconds=8.0)
    return tmp_path


def service() -> AudioAnalysisService:
    return AudioAnalysisService(SubprocessRunner(quiet=True), probe, no_sync)


# ---------- Achar Clipping ----------


def test_find_clipping_gets_the_three_stretches_of_a_recorded_voice_within_one_millisecond(work):
    """Critério do card: 3 trechos estourados, com início e fim certos (±1 ms), pelo caminho real (ffmpeg → numpy)."""
    samples, spans = clipped_voice()
    write_mono(work / "voz.wav", samples)
    project = make_project(work, audio={"voiceover": [{"src": "voz.wav", "start": 1.0}]})
    outcome = service().analyze(project, AnalysisRequest("clipping", target="audio.voiceover.0"))
    assert len(outcome.result.regions) == 3
    for region, (start, end) in zip(outcome.result.regions, spans, strict=True):
        assert region.start == pytest.approx(start, abs=0.001)
        assert region.end == pytest.approx(end, abs=0.001)
    assert outcome.to_dict()["regions"][0]["channel"] == 1  # o resultado é JSON puro


def test_the_item_is_analysed_as_it_sounds_with_its_effects_and_its_gain(work):
    both = tone(
        220.0, 2.0, 0.5
    )  # estéreo: o item com efeito sai no formato da mixagem (estéreo), e um mono mudaria 3 dB
    write_wav_channels(work / "voz.wav", np.column_stack([both, both]).astype(np.float32), RATE)
    quiet = make_project(work, audio={"voiceover": [{"src": "voz.wav"}]})
    boosted = make_project(
        work, audio={"voiceover": [{"src": "voz.wav", "effects": [{"type": "amplify", "gain_db": 12}]}]}
    )
    loud = make_project(work, audio={"voiceover": [{"src": "voz.wav", "volume": 3.0}]})
    request = AnalysisRequest("clipping", target="audio.voiceover.0")
    assert service().analyze(quiet, request).result.regions == []
    # +12 dB leva o pico de 0,5 a 2,0: o arquivo processado (de ponto flutuante) estoura, e a análise enxerga
    assert len(service().analyze(boosted, request).result.regions) > 100
    assert len(service().analyze(loud, request).result.regions) > 100  # o volume do item também conta
    rms = AnalysisRequest("rms", target="audio.voiceover.0")
    base = service().analyze(quiet, rms).result.overall_rms_db
    assert service().analyze(boosted, rms).result.overall_rms_db == pytest.approx(base + 12.0, abs=0.1)
    assert service().analyze(quiet, AnalysisRequest("rms", file=str(work / "voz.wav"))).label == "voz.wav"


def test_clipping_in_a_slice_counts_from_the_start_of_the_slice(work):
    samples, spans = clipped_voice()
    write_mono(work / "voz.wav", samples)
    project = make_project(work, audio={"voiceover": [{"src": "voz.wav", "start": 1.0}]})
    outcome = service().analyze(
        project, AnalysisRequest("clipping", target="audio.voiceover.0", start=0.9, end=1.6)
    )
    assert [round(r.start, 3) for r in outcome.result.regions] == [
        pytest.approx(spans[1][0] - 0.9, abs=0.001)
    ] + [pytest.approx(spans[2][0] - 0.9, abs=0.001)]
    assert outcome.interval == pytest.approx((0.9, 1.6))


def test_marking_clipping_writes_a_red_group_at_project_time(work):
    samples, spans = clipped_voice()
    write_mono(work / "voz.wav", samples)
    make_project(work, audio={"voiceover": [{"src": "voz.wav", "start": 1.0}]}).save(work / "spec.json")
    outcome = analyze_project(
        work / "spec.json",
        AnalysisRequest("clipping", target="audio.voiceover.0", mark=True),
        service=service(),
    )
    markers = load_project(work / "spec.json").markers
    assert outcome.marker_group == "clipping" and outcome.markers_written == 3
    assert [m.group for m in markers] == ["clipping"] * 3 and {m.color for m in markers} == {"#e03131"}
    assert markers[0].begin == pytest.approx(1.0 + spans[0][0], abs=0.002)  # o áudio entra em 1 s no vídeo


# ---------- Espectro de Frequência ----------


def test_the_spectrum_of_a_one_khz_voice_peaks_at_the_one_khz_bin_and_exports_csv_and_png(work):
    write_mono(work / "tom.wav", tone(1000.0, 2.0, 0.5))
    make_project(work, audio={"voiceover": [{"src": "tom.wav"}]}).save(work / "spec.json")
    params = {"size": 4096}
    csv = work / "espectro.csv"
    outcome = analyze_project(
        work / "spec.json",
        AnalysisRequest("spectrum", params, target="audio.voiceover.0"),
        out=csv,
        service=service(),
    )
    result = outcome.result
    bin_hz = RATE / 4096
    assert result.peak_bin == round(1000 / bin_hz) and abs(result.peak_hz - 1000.0) < 1.0
    lines = csv.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "frequencia_hz,nivel_db" and len(lines) == 4096 // 2 + 2
    peak_row = lines[1 + result.peak_bin].split(",")
    assert float(peak_row[0]) == pytest.approx(result.peak_bin * bin_hz, abs=1e-3)
    assert float(peak_row[1]) == pytest.approx(20 * np.log10(0.5), abs=1.5)
    png = work / "espectro.png"
    analyze_project(
        work / "spec.json",
        AnalysisRequest("spectrum", params, target="audio.voiceover.0"),
        out=png,
        service=service(),
    )
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and png.stat().st_size > 2000


# ---------- Marcar Sons e Achar Batidas ----------


def test_label_sounds_marks_a_group_without_touching_the_users_markers(work):
    voice = np.concatenate([np.zeros(RATE), tone(300.0, 1.5, 0.3), np.zeros(2 * RATE), tone(300.0, 1.0, 0.3)])
    write_mono(work / "fala.wav", voice)
    project = make_project(
        work,
        audio={"voiceover": [{"src": "fala.wav", "start": 0.5}]},
        markers=[{"at": 2.0, "text": "meu marcador"}, {"at": 4.0, "text": "antigo", "group": "sons"}],
    )
    project.save(work / "spec.json")
    request = AnalysisRequest("sounds", {"min_silence": 1.0}, target="audio.voiceover.0")
    first = analyze_project(work / "spec.json", request, service=service())
    saved = load_project(work / "spec.json").markers
    sounds = [m for m in saved if m.group == "sons"]
    assert first.marker_group == "sons" and first.markers_written == 2
    assert [(round(m.begin, 2), round(m.finish, 2)) for m in sounds] == [
        (1.5, 3.0),
        (5.0, 6.0),
    ]  # voz entra em 0,5 s
    assert [m.text for m in saved if m.group == ""] == ["meu marcador"]  # os da pessoa ficam onde estavam
    analyze_project(work / "spec.json", request, service=service())  # rodar de novo não duplica
    assert len([m for m in load_project(work / "spec.json").markers if m.group == "sons"]) == 2
    custom = AnalysisRequest("sounds", {"min_silence": 1.0}, target="audio.voiceover.0", group="falas")
    analyze_project(work / "spec.json", custom, service=service())
    groups = sorted({m.group for m in load_project(work / "spec.json").markers})
    assert groups == ["", "falas", "sons"]
    no_marks = AnalysisRequest("sounds", target="audio.voiceover.0", mark=False)
    assert analyze_project(work / "spec.json", no_marks, service=service()).marker_group is None


def test_beat_finder_marks_a_beat_every_half_second_of_a_120_bpm_music_in_project_time(work):
    write_mono(work / "musica.wav", click_track(120.0, 8.0, 0.25))
    project = make_project(work, audio={"music": {"src": "musica.wav", "start_at": 0.1}})
    project.save(work / "spec.json")
    outcome = analyze_project(
        work / "spec.json", AnalysisRequest("beats", target="audio.music"), service=service()
    )
    beats = [m.begin for m in load_project(work / "spec.json").markers if m.group == "batidas"]
    assert outcome.marker_group == "batidas" and len(beats) == 15
    assert np.all(np.abs(np.diff(beats) - 0.5) <= 0.02)  # critério do card: a cada 0,5 s (±20 ms)
    assert beats[0] == pytest.approx(
        0.15, abs=0.02
    )  # o clique de 0,25 s do arquivo cai em 0,15 s: a música entra em 0,1 s
    assert outcome.result.bpm == pytest.approx(120.0, abs=1.0)


# ---------- o QA ----------


def lossless_output(work: Path, voice: np.ndarray) -> Path:
    """Um 'vídeo renderizado' sem perda: a imagem preta e o som PCM de 16 bits, para o estouro chegar ao arquivo inteiro."""
    wav = write_mono(work / "mix.wav", voice)
    out = work / "saida.mov"
    ffmpeg.run(
        ["-f", "lavfi", "-i", "color=c=black:size=320x180:rate=15:d=3", "-i", str(wav)]
        + [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "pcm_s16le",
            "-shortest",
            str(out),
        ],
        quiet=True,
    )
    return out


def test_the_qa_report_of_a_clipped_voice_points_at_the_clipping_with_the_instant(work):
    samples, spans = clipped_voice()
    write_mono(work / "voz.wav", samples)
    project = make_project(work, audio={"voiceover": [{"src": "voz.wav", "start": 0.0}]})
    output = lossless_output(work, samples)
    report = build_report(project, output=output, runner=SubprocessRunner(quiet=True), offset_finder=no_sync)
    clipping = [f for f in report.findings if "clipping" in f.message]
    on_output = [f for f in clipping if f.where == "saída"]
    on_item = [f for f in clipping if f.where == "audio.voiceover[0]"]
    assert len(on_output) == 3 and {f.level for f in on_output} == {"erro"}
    assert [f.at for f in on_output] == [pytest.approx(s, abs=0.002) for s, _ in spans]
    assert len(on_item) == 3 and {f.level for f in on_item} == {"aviso"}
    text = report.to_text()
    assert "erro: saída: som estourado no teto (clipping) em 0.40 s" in text
    assert (
        "clipping na saída" in text and "contraste entre voz e música" not in text
    )  # sem música não confere


def test_a_clean_voice_gets_no_clipping_finding(work):
    write_mono(work / "voz.wav", tone(220.0, 2.5, 0.4))
    project = make_project(work, audio={"voiceover": [{"src": "voz.wav"}]})
    findings, checks = audio_findings(
        project, lossless_output(work, tone(220.0, 2.5, 0.4)), SubprocessRunner(quiet=True), probe, no_sync
    )
    assert [f for f in findings if "clipping" in f.message] == [] and checks


def music_project(work: Path, music_db: float, *, ducking: bool = False) -> Project:
    voice = np.zeros(8 * RATE)
    voice[: 4 * RATE] = tone(300.0, 4.0, rms_amplitude(-20.0))
    write_mono(work / "fala.wav", voice)
    write_mono(work / "musica.wav", tone(120.0, 8.0, rms_amplitude(music_db)))
    return make_project(
        work,
        audio={
            "voiceover": [{"src": "fala.wav"}],
            "music": {"src": "musica.wav", "volume": 1.0, "ducking": ducking},
        },
    )


def test_voice_contrast_reproves_a_music_at_minus_30_and_passes_one_at_minus_45(work):
    """Critério do card: fala a -20 dBFS contra fundo a -45 dá 25 dB e passa; com fundo a -30 reprova com o aviso."""
    runner = SubprocessRunner(quiet=True)
    loud = voice_contrast_findings(music_project(work, -30.0), runner, probe, no_sync)
    assert len(loud) == 1 and loud[0].level == "aviso" and loud[0].where == "áudio"
    assert "só 10." in loud[0].message and "WCAG 1.4.7" in loud[0].message
    assert 0.0 <= loud[0].at < 4.0  # o instante do pior trecho cai na fala
    assert voice_contrast_findings(music_project(work, -45.0), runner, probe, no_sync) == []
    plain = make_project(work, audio={"voiceover": [{"src": "fala.wav"}]})
    assert voice_contrast_findings(plain, runner, probe, no_sync) == []  # projeto sem música não confere


def test_the_contrast_is_measured_after_the_ducking_the_music_suffers_under_the_voice(work):
    from dmaker.analysis.analyzers.contrast import speech_contrast
    from dmaker.pipeline.audio_render import AudioRenderPipeline
    from dmaker.pipeline.audio_stems import render_stem_levels
    from dmaker.pipeline.context import RenderOptions

    def worst(project: Project) -> float:
        pipeline = AudioRenderPipeline(
            project,
            RenderOptions(quiet=True, preset="audio/wav"),
            runner=SubprocessRunner(quiet=True),
            offset_finder=no_sync,
        )
        levels = render_stem_levels(pipeline, pipeline.prepare(), ("VO", "MUS"))
        result = speech_contrast(levels["VO"], levels["MUS"], 16000)
        assert result is not None
        return result.worst_db

    flat, ducked = worst(music_project(work, -30.0)), worst(music_project(work, -30.0, ducking=True))
    assert flat == pytest.approx(10.0, abs=1.0)
    assert ducked > flat + 3.0  # a música abaixada pelo sidechain é a que a pessoa ouve


# ---------- cortar no ritmo ----------


def beat_project(work: Path) -> Project:
    write_mono(work / "musica.wav", click_track(120.0, 8.0, 0.25))
    project = Project.model_validate(
        {
            "name": "ritmo",
            "output": {"preset": "instagram/reels", "quality": "draft"},
            "timeline": [
                {"type": "clip", "src": "video.mp4", "start": 0.0, "end": 2.1, "mute": True},
                {"type": "clip", "src": "video.mp4", "start": 2.1, "end": 4.2, "mute": True},
                {"type": "clip", "src": "video.mp4", "start": 4.2, "end": 6.3, "mute": True},
            ],
            "audio": {"music": {"src": "musica.wav"}, "normalize": "off"},
            "markers": [{"at": 5.0, "text": "depois"}],
        }
    )
    project.base_dir = work
    project.save(work / "spec.json")
    return project


def boundaries(work: Path) -> list[float]:
    project = load_project(work / "spec.json")
    layout = project_layout(project, probe, no_sync)
    return [span[1] for span in layout.spans[:-1]]


def test_cut_on_beat_proposes_first_and_only_moves_the_cuts_when_asked(work):
    beat_project(work)
    before = boundaries(work)
    proposal = cut_on_beat(work / "spec.json", service=service())
    assert proposal.applied is False and proposal.moved == 0 and proposal.bpm == pytest.approx(120.0, abs=1.0)
    assert [round(p.beat, 2) for p in proposal.proposals] == [2.25, 4.25]
    assert [round(p.shift, 2) for p in proposal.proposals] == [0.15, 0.05]
    assert boundaries(work) == before  # só propôs: a spec não mudou

    applied = cut_on_beat(work / "spec.json", apply=True, service=service())
    assert applied.moved == 2
    assert boundaries(work) == [pytest.approx(2.25, abs=0.02), pytest.approx(4.25, abs=0.02)]
    after = load_project(work / "spec.json")
    layout = project_layout(after, probe, no_sync)
    assert layout.total == pytest.approx(
        6.3, abs=0.02
    )  # a duração não muda: um corte anda, o vizinho acompanha
    assert [m.begin for m in after.markers] == [
        pytest.approx(5.0, abs=0.02)
    ]  # o marcador acompanha pelo mapa de tempo


def test_cut_on_beat_skips_a_boundary_with_a_transition_and_refuses_a_single_clip(work):
    project = beat_project(work)
    data = project.model_dump(mode="json")
    data["timeline"][1]["transition"] = {"type": "fade", "duration": 0.3}
    Project.model_validate(data).save(work / "spec.json")
    outcome = cut_on_beat(work / "spec.json", service=service())
    assert (
        outcome.proposals[0].reason == "há uma transição entre os trechos"
        and outcome.proposals[0].beat is None
    )
    data["timeline"] = data["timeline"][:1]
    Project.model_validate(data).save(work / "spec.json")
    with pytest.raises(ValueError, match="um trecho só"):
        cut_on_beat(work / "spec.json", service=service())


def test_the_qa_data_dir_is_isolated_from_the_real_one():
    assert config.CACHE_DIR.is_relative_to(config.DATA_DIR)
