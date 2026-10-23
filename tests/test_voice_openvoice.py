"""OpenVoiceConverter com modelo falso (carga preguiçosa, embedding em cache, duração preservada) e o download
com tamanho e hash conferidos. A fumaça com o modelo real fica atrás de `DMAKER_VOICE_SMOKE=1`."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np
import pytest

from dmaker import config
from dmaker.media.wavio import read_wav, write_wav
from dmaker.voice.openvoice_converter import (
    CHECKPOINT,
    CONFIG,
    OpenVoiceConverter,
    RemoteFile,
    ensure_file,
)

torch = pytest.importorskip("torch")
pytest.importorskip("torchaudio")

MODEL_RATE = 22050


class FakeModel:
    """Imita o modelo: `ref_enc` devolve um vetor por espectrograma e a conversão devolve uma senoide por
    quadro, um quadro de 256 amostras mais curta que a entrada (como o modelo de verdade)."""

    def __init__(self) -> None:
        self.conversions: list[dict] = []
        self.embedded: list[int] = []

    def ref_enc(self, spectrogram):
        self.embedded.append(spectrogram.shape[1])
        return torch.full((1, 256), float(len(self.embedded)))

    def voice_conversion(self, spectrogram, lengths, sid_src, sid_tgt, tau):
        self.conversions.append({"src": float(sid_src.mean()), "tgt": float(sid_tgt.mean()), "tau": tau})
        samples = (int(lengths[0]) - 1) * 256
        return (torch.sin(torch.arange(samples) * 0.05).reshape(1, 1, -1) * 0.3,)


HPS = type(
    "Hps",
    (),
    {
        "data": type(
            "Data",
            (),
            {"sampling_rate": MODEL_RATE, "filter_length": 1024, "hop_length": 256, "win_length": 1024},
        )()
    },
)()


def loader_for(model: FakeModel, loads: list[int]):
    def load():
        loads.append(1)
        return model, HPS

    return load


def speech_file(path: Path, seconds: float = 3.0, rate: int = 44100) -> Path:
    t = np.arange(int(seconds * rate)) / rate
    return write_wav(path, 0.3 * np.sin(2 * np.pi * 180 * t) * (1 + np.sin(2 * np.pi * 3 * t)) / 2, rate)


@pytest.fixture
def converter_parts(tmp_path: Path):
    model, loads = FakeModel(), []
    converter = OpenVoiceConverter(models_dir=tmp_path / "models", model_loader=loader_for(model, loads))
    return converter, model, loads


# ---------- conversão ----------


def test_conversion_keeps_the_duration_of_the_source_at_the_model_rate(tmp_path: Path, converter_parts):
    converter, model, _ = converter_parts
    source, reference = speech_file(tmp_path / "fonte.wav"), speech_file(tmp_path / "ref.wav", 5.0, 24000)
    out = converter.convert(source, reference, tmp_path / "saida.wav")
    samples, rate = read_wav(out)
    assert rate == MODEL_RATE
    assert len(samples) == round(3.0 * MODEL_RATE)  # completou o quadro que o modelo cortou
    assert float(np.abs(samples).max()) > 0.1
    assert model.conversions[0]["tau"] == 0.3


def test_model_loads_once_and_only_on_the_first_conversion(tmp_path: Path, converter_parts):
    converter, _, loads = converter_parts
    assert loads == []
    source, reference = speech_file(tmp_path / "fonte.wav"), speech_file(tmp_path / "ref.wav", 5.0, 24000)
    converter.convert(source, reference, tmp_path / "a.wav")
    converter.convert(source, reference, tmp_path / "b.wav")
    assert loads == [1]


def test_target_embedding_is_computed_once_per_reference_file(tmp_path: Path, converter_parts):
    converter, model, _ = converter_parts
    source, reference = speech_file(tmp_path / "fonte.wav"), speech_file(tmp_path / "ref.wav", 5.0, 24000)
    converter.convert(source, reference, tmp_path / "a.wav")
    converter.convert(source, reference, tmp_path / "b.wav")
    # por conversão: 1 embedding da fonte; o do alvo só na primeira
    assert len(model.embedded) == 3
    assert model.conversions[0]["tgt"] == model.conversions[1]["tgt"]
    speech_file(reference, 6.0, 24000)  # a referência mudou no disco: o embedding vale de novo
    converter.convert(source, reference, tmp_path / "c.wav")
    assert len(model.embedded) == 5


def test_progress_reports_start_and_end(tmp_path: Path, converter_parts):
    converter, _, _ = converter_parts
    seen: list[tuple[int, int]] = []
    source, reference = speech_file(tmp_path / "fonte.wav"), speech_file(tmp_path / "ref.wav", 5.0, 24000)
    converter.convert(source, reference, tmp_path / "a.wav", lambda done, total: seen.append((done, total)))
    assert seen == [(0, 1), (1, 1)]


def test_models_dir_is_read_when_used_not_when_imported(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "outro")
    assert OpenVoiceConverter().models_dir == tmp_path / "outro" / "openvoice"
    assert OpenVoiceConverter(models_dir=tmp_path / "meu").models_dir == tmp_path / "meu"


def test_engine_id_names_the_model_for_the_cache():
    assert OpenVoiceConverter.engine_id == "openvoice:v2"


# ---------- download ----------


def _remote(content: bytes, name: str = "arquivo.bin") -> RemoteFile:
    return RemoteFile(name, f"https://exemplo.test/{name}", len(content), hashlib.sha256(content).hexdigest())


def test_download_is_verified_and_skipped_when_the_file_is_intact(tmp_path: Path):
    content, calls = b"pesos" * 100, []

    def downloader(url: str, destination: Path) -> None:
        calls.append(url)
        destination.write_bytes(content)

    target = ensure_file(tmp_path / "m", _remote(content), downloader)
    again = ensure_file(tmp_path / "m", _remote(content), downloader)
    assert target == again and target.read_bytes() == content
    assert calls == ["https://exemplo.test/arquivo.bin"]
    assert not list((tmp_path / "m").glob("*.part"))


def test_corrupted_download_is_refused_and_leaves_no_file(tmp_path: Path):
    expected = _remote(b"certo" * 100)

    def downloader(url: str, destination: Path) -> None:
        destination.write_bytes(b"errado" * 100)

    with pytest.raises(RuntimeError, match="corrompido"):
        ensure_file(tmp_path / "m", expected, downloader)
    assert not list((tmp_path / "m").glob("arquivo*"))


def test_pinned_weights_point_to_a_fixed_revision_with_known_hashes():
    for remote in (CHECKPOINT, CONFIG):
        assert "/resolve/f36e7edfe1684461a8343844af60babc2efbb727/converter/" in remote.url
        assert len(remote.sha256) == 64 and remote.size > 0


# ---------- modelo real ----------


@pytest.mark.skipif(os.environ.get("DMAKER_VOICE_SMOKE") != "1", reason="defina DMAKER_VOICE_SMOKE=1")
def test_real_model_converts_a_spoken_sentence_and_stays_intelligible(tmp_path: Path):
    pytest.importorskip("kokoro_onnx")
    pytest.importorskip("faster_whisper")
    from dmaker.text.transcribe import WhisperTranscriber
    from dmaker.voice.kokoro import KokoroSynthesizer
    from dmaker.voice.library import VoiceLibrary
    from dmaker.voice.synth import VoiceRequest

    library, kokoro = VoiceLibrary(tmp_path / "v"), KokoroSynthesizer()
    text = "Hoje é um bom dia para gravar um vídeo. Vamos começar pelo primeiro passo."
    source = kokoro.synthesize(VoiceRequest(text=text, voice=library.get("alex")))
    target = kokoro.synthesize(VoiceRequest(text=text + " Depois, o segundo.", voice=library.get("dora")))
    source_wav = write_wav(tmp_path / "fonte.wav", source.samples, source.sample_rate)
    target_wav = write_wav(tmp_path / "alvo.wav", target.samples, target.sample_rate)

    out = OpenVoiceConverter().convert(source_wav, target_wav, tmp_path / "convertido.wav")

    samples, rate = read_wav(out)
    assert abs(len(samples) / rate - source.duration) / source.duration < 0.01
    heard = " ".join(c.text for c in WhisperTranscriber().transcribe(out, "pt").cues).lower()
    assert sum(word in heard for word in ("hoje", "bom dia", "gravar", "vídeo", "primeiro")) >= 4
