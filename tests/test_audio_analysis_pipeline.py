"""A análise de áudio no pipeline, sem ffmpeg de verdade: o runner falso "decodifica" gravando um WAV a partir de amostras
que o teste escolheu, então dá para provar o recorte, o ganho, o relógio do item e os marcadores com números exatos."""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np
import pytest

from dmaker import config
from dmaker.analysis import parse_analyzer
from dmaker.analysis.analyzers.contrast import speech_contrast
from dmaker.analysis.registry import MarkerProposal
from dmaker.analysis.rhythm import ON_BEAT_SECONDS, nearest_beat, propose_beat_cuts
from dmaker.domain.edits import EditError
from dmaker.domain.spec import Marker, Project
from dmaker.media.decode import decode_to_wav
from dmaker.media.ffmpeg import FFmpegCommand, RecordingRunner
from dmaker.media.probe import MediaInfo
from dmaker.media.wavio import read_wav_float, write_wav_channels
from dmaker.pipeline.analysis_items import ItemClock, TargetError, parse_target
from dmaker.pipeline.audio_analysis import (
    AnalysisRequest,
    AudioAnalysisService,
    export_result,
    marker_dicts,
)
from dmaker.pipeline.edits import apply_edit_report
from dmaker.pipeline.final_output import latest_final_output

RATE = 48000


def tone(hz: float, seconds: float, amp: float = 0.5) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return amp * np.sin(2 * np.pi * hz * t)


# ---------- ler WAV de qualquer profundidade ----------


def riff(fmt: bytes, data: bytes, *, extra: bytes = b"") -> bytes:
    body = (
        b"WAVE"
        + b"fmt "
        + struct.pack("<I", len(fmt))
        + fmt
        + extra
        + b"data"
        + struct.pack("<I", len(data))
        + data
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body


def fmt_chunk(tag: int, channels: int, rate: int, bits: int) -> bytes:
    block = channels * bits // 8
    return struct.pack("<HHIIHH", tag, channels, rate, rate * block, block, bits)


def test_read_wav_float_reads_float_32_with_a_list_chunk_before_the_data(tmp_path):
    samples = np.array([[0.5, -0.25], [1.5, -2.0], [0.0, 0.125]], dtype="<f4")
    extra = b"LIST" + struct.pack("<I", 5) + b"abcde" + b"\x00"  # bloco ímpar, com o byte de enchimento
    path = tmp_path / "f32.wav"
    path.write_bytes(riff(fmt_chunk(3, 2, 44100, 32), samples.tobytes(), extra=extra))
    frames, rate = read_wav_float(path)
    assert rate == 44100 and frames.shape == (3, 2)
    assert np.array_equal(
        frames, samples
    )  # o que passa de 1,0 continua inteiro: é por isso que o arquivo é flutuante


def test_read_wav_float_reads_sixteen_and_twenty_four_bits_and_a_slice(tmp_path):
    values = np.linspace(-1, 1, 4800).astype(np.float32)
    sixteen = write_wav_channels(tmp_path / "s16.wav", values.reshape(-1, 1), 4800)
    frames, rate = read_wav_float(sixteen)
    assert rate == 4800 and frames.shape == (4800, 1)
    assert np.allclose(frames[:, 0], values, atol=1e-3)
    cut, _ = read_wav_float(sixteen, start=0.25, duration=0.5)
    assert cut.shape == (2400, 1) and np.allclose(cut[:, 0], values[1200:3600], atol=1e-3)
    assert read_wav_float(sixteen, start=5.0)[0].shape == (0, 1)  # depois do fim: vazio, sem erro

    ints = np.round(values * 8388607).astype(np.int32)
    packed = b"".join(int(v).to_bytes(4, "little", signed=True)[:3] for v in ints)
    twenty_four = tmp_path / "s24.wav"
    twenty_four.write_bytes(riff(fmt_chunk(1, 1, 4800, 24), packed))
    assert np.allclose(read_wav_float(twenty_four)[0][:, 0], values, atol=1e-6)


def test_read_wav_float_accepts_the_extensible_format_and_refuses_what_it_cannot_read(tmp_path):
    extensible = struct.pack("<HHIIHH", 0xFFFE, 1, 8000, 32000, 4, 32) + struct.pack("<HHI", 22, 32, 4)
    extensible += struct.pack("<H", 3) + b"\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"
    path = tmp_path / "ext.wav"
    path.write_bytes(riff(extensible, np.array([0.25, 0.5], dtype="<f4").tobytes()))
    assert read_wav_float(path)[0][:, 0].tolist() == [0.25, 0.5]
    (tmp_path / "not.wav").write_bytes(b"isto nao e um wav")
    with pytest.raises(ValueError, match="não é um WAV"):
        read_wav_float(tmp_path / "not.wav")
    odd = tmp_path / "odd.wav"
    odd.write_bytes(riff(fmt_chunk(1, 1, 8000, 12), b"\x00\x00"))
    with pytest.raises(ValueError, match="não é suportado"):
        read_wav_float(odd)


def test_decode_to_wav_builds_a_float_command_with_the_slice_and_the_stream(tmp_path):
    runner = RecordingRunner()
    decode_to_wav(
        runner, tmp_path / "video.mp4", tmp_path / "saida" / "a.wav", start=1.5, duration=2.0, stream=1
    )
    command = runner.commands[0]
    assert command[command.index("-ss") + 1] == "1.500000" and command[command.index("-t") + 1] == "2.000000"
    assert command.index("-ss") < command.index("-i")  # pula direto, sem decodificar o começo
    assert command[command.index("-map") + 1] == "0:a:1"
    assert command[command.index("-c:a") + 1] == "pcm_f32le"
    assert "-ar" not in command and "-ac" not in command  # taxa e canais da fonte
    assert (tmp_path / "saida").is_dir()


# ---------- o alvo e o relógio do item ----------


def test_targets_are_parsed_and_the_invalid_ones_listed():
    assert parse_target("timeline.3") == ("timeline", 3)
    assert parse_target("audio.voiceover.0") == ("audio.voiceover", 0)
    assert parse_target("audio.music") == ("audio.music", None)
    with pytest.raises(TargetError, match="alvo de análise inválido"):
        parse_target("audio.music.2")
    with pytest.raises(TargetError, match="alvo de análise inválido"):
        parse_target("master")


def test_the_item_clock_turns_item_time_into_project_time_and_back():
    clock = ItemClock(start=10.0, speed=2.0)
    assert clock.to_project(4.0) == 12.0 and clock.to_item(12.0) == 4.0
    assert ItemClock().to_project(3.0) == 3.0


def test_markers_from_an_analysis_land_on_the_project_timeline():
    proposals = [
        MarkerProposal(1.0, None, "Batida 1"),
        MarkerProposal(2.0, 3.0, "Som 1"),
        MarkerProposal(9.0, 11.0, "Passa do fim"),
        MarkerProposal(20.0, None, "Fora"),
    ]
    dicts = marker_dicts(
        proposals, offset=0.5, clock=ItemClock(start=2.0, speed=1.0), total=12.0, color="#e8590c"
    )
    assert dicts[0] == {"at": 3.5, "text": "Batida 1", "color": "#e8590c"}
    assert dicts[1]["start"] == 4.5 and dicts[1]["end"] == 5.5
    assert dicts[2]["start"] == 11.5 and dicts[2]["end"] == 12.0  # a região é cortada no fim do vídeo
    assert len(dicts) == 3  # o que cai depois do fim some
    fast = marker_dicts(proposals[:1], 0.0, ItemClock(start=0.0, speed=2.0), 12.0, None)
    assert fast == [{"at": 0.5, "text": "Batida 1"}]  # a 2x, 1 s do áudio dura 0,5 s na linha do tempo
    assert marker_dicts(proposals[:1], 0.0, None, 12.0, None) == [{"at": 1.0, "text": "Batida 1"}]


# ---------- a operação que troca um grupo de marcadores ----------


def project_with_markers() -> Project:
    project = Project.model_validate(
        {
            "name": "grupos",
            "timeline": [{"type": "card", "title": "x", "duration": 20.0}],
            "markers": [
                {"at": 1.0, "text": "meu"},
                {"at": 2.0, "text": "antigo", "group": "sons"},
                {"start": 3.0, "end": 4.0, "text": "outro", "group": "cena"},
            ],
        }
    )
    return project


def test_marker_group_set_replaces_only_that_group_in_one_step():
    project = project_with_markers()
    created = [{"at": 5.0, "text": "novo"}, {"start": 6.0, "end": 7.0, "text": "região", "color": "#2f9e44"}]
    report = apply_edit_report(project, {"type": "marker_group_set", "group": "sons", "markers": created})
    groups = {m.group: [] for m in report.project.markers}
    for marker in report.project.markers:
        groups[marker.group].append(marker.text)
    assert groups == {"": ["meu"], "cena": ["outro"], "sons": ["novo", "região"]}
    assert report.warnings == [] and project.markers[1].text == "antigo"  # a spec original não mudou
    cleared = apply_edit_report(report.project, {"type": "marker_group_set", "group": "sons", "markers": []})
    assert [m.text for m in cleared.project.markers] == ["meu", "outro"]


def test_marker_group_set_never_touches_the_default_track():
    with pytest.raises(EditError, match="grupo vazio"):
        apply_edit_report(project_with_markers(), {"type": "marker_group_set", "group": "", "markers": []})
    with pytest.raises(EditError, match="desconhecido"):
        apply_edit_report(
            project_with_markers(),
            {"type": "marker_group_set", "group": "sons", "markers": [{"at": 1.0, "cor": "x"}]},
        )


# ---------- exportar ----------


def test_export_result_picks_the_format_from_the_extension(tmp_path):
    signal_samples = tone(1000.0, 1.0).astype(np.float32).reshape(-1, 1)
    from dmaker.analysis import Signal

    spectrum = parse_analyzer("spectrum", {"size": 1024}).analyze(Signal(signal_samples, RATE))
    csv = export_result(spectrum, tmp_path / "pasta" / "espectro.csv")
    assert csv.read_text(encoding="utf-8").splitlines()[0] == "frequencia_hz,nivel_db"
    tsv = export_result(spectrum, tmp_path / "espectro.txt")
    assert tsv.read_text(encoding="utf-8").splitlines()[0] == "frequencia_hz\tnivel_db"
    png = export_result(spectrum, tmp_path / "espectro.png")
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    as_json = export_result(spectrum, tmp_path / "espectro.json")
    assert len(as_json.read_text(encoding="utf-8")) > len(csv.read_text(encoding="utf-8")) / 3
    clipping = parse_analyzer("clipping", {}).analyze(Signal(signal_samples, RATE))
    with pytest.raises(ValueError, match="não exporta uma tabela"):
        export_result(clipping, tmp_path / "clip.csv")
    with pytest.raises(ValueError, match="só o Espectro"):
        export_result(clipping, tmp_path / "clip.png")
    with pytest.raises(ValueError, match="formato de arquivo desconhecido"):
        export_result(spectrum, tmp_path / "espectro.xyz")


# ---------- cortar no ritmo (a conta) ----------


def test_beat_cut_proposals_pick_the_nearest_beat_within_the_tolerance():
    beats = [0.25, 0.75, 1.25, 1.75, 2.25]
    proposals = propose_beat_cuts(
        [(0, 0.8), (1, 1.5), (2, 2.1)], beats, tolerance=0.1, skipped={2: "transição"}
    )
    assert proposals[0].beat == 0.75 and proposals[0].shift == pytest.approx(-0.05) and proposals[0].moves
    assert (
        proposals[1].beat is None
        and "0,1" not in (proposals[1].reason or "")
        and "0.1" in proposals[1].reason
    )
    assert proposals[2].beat is None and proposals[2].reason == "transição"
    on_beat = propose_beat_cuts([(0, 1.25 + ON_BEAT_SECONDS / 2)], beats, 0.2)[0]
    assert on_beat.beat == 1.25 and not on_beat.moves  # já está na batida: nada a andar
    assert propose_beat_cuts([(0, 3.0)], [], 0.5)[0].reason is not None
    assert (
        nearest_beat([1.0, 2.0], 1.4) == 1.0
        and nearest_beat([1.0, 2.0], 1.6) == 2.0
        and nearest_beat([], 1.0) is None
    )


# ---------- o contraste da fala (a conta do QA) ----------


def speech_and_music(music_db: float, speech_seconds: float = 4.0, total_seconds: float = 6.0):
    amplitude = lambda db: 10 ** (db / 20) * np.sqrt(2)  # noqa: E731
    voice = np.zeros(int(total_seconds * 16000))
    voice[: int(speech_seconds * 16000)] = tone_at(16000, 300.0, speech_seconds, amplitude(-20.0))
    music = tone_at(16000, 120.0, total_seconds, amplitude(music_db))
    return voice, music


def tone_at(rate: int, hz: float, seconds: float, amp: float) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return amp * np.sin(2 * np.pi * hz * t)


def test_speech_contrast_measures_only_where_there_is_speech():
    voice, music = speech_and_music(-45.0)
    result = speech_contrast(voice, music, 16000)
    assert result is not None and result.passes
    assert result.overall_db == pytest.approx(25.0, abs=0.5) and result.worst_db == pytest.approx(
        25.0, abs=0.5
    )
    assert (
        result.blocks == 4 and result.blocks_below == 0
    )  # as pausas (2 s de silêncio) não contam como blocos


def test_speech_contrast_flags_a_music_that_covers_the_voice_and_says_when():
    voice, music = speech_and_music(-30.0)
    music[2 * 16000 : 3 * 16000] *= 4.0  # a música sobe 12 dB no terceiro segundo
    result = speech_contrast(voice, music, 16000)
    assert result is not None and not result.passes
    assert result.worst_db == pytest.approx(-2.0, abs=0.5) and result.worst_at == pytest.approx(2.0, abs=0.05)
    assert result.blocks_below == 4  # -30 dB de fundo dá 10 dB nos outros três: nenhum chega a 20


def test_speech_contrast_gives_nothing_for_silence_or_a_speechless_track():
    assert speech_contrast(np.zeros(32000), np.ones(32000) * 0.1, 16000) is None
    assert speech_contrast(np.zeros(0), np.zeros(0), 16000) is None


# ---------- o serviço com o runner falso ----------


class FakeDecoder:
    """Um runner que "decodifica" gravando um WAV a partir das amostras escolhidas para cada arquivo de origem."""

    def __init__(self, sources: dict[str, np.ndarray]) -> None:
        self.sources = sources
        self.runner = RecordingRunner(on_run=self.decode)
        self.decoded: list[tuple[str, float, float | None]] = []

    def decode(self, command: FFmpegCommand) -> None:
        args = command.args
        src = Path(args[args.index("-i") + 1])
        start = float(args[args.index("-ss") + 1]) if "-ss" in args else 0.0
        length = float(args[args.index("-t") + 1]) if "-t" in args else None
        self.decoded.append((src.name, start, length))
        samples = self.sources[src.name]
        first = int(round(start * RATE))
        last = len(samples) if length is None else first + int(round(length * RATE))
        write_wav_channels(Path(args[-1]), samples[first:last].reshape(-1, 1).astype(np.float32), RATE)


def audio_info(path: Path, duration: float) -> MediaInfo:
    return MediaInfo(path, duration, 0, 0, 0.0, False, True, False, sample_rate=RATE, channels=1)


def make_service(decoder: FakeDecoder, durations: dict[str, float]) -> AudioAnalysisService:
    def prober(path: Path) -> MediaInfo:
        return audio_info(path, durations[path.name])

    return AudioAnalysisService(decoder.runner, prober)


def voice_project(tmp_path: Path, **clip) -> Project:
    (tmp_path / "fala.wav").write_bytes(b"x")
    project = Project.model_validate(
        {
            "name": "voz",
            "timeline": [{"type": "card", "title": "x", "duration": 12.0}],
            "audio": {"voiceover": [{"src": "fala.wav", **clip}], "normalize": "off"},
        }
    )
    project.base_dir = tmp_path
    return project


def test_a_voice_item_is_read_from_its_entry_point_with_its_gain(tmp_path):
    source = np.concatenate([tone(300.0, 1.0, 0.1), tone(300.0, 3.0, 0.4)])  # 1 s fraco e depois 3 s forte
    decoder = FakeDecoder({"fala.wav": source})
    service = make_service(decoder, {"fala.wav": 4.0})
    project = voice_project(tmp_path, start=2.0, offset=1.0, volume=0.5)
    outcome = service.analyze(project, AnalysisRequest("rms", target="audio.voiceover.0"))
    assert decoder.decoded == [("fala.wav", 1.0, 3.0)]  # a partir do ponto de entrada, só o que toca
    assert outcome.result.overall_rms_db == pytest.approx(
        -10.97 - 6.02, abs=0.05
    )  # 0,4 de amplitude e volume 0,5
    assert outcome.interval == pytest.approx((0.0, 3.0))
    assert outcome.label.startswith("Voz gravada 1")
    assert outcome.clock is not None and outcome.clock.start == 2.0


def test_the_interval_accepts_seconds_and_markers_in_project_time(tmp_path):
    source = tone(300.0, 4.0, 0.4)
    decoder = FakeDecoder({"fala.wav": source})
    service = make_service(decoder, {"fala.wav": 4.0})
    project = voice_project(tmp_path, start=2.0)
    project = project.model_copy(
        update={"markers": [Marker(at=3.5, text="meio"), Marker(at=1.0, text="antes")]}
    )
    by_seconds = service.analyze(
        project, AnalysisRequest("rms", target="audio.voiceover.0", start=1.0, end=2.5)
    )
    assert decoder.decoded[-1] == ("fala.wav", 1.0, 1.5) and by_seconds.interval == pytest.approx((1.0, 2.5))
    by_marker = service.analyze(
        project, AnalysisRequest("rms", target="audio.voiceover.0", start="marker:meio")
    )
    assert decoder.decoded[-1] == (
        "fala.wav",
        1.5,
        2.5,
    )  # 3,5 s do projeto é 1,5 s do áudio da voz que começa em 2 s
    with pytest.raises(TargetError, match="depois do fim"):
        service.analyze(project, AnalysisRequest("rms", target="audio.voiceover.0", start=9.0))
    with pytest.raises(TargetError, match="maior que start"):
        service.analyze(project, AnalysisRequest("rms", target="audio.voiceover.0", start=2.0, end=1.0))
    with pytest.raises(TargetError, match="não existe o marcador"):
        service.analyze(project, AnalysisRequest("rms", target="audio.voiceover.0", start="marker:nada"))
    del by_marker


def test_parameters_can_cite_markers_and_count_from_the_start_of_the_analysed_part(tmp_path):
    voice, background = tone(300.0, 2.0, rms_amp(-20.0)), tone(120.0, 2.0, rms_amp(-45.0))
    decoder = FakeDecoder({"fala.wav": np.concatenate([voice, background])})
    service = make_service(decoder, {"fala.wav": 4.0})
    project = voice_project(tmp_path, start=1.0)
    project = project.model_copy(update={"markers": [Marker(at=3.0, text="fundo")]})
    params = {
        "foreground_start": 0.0,
        "foreground_end": 2.0,
        "background_start": "marker:fundo",  # 3 s do projeto = 2 s do áudio da voz
        "background_end": 4.0,
    }
    outcome = service.analyze(project, AnalysisRequest("contrast", params, target="audio.voiceover.0"))
    assert outcome.result.difference_db == pytest.approx(25.0, abs=0.5) and outcome.result.passes


def rms_amp(db: float) -> float:
    return 10 ** (db / 20) * np.sqrt(2)


def test_a_missing_or_silent_target_is_refused_with_the_reason(tmp_path):
    decoder = FakeDecoder({})
    service = make_service(decoder, {"fala.wav": 4.0})
    project = voice_project(tmp_path)
    for target, message in (
        ("audio.voiceover.3", "voz gravada 3 não existe"),
        ("audio.music", "não tem música"),
        ("timeline.0", "não é um clipe"),
        ("overlays.0", "sobreposição 0 não existe"),
        ("audio.narration.0", "narração 0 não existe"),
    ):
        with pytest.raises(TargetError, match=message):
            service.analyze(project, AnalysisRequest("rms", target=target))
    with pytest.raises(ValueError, match="Analisador desconhecido"):
        service.analyze(project, AnalysisRequest("wavelet", target="audio.voiceover.0"))
    with pytest.raises(TargetError, match="não tem saída final renderizada"):
        service.analyze(project, AnalysisRequest("rms"))
    with pytest.raises(TargetError, match="arquivo não encontrado"):
        service.analyze(project, AnalysisRequest("rms", file=str(tmp_path / "nada.wav")))


def test_an_analysis_too_long_to_fit_in_memory_asks_for_an_interval(tmp_path):
    decoder = FakeDecoder({"fala.wav": tone(300.0, 1.0)})
    service = make_service(decoder, {"fala.wav": 3 * 3600.0})
    project = voice_project(tmp_path)
    with pytest.raises(TargetError, match="escolha um intervalo menor"):
        service.analyze(project, AnalysisRequest("rms", target="audio.voiceover.0"))
    assert decoder.decoded == []  # recusou antes de decodificar horas de áudio


def test_the_latest_final_output_is_the_newest_file_of_the_project_preset(tmp_path):
    project = voice_project(tmp_path)
    assert latest_final_output(project) is None
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (config.OUTPUT_DIR / "voz__instagram-reels.mp4").write_bytes(b"x")
    (config.OUTPUT_DIR / "outro__instagram-reels.mp4").write_bytes(b"x")
    assert latest_final_output(project) == config.OUTPUT_DIR / "voz__instagram-reels.mp4"
