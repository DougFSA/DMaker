"""Serviço de troca de voz: isolamento, conversor, sintetizador e ffmpeg falsos (sem modelo nem render)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dmaker import config
from dmaker.media.wavio import read_wav, wav_duration, write_wav
from dmaker.pipeline.voice_conversion import (
    REFERENCE_TEXTS,
    ConversionRequest,
    VoiceConversionService,
    default_output_path,
    stage_progress,
)
from dmaker.voice.library import VoiceNotFoundError
from tests.test_speech_fix import Harness, video_info
from tests.test_voice_watermark import FakeWatermarker

MODEL_RATE = 22050


class FakeConverter:
    """Devolve a própria fala a 22,05 kHz multiplicada por `factor` (um timbre "mais baixo" mensurável)."""

    engine_id = "fake-convert:1"

    def __init__(self, factor: float = 1.0) -> None:
        self.factor = factor
        self.calls: list[tuple[Path, Path]] = []
        self.blocks: list[float] = []

    def convert(self, source_vocals: Path, target_reference: Path, out: Path, on_progress=None) -> Path:
        self.calls.append((source_vocals, target_reference))
        samples, rate = read_wav(source_vocals)
        self.blocks.append(len(samples) / rate)
        count = round(len(samples) / rate * MODEL_RATE)
        resampled = np.interp(np.linspace(0, len(samples) - 1, count), np.arange(len(samples)), samples)
        return write_wav(out, (resampled * self.factor).astype(np.float32), MODEL_RATE)


class ServiceHarness(Harness):
    def __init__(
        self,
        tmp_path: Path,
        duration: float = 40.0,
        has_video: bool = True,
        factor: float = 1.0,
        watermarker: FakeWatermarker | None = None,
    ):
        super().__init__(tmp_path, duration=duration, has_video=has_video)
        self.converter = FakeConverter(factor)
        self.watermarker = watermarker
        self.conversion = VoiceConversionService(
            self.converter,
            self.isolation,
            self.library,
            self.synthesizer,
            self.runner,
            prober=lambda path: video_info(path, duration, has_video),
            watermarker=watermarker,
        )
        self.voice_seconds: float | None = None  # duração da fala convertida entregue ao ffmpeg
        self.voice_offset: float | None = None  # nível médio da fala convertida entregue ao ffmpeg

    def _on_run(self, command) -> None:
        super()._on_run(command)
        if command.label == "troca de voz":
            voice_file = Path(command.args[len(command.args) - 1 - command.args[::-1].index("-i") + 1])
            self.voice_seconds = wav_duration(voice_file)
            self.voice_offset = float(np.mean(read_wav(voice_file)[0]))

    def swap_command(self) -> list[str]:
        """O único comando ffmpeg do serviço (a separação é falsa e não usa o runner)."""
        (command,) = self.runner.commands
        return command

    def request(self, **options) -> ConversionRequest:  # type: ignore[override]
        defaults = {"src": self.src, "voice": "dora", "out": self.tmp_path / "saida.mp4"}
        return ConversionRequest(**{**defaults, **options})


@pytest.fixture
def harness(tmp_path: Path, monkeypatch) -> ServiceHarness:
    monkeypatch.setattr(config, "VOICE_CACHE_DIR", tmp_path / "voice-cache")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    return ServiceHarness(tmp_path / "media")


# ---------- o pedido ----------


def test_request_validates_voice_and_window():
    src = Path("a.mp4")
    with pytest.raises(ValueError, match="Escolha a voz"):
        ConversionRequest(src, voice="  ")
    with pytest.raises(ValueError, match="negativo"):
        ConversionRequest(src, voice="dora", start=-1)
    with pytest.raises(ValueError, match="maior que start"):
        ConversionRequest(src, voice="dora", start=5, end=2)


def test_default_output_name_carries_voice_and_window(harness: ServiceHarness):
    whole = default_output_path(harness.request(out=None), ".mp4")
    part = default_output_path(harness.request(out=None, start=10.0, end=30.0), ".mp4")
    assert whole.parent == config.OUTPUT_DIR / "troca-de-voz" and whole.name.startswith("entrevista.dora-")
    assert whole != part and whole.suffix == ".mp4"


# ---------- fluxo completo ----------


def test_whole_video_is_isolated_converted_in_blocks_and_remuxed_with_the_picture_untouched(
    harness: ServiceHarness,
):
    result = harness.conversion.convert(harness.request())

    assert harness.isolation.calls == [(None, None)]
    assert result.path == harness.tmp_path / "saida.mp4" and result.engine == "fake-convert:1"
    assert result.blocks == 2 == len(harness.converter.calls)  # 40 s partidos em dois blocos
    assert harness.converter.blocks[0] > 25.0 and harness.converter.blocks[1] > 15.0  # com a sobreposição
    args = harness.swap_command()
    assert args[args.index("-c:v") + 1] == "copy" and "-ss" not in args
    graph = args[args.index("-filter_complex") + 1]
    assert "atrim=duration=40.000" in graph
    assert set(result.timings) == {"separação", "referência", "conversão", "montagem"}


def test_converted_voice_has_the_exact_duration_of_the_source(harness: ServiceHarness):
    harness.conversion.convert(harness.request())
    assert harness.voice_seconds == pytest.approx(
        40.0, abs=1 / MODEL_RATE
    )  # a duração (e as pausas) não muda


def test_volume_of_the_converted_voice_is_matched_to_the_original(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "VOICE_CACHE_DIR", tmp_path / "voice-cache")
    quiet = ServiceHarness(tmp_path / "media", factor=0.5)  # metade da amplitude = 6 dB abaixo
    result = quiet.conversion.convert(quiet.request())
    assert result.gain_db == pytest.approx(6.02, abs=0.1)
    assert "volume=6.0" in quiet.swap_command()[quiet.swap_command().index("-filter_complex") + 1]


def test_gain_is_limited_so_a_broken_conversion_is_not_amplified(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "VOICE_CACHE_DIR", tmp_path / "voice-cache")
    silent = ServiceHarness(tmp_path / "media", factor=0.05)
    assert silent.conversion.convert(silent.request()).gain_db == 9.0


def test_excerpt_isolates_only_the_window_and_cuts_the_video(harness: ServiceHarness):
    harness.conversion.convert(harness.request(start=10.0, end=30.0))
    assert harness.isolation.calls == [(10.0, 30.0)]
    args = harness.swap_command()
    assert args[args.index("-ss") + 1] == "10.000" and args[args.index("-c:v") + 1] == "libx264"
    assert "atrim=duration=20.000" in args[args.index("-filter_complex") + 1]


def test_audio_file_is_remuxed_as_audio_with_the_source_extension(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "VOICE_CACHE_DIR", tmp_path / "voice-cache")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    audio = ServiceHarness(tmp_path / "media", duration=12.0, has_video=False)
    audio.src.rename(audio.src.with_suffix(".mp3"))
    audio.src = audio.src.with_suffix(".mp3")
    result = audio.conversion.convert(audio.request(out=None))
    assert result.path.suffix == ".mp3" and result.path.parent == config.OUTPUT_DIR / "troca-de-voz"
    assert "0:v:0" not in audio.swap_command() and "libmp3lame" in audio.swap_command()


def test_progress_goes_through_the_stages_in_order_up_to_one(harness: ServiceHarness):
    seen: list[tuple[str, float]] = []
    harness.conversion.convert(harness.request(), lambda stage, fraction: seen.append((stage, fraction)))
    stages = [stage for stage, _ in seen]
    assert stages[0] == "separação" and stages[-1] == "montagem" and "conversão" in stages
    fractions = [fraction for _, fraction in seen]
    assert fractions == sorted(fractions) and fractions[-1] == 1.0


def test_stage_progress_maps_blocks_into_the_stage_slice_of_the_bar():
    seen: list[float] = []
    update = stage_progress(lambda stage, fraction: seen.append(fraction), "conversão")
    update(1, 2)
    update(2, 2)
    assert 0.45 < seen[0] < seen[1] == pytest.approx(0.92)
    stage_progress(None, "conversão")(1, 2)  # sem relatório: não faz nada


# ---------- a voz alvo ----------


def test_preset_voice_gets_a_reference_synthesized_once_and_kept(harness: ServiceHarness):
    first = harness.conversion.convert(harness.request(voice="dora"))
    harness.conversion.convert(harness.request(voice="dora"))
    assert first.voice == "dora"
    assert len(harness.synthesizer.requests) == 1  # a segunda conversão reaproveitou a referência
    request = harness.synthesizer.requests[0]
    assert request.text == REFERENCE_TEXTS["pt"] and request.seed == 1 and request.voice.id == "dora"
    reference = harness.converter.calls[0][1]
    assert reference.parent == config.VOICE_CACHE_DIR / "convert-refs" and reference.exists()
    assert all(call[1] == reference for call in harness.converter.calls)


def test_each_voice_has_its_own_reference(harness: ServiceHarness):
    harness.conversion.convert(harness.request(voice="dora"))
    harness.conversion.convert(harness.request(voice="alex"))
    assert len(harness.synthesizer.requests) == 2
    assert harness.converter.calls[0][1] != harness.converter.calls[-1][1]


def test_cloned_voice_uses_its_recorded_reference_without_synthesizing(harness: ServiceHarness):
    folder = harness.library.root / "locutor"
    folder.mkdir(parents=True)
    write_wav(folder / "reference.wav", np.zeros(24000, dtype=np.float32), 24000)
    (folder / "voice.json").write_text(
        '{"id":"locutor","name":"Locutor","kind":"clone","reference":"reference.wav","reference_text":"oi"}',
        encoding="utf-8",
    )
    harness.conversion.convert(harness.request(voice="locutor"))
    assert harness.synthesizer.requests == []
    assert harness.converter.calls[0][1] == folder / "reference.wav"


def test_designed_voice_without_recording_gets_a_generated_reference(harness: ServiceHarness):
    harness.library.save_design("Narradora", "female, low pitch")
    harness.conversion.convert(harness.request(voice="narradora"))
    assert harness.synthesizer.requests[0].voice.kind == "design"


# ---------- erros ----------


def test_missing_file_unknown_voice_and_silent_media_fail_before_any_work(
    harness: ServiceHarness, tmp_path: Path
):
    with pytest.raises(FileNotFoundError, match="não encontrado"):
        harness.conversion.convert(harness.request(src=tmp_path / "nada.mp4"))
    with pytest.raises(VoiceNotFoundError, match="fantasma"):
        harness.conversion.convert(harness.request(voice="fantasma"))
    harness.conversion.prober = lambda path: video_info(path).__class__(
        path, 5.0, 0, 0, 0.0, False, False, False
    )
    with pytest.raises(ValueError, match="não tem áudio"):
        harness.conversion.convert(harness.request())
    assert harness.isolation.calls == [] and harness.converter.calls == []


# ---------- marca d'água (DMK-7) na fala convertida ----------


def test_converted_voice_gets_the_same_watermark_as_the_narration(tmp_path: Path, monkeypatch):
    """A fala convertida é voz gerada por IA: o marcador injetado a recebe inteira, antes de ir ao ffmpeg."""
    monkeypatch.setattr(config, "VOICE_CACHE_DIR", tmp_path / "voice-cache")
    marker = FakeWatermarker()
    marked = ServiceHarness(tmp_path / "media", watermarker=marker)
    marked.conversion.convert(marked.request())

    assert len(marker.embedded) == 1  # uma passada sobre o stem convertido inteiro, não por bloco
    assert marker.embedded[0] == pytest.approx(40.0 * MODEL_RATE, abs=MODEL_RATE)
    assert marked.voice_offset == pytest.approx(
        FakeWatermarker.OFFSET, abs=0.01
    )  # o que o ffmpeg recebeu é a fala marcada


def test_without_a_watermarker_the_conversion_follows_the_narration_switch(tmp_path: Path, monkeypatch):
    """Sem marcador injetado vale o padrão da narração; a suíte roda com DMAKER_WATERMARK=0, então não marca."""
    monkeypatch.setattr(config, "VOICE_CACHE_DIR", tmp_path / "voice-cache")
    plain = ServiceHarness(tmp_path / "media")
    assert plain.conversion.watermarker.identity == ""  # NullWatermarker: DMAKER_WATERMARK=0
    plain.conversion.convert(plain.request())
    assert plain.voice_offset == pytest.approx(0.0, abs=0.01)


def test_the_production_service_hands_the_watermarker_to_the_conversion(tmp_path: Path):
    from dmaker.pipeline.voice_conversion import default_voice_conversion_service

    marker = FakeWatermarker()
    harness = Harness(tmp_path / "media")
    service = default_voice_conversion_service(
        harness.runner,
        library=harness.library,
        isolation=harness.isolation,
        synthesizer=harness.synthesizer,
        converter=FakeConverter(),
        watermarker=marker,
    )
    assert service.watermarker is marker
