"""KokoroSynthesizer com modelo falso, e download com tamanho/hash conferidos."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from dmaker.media.downloads import RemoteFile, ensure_file
from dmaker.voice.kokoro import DEFAULT_PRESET, MODEL_FILES, VOICES_FILE, KokoroSynthesizer
from dmaker.voice.library import VoiceLibrary
from dmaker.voice.synth import VoiceRequest


class FakeKokoro:
    def __init__(self):
        self.calls: list[dict] = []

    def create(self, text, voice, speed=1.0, lang="en-us"):
        self.calls.append({"text": text, "voice": voice, "speed": speed, "lang": lang})
        return np.full(2400, 0.2, dtype=np.float64), 24000


def _synth(tmp_path, **kwargs):
    model = FakeKokoro()
    loads: list[int] = []

    def loader():
        loads.append(1)
        return model

    return KokoroSynthesizer(models_dir=tmp_path, model_loader=loader, **kwargs), model, loads


def test_speaks_with_the_preset_of_the_voice(tmp_path):
    synth, model, _ = _synth(tmp_path)
    alex = VoiceLibrary(tmp_path / "v").get("alex")
    speech = synth.synthesize(VoiceRequest(text="Olá.", voice=alex, speed=1.1))
    assert model.calls == [{"text": "Olá.", "voice": "pm_alex", "speed": 1.1, "lang": "pt-br"}]
    assert speech.samples.dtype == np.float32 and speech.sample_rate == 24000
    assert speech.duration == pytest.approx(0.1)


def test_without_voice_uses_the_default_preset_and_maps_language(tmp_path):
    synth, model, _ = _synth(tmp_path)
    synth.synthesize(VoiceRequest(text="Hello.", language="en"))
    synth.synthesize(VoiceRequest(text="Oi.", language="pt-BR"))
    assert [(c["voice"], c["lang"]) for c in model.calls] == [
        (DEFAULT_PRESET, "en-us"),
        (DEFAULT_PRESET, "pt-br"),
    ]


def test_model_loads_lazily_once(tmp_path):
    synth, _, loads = _synth(tmp_path)
    assert loads == []
    synth.synthesize(VoiceRequest(text="Um."))
    synth.synthesize(VoiceRequest(text="Dois."))
    assert loads == [1]


def test_rejects_voices_of_other_engines_and_speeds_out_of_range(tmp_path):
    synth, _, _ = _synth(tmp_path)
    design = VoiceLibrary(tmp_path / "v").save_design("Grave", "male")
    with pytest.raises(ValueError, match="não é uma voz pronta do Kokoro"):
        synth.synthesize(VoiceRequest(text="Oi.", voice=design))
    with pytest.raises(ValueError, match="velocidade"):
        synth.synthesize(VoiceRequest(text="Oi.", speed=3.0))


def test_variants_have_distinct_engine_ids_and_unknown_variant_fails(tmp_path):
    fast, _, _ = _synth(tmp_path)
    small, _, _ = _synth(tmp_path, variant="int8")
    assert fast.engine_id != small.engine_id and fast.cache_identity(VoiceRequest(text="x")) == fast.engine_id
    with pytest.raises(ValueError, match="Variante"):
        KokoroSynthesizer(variant="fp8")


def test_pinned_files_point_to_the_fixed_release_and_use_the_shared_download_code():
    from dmaker.media import downloads
    from dmaker.voice import kokoro

    for remote in (VOICES_FILE, *MODEL_FILES.values()):
        assert remote.url == f"{kokoro.RELEASE_URL}/{remote.name}" and "/model-files-v1.0/" in remote.url
    assert kokoro.ensure_file is downloads.ensure_file  # o download com hash mora num lugar só


def test_pinned_files_have_sizes_and_hashes():
    assert VOICES_FILE.size > 1_000_000 and len(VOICES_FILE.sha256) == 64
    assert all(len(f.sha256) == 64 and f.size > 1_000_000 for f in MODEL_FILES.values())
    assert MODEL_FILES["int8"].size < MODEL_FILES["fp32"].size


def _remote(content: bytes) -> RemoteFile:
    url = "https://exemplo.test/model-files-v1.0/modelo.bin"
    return RemoteFile("modelo.bin", url, len(content), hashlib.sha256(content).hexdigest())


def test_ensure_file_downloads_once_and_keeps_the_verified_file(tmp_path):
    content = b"pesos do modelo"
    urls: list[str] = []

    def downloader(url: str, destination: Path) -> None:
        urls.append(url)
        destination.write_bytes(content)

    target = ensure_file(tmp_path / "kokoro", _remote(content), downloader)
    again = ensure_file(tmp_path / "kokoro", _remote(content), downloader)
    assert target == again and target.read_bytes() == content
    assert len(urls) == 1 and urls[0].endswith("/model-files-v1.0/modelo.bin")
    assert not list((tmp_path / "kokoro").glob("*.part"))


@pytest.mark.parametrize("delivered", [b"pesos corrompid", b"pesos do modelo!"])
def test_ensure_file_rejects_a_wrong_download(tmp_path, delivered):
    expected = _remote(b"pesos do modelo")

    def downloader(url: str, destination: Path) -> None:
        destination.write_bytes(delivered)

    with pytest.raises(RuntimeError, match="corrompido"):
        ensure_file(tmp_path, expected, downloader)
    assert list(tmp_path.iterdir()) == []


def test_ensure_file_replaces_a_damaged_file(tmp_path):
    content = b"pesos do modelo"
    (tmp_path / "modelo.bin").write_bytes(b"estragado")
    ensure_file(tmp_path, _remote(content), lambda url, dest: dest.write_bytes(content))
    assert (tmp_path / "modelo.bin").read_bytes() == content
