"""RoutingSynthesizer: o motor certo para cada voz e cache separado por motor."""

from __future__ import annotations

import numpy as np
import pytest

from dmaker.media.ffmpeg import RecordingRunner
from dmaker.pipeline.narration import NarrationService
from dmaker.voice.library import VoiceLibrary
from dmaker.voice.router import RoutingSynthesizer
from dmaker.voice.synth import Speech, VoiceRequest


class FakeEngine:
    def __init__(self, engine_id: str):
        self.engine_id = engine_id
        self.requests: list[VoiceRequest] = []

    def synthesize(self, request: VoiceRequest) -> Speech:
        self.requests.append(request)
        return Speech(np.zeros(2400, dtype=np.float32), 24000)


@pytest.fixture
def setup(tmp_path):
    library = VoiceLibrary(tmp_path / "voices")
    kokoro, omni = FakeEngine("fake-kokoro"), FakeEngine("fake-omni")
    router = RoutingSynthesizer(
        {"kokoro": kokoro, "omnivoice": omni}, default_voice_id="dora", library_factory=lambda: library
    )
    return router, kokoro, omni, library


def test_preset_goes_to_kokoro_and_clone_or_design_to_omnivoice(setup):
    router, kokoro, omni, library = setup
    router.synthesize(VoiceRequest(text="a", voice=library.get("alex")))
    router.synthesize(VoiceRequest(text="b", voice=library.save_design("Grave", "male")))
    assert [r.text for r in kokoro.requests] == ["a"] and [r.text for r in omni.requests] == ["b"]


def test_without_voice_the_default_voice_speaks_through_kokoro(setup):
    router, kokoro, omni, _ = setup
    router.synthesize(VoiceRequest(text="a"))
    assert omni.requests == [] and kokoro.requests[0].voice.id == "dora"


def test_instruct_without_voice_is_voice_design_for_omnivoice(setup):
    router, kokoro, omni, _ = setup
    router.synthesize(VoiceRequest(text="a", instruct="female, low pitch"))
    assert kokoro.requests == [] and omni.requests[0].voice is None


def test_default_voice_is_configurable(setup):
    router, kokoro, _, _ = setup
    router.default_voice_id = "santa"
    router.synthesize(VoiceRequest(text="a"))
    assert kokoro.requests[0].voice.preset == "pm_santa"


def test_cache_identity_follows_the_engine_and_the_default_voice(setup):
    router, _, _, library = setup
    preset = router.cache_identity(VoiceRequest(text="a", voice=library.get("dora")))
    design = router.cache_identity(VoiceRequest(text="a", voice=library.save_design("Grave", "male")))
    assert preset == "fake-kokoro" and design == "fake-omni"

    default_dora = router.cache_identity(VoiceRequest(text="a"))
    router.default_voice_id = "alex"
    default_alex = router.cache_identity(VoiceRequest(text="a"))
    assert default_dora != default_alex and default_dora.startswith("fake-kokoro|")


def test_missing_engine_is_a_clear_error(setup):
    _, _, omni, library = setup
    router = RoutingSynthesizer({"omnivoice": omni}, default_voice_id="dora", library_factory=lambda: library)
    with pytest.raises(RuntimeError, match="kokoro"):
        router.synthesize(VoiceRequest(text="a"))


def test_narration_cache_does_not_mix_engines(setup, tmp_path):
    router, _, _, library = setup
    service = NarrationService(router, RecordingRunner(), tmp_path / "cache")
    base = {"text": "Uma frase.", "language": "pt"}
    dora = service.cache_key(VoiceRequest(**base, voice=library.get("dora")))
    design = service.cache_key(VoiceRequest(**base, voice=library.save_design("Grave", "male")))
    default = service.cache_key(VoiceRequest(**base))
    assert len({dora, design, default}) == 3


def test_narration_without_voice_uses_the_default_voice(setup, tmp_path):
    router, kokoro, _, _ = setup
    out = tmp_path / "n.wav"
    runner = RecordingRunner(on_run=lambda command: out.write_bytes(b"a"))
    service = NarrationService(router, runner, tmp_path / "cache")
    service.render("Uma frase.", out, voice=None)
    service.render("Uma frase.", tmp_path / "m.wav", voice=None)
    assert len(kokoro.requests) == 1 and kokoro.requests[0].voice.id == "dora"


def test_without_default_voice_the_automatic_omnivoice_speaks(setup, monkeypatch):
    _, kokoro, omni, library = setup
    monkeypatch.setattr("dmaker.voice.router.DEFAULT_VOICE_ID", None)
    router = RoutingSynthesizer({"kokoro": kokoro, "omnivoice": omni}, library_factory=lambda: library)
    router.synthesize(VoiceRequest(text="a"))
    assert kokoro.requests == [] and omni.requests[0].voice is None
    assert router.cache_identity(VoiceRequest(text="a")) == "fake-omni"


def test_kokoro_stays_available_when_chosen_explicitly(setup, monkeypatch):
    _, kokoro, omni, library = setup
    monkeypatch.setattr("dmaker.voice.router.DEFAULT_VOICE_ID", None)
    router = RoutingSynthesizer({"kokoro": kokoro, "omnivoice": omni}, library_factory=lambda: library)
    router.synthesize(VoiceRequest(text="a", voice=library.get("santa")))
    assert [r.voice.id for r in kokoro.requests] == ["santa"] and omni.requests == []
