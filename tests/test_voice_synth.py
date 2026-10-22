"""OmniVoiceSynthesizer com um modelo falso: carregamento preguiçoso, prompts, âncora e fallback."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dmaker.media.ffmpeg import RecordingRunner
from dmaker.media.wavio import write_wav
from dmaker.voice.library import VoiceLibrary
from dmaker.voice.synth import ANCHOR_TEXTS, DEFAULT_STEPS, DRAFT_STEPS, OmniVoiceSynthesizer, VoiceRequest

torch = pytest.importorskip("torch")
omnivoice = pytest.importorskip("omnivoice")


class FakeModel:
    sampling_rate = 24000

    def __init__(self, fail_prompt: bool = False, fail_generate_with_prompt: bool = False):
        self.fail_prompt = fail_prompt
        self.fail_generate_with_prompt = fail_generate_with_prompt
        self.prompts: list[dict] = []
        self.generations: list[dict] = []
        self.seeds: list[int] = []

    def create_voice_clone_prompt(self, ref_audio, ref_text=None, preprocess_prompt=True):
        if self.fail_prompt:
            raise RuntimeError("prompt falhou")
        self.prompts.append(
            {"ref_audio": ref_audio, "ref_text": ref_text, "preprocess_prompt": preprocess_prompt}
        )
        return omnivoice.VoiceClonePrompt(torch.zeros(8, 5, dtype=torch.long), ref_text, 0.1)

    def generate(self, **kwargs):
        if self.fail_generate_with_prompt and "voice_clone_prompt" in kwargs:
            raise RuntimeError("prompt rejeitado")
        self.generations.append(kwargs)
        self.seeds.append(torch.initial_seed())
        return [np.full(2400, 0.1, dtype=np.float64)]


def _synth(tmp_path, model=None):
    model = model or FakeModel()
    loads: list[int] = []

    def loader():
        loads.append(1)
        return model

    synth = OmniVoiceSynthesizer(prompt_dir=tmp_path / "prompts", model_loader=loader)
    return synth, model, loads


def _clone_voice(tmp_path):
    def on_run(command):
        write_wav(Path(command.args[-1]), np.zeros(2400, dtype=np.float32), 24000)

    library = VoiceLibrary(tmp_path / "voices")
    voice = library.save_clone(
        "Ana", tmp_path / "x.wav", RecordingRunner(on_run=on_run), None, "texto de referência"
    )
    return voice


@pytest.fixture
def clone(tmp_path):
    (tmp_path / "x.wav").write_bytes(b"x")
    return _clone_voice(tmp_path)


def test_model_loads_lazily_and_only_once(tmp_path):
    synth, _, loads = _synth(tmp_path)
    assert loads == [] and synth.engine_id == "omnivoice:k2-fsa/OmniVoice"
    synth.synthesize(VoiceRequest(text="Olá."))
    synth.synthesize(VoiceRequest(text="Tchau."))
    assert loads == [1]


def test_speech_is_float32_mono_at_model_rate(tmp_path):
    synth, _, _ = _synth(tmp_path)
    speech = synth.synthesize(VoiceRequest(text="Olá."))
    assert speech.samples.dtype == np.float32 and speech.samples.ndim == 1
    assert speech.sample_rate == 24000 and speech.duration == pytest.approx(0.1)


def test_clone_prompt_is_built_once_saved_and_reused(tmp_path, clone):
    synth, model, _ = _synth(tmp_path)
    synth.synthesize(VoiceRequest(text="Primeira.", voice=clone))
    synth.synthesize(VoiceRequest(text="Segunda.", voice=clone))

    assert len(model.prompts) == 1 and model.prompts[0]["ref_text"] == "texto de referência"
    assert all("voice_clone_prompt" in g and "instruct" not in g for g in model.generations)
    assert len(list((tmp_path / "prompts").glob("*.pt"))) == 1


def test_reference_is_passed_as_tensor_not_path(tmp_path, clone):
    synth, model, _ = _synth(tmp_path)
    synth.synthesize(VoiceRequest(text="Primeira.", voice=clone))
    waveform, rate = model.prompts[0]["ref_audio"]
    assert isinstance(waveform, torch.Tensor) and waveform.shape == (1, 2400) and rate == 24000


def test_failed_prompt_falls_back_to_inline_reference(tmp_path, clone):
    synth, model, _ = _synth(tmp_path, FakeModel(fail_prompt=True))
    speech = synth.synthesize(VoiceRequest(text="Primeira.", voice=clone))
    generation = model.generations[0]
    assert speech.duration > 0 and "voice_clone_prompt" not in generation
    assert generation["ref_text"] == "texto de referência" and isinstance(generation["ref_audio"], tuple)


def test_rejected_prompt_retries_with_inline_reference(tmp_path, clone):
    synth, model, _ = _synth(tmp_path, FakeModel(fail_generate_with_prompt=True))
    synth.synthesize(VoiceRequest(text="Primeira.", voice=clone))
    assert "ref_audio" in model.generations[0]


def test_clone_without_reference_text_is_a_clear_error(tmp_path, clone):
    synth, _, _ = _synth(tmp_path)
    no_text = clone.model_copy(update={"reference_text": None})
    with pytest.raises(ValueError, match="texto da referência"):
        synth.synthesize(VoiceRequest(text="Olá.", voice=no_text))


def test_designed_voice_is_anchored_once_and_keeps_the_speaker(tmp_path):
    synth, model, _ = _synth(tmp_path)
    design = VoiceLibrary(tmp_path / "voices").save_design("Grave", "male, low pitch")
    synth.synthesize(VoiceRequest(text="Primeira.", voice=design))
    synth.synthesize(VoiceRequest(text="Segunda.", voice=design))

    anchor, first, second = model.generations
    assert anchor["instruct"] == "male, low pitch" and anchor["text"] == ANCHOR_TEXTS["pt"]
    assert "instruct" not in first and "voice_clone_prompt" in first and "voice_clone_prompt" in second
    assert len(model.prompts) == 1 and model.prompts[0]["ref_text"] == ANCHOR_TEXTS["pt"]


def test_request_instruct_overrides_the_voice_instruct(tmp_path):
    synth, model, _ = _synth(tmp_path)
    design = VoiceLibrary(tmp_path / "voices").save_design("Grave", "male, low pitch")
    synth.synthesize(VoiceRequest(text="Olá.", voice=design, instruct="female"))
    assert model.generations[0]["instruct"] == "female"


def test_anchor_failure_still_speaks_with_instruct(tmp_path):
    synth, model, _ = _synth(tmp_path, FakeModel(fail_prompt=True))
    speech = synth.synthesize(VoiceRequest(text="Olá.", instruct="female"))
    assert speech.duration > 0 and model.generations[-1]["instruct"] == "female"


def test_prompt_saved_on_disk_is_reused_by_a_new_instance(tmp_path):
    first, model, _ = _synth(tmp_path)
    first.synthesize(VoiceRequest(text="Olá.", instruct="female"))
    assert len(model.prompts) == 1

    second, model2, _ = _synth(tmp_path)
    second.synthesize(VoiceRequest(text="Olá.", instruct="female"))
    assert model2.prompts == [] and "voice_clone_prompt" in model2.generations[0]


def test_seed_is_applied_right_before_generation_and_speed_only_when_changed(tmp_path):
    synth, model, _ = _synth(tmp_path)
    synth.synthesize(VoiceRequest(text="Olá.", seed=1234, speed=1.2, steps=8, language="pt-BR"))
    generation = model.generations[-1]
    assert model.seeds[-1] == 1234
    assert generation["speed"] == 1.2 and generation["num_step"] == 8 and generation["language"] == "pt"
    synth.synthesize(VoiceRequest(text="Olá."))
    assert "speed" not in model.generations[-1]


def test_default_steps_follow_voicestudio_16_with_draft_8(tmp_path):
    synth = OmniVoiceSynthesizer(device="cpu", prompt_dir=tmp_path, model_loader=FakeModel)
    request = VoiceRequest(text="Olá.")
    assert synth.effective_steps(request) == DEFAULT_STEPS == 16
    assert synth.effective_steps(VoiceRequest(text="Olá.", steps=DRAFT_STEPS)) == 8
    assert synth.cache_identity(request) != synth.cache_identity(VoiceRequest(text="Olá.", steps=8))
    gpu = OmniVoiceSynthesizer(device="cuda", prompt_dir=tmp_path, model_loader=FakeModel)
    assert gpu.effective_steps(request) == 16


def test_generation_pins_the_voicestudio_quality_parameters(tmp_path):
    synth = OmniVoiceSynthesizer(device="cpu", prompt_dir=tmp_path / "p", model_loader=FakeModel)
    synth.synthesize(VoiceRequest(text="Olá.", instruct="female"))
    for generation in synth._model.generations:
        assert generation["num_step"] == 16 and generation["guidance_scale"] == 2.0
        assert generation["denoise"] is True and generation["postprocess_output"] is True
    assert all(prompt["preprocess_prompt"] is True for prompt in synth._model.prompts)
