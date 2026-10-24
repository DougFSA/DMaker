"""Registro dos modelos (`domain.models`): contas puras e o contrato com os motores que baixam de verdade."""

from __future__ import annotations

import pytest

from dmaker import config
from dmaker.domain.models import (
    INSTALLED_FRACTION,
    REGISTRY,
    ModelSpec,
    classify,
    exclusive_paths,
    find_model,
    format_size,
    is_safe_relative,
)
from dmaker.pipeline.model_fetchers import resolve_fetcher

# ---------- contas puras ----------


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (0, "0 B"),
        (512, "512 B"),
        (2048, "2 KB"),
        (84_025_501, "80,1 MB"),
        (3_267_869_931, "3,04 GB"),
        (-5, "0 B"),
    ],
)
def test_format_size_uses_windows_units_with_a_decimal_comma(size, expected):
    assert format_size(size) == expected


def test_classify_separates_installed_partial_and_absent():
    assert classify(False, 0, 100, False) == "absent"
    assert classify(True, 100, 100, False) == "installed"
    assert classify(True, int(100 * INSTALLED_FRACTION), 100, False) == "installed"
    assert classify(True, int(100 * INSTALLED_FRACTION) - 1, 100, False) == "partial"
    assert classify(True, 100, 100, True) == "partial"  # sobrou arquivo de download: não está inteiro


@pytest.mark.parametrize(
    "path", ["omnivoice", "kokoro/kokoro-v1.0.onnx", "models--Systran--faster-whisper-small"]
)
def test_safe_relative_paths_are_accepted(path):
    assert is_safe_relative(path)


@pytest.mark.parametrize(
    "path", ["", "..", "../fora", "a/../../b", "/etc", "C:/Windows", "a\\b", "a/./b", "D:segredo"]
)
def test_unsafe_relative_paths_are_refused(path):
    assert not is_safe_relative(path)


def test_a_spec_with_an_unsafe_path_cannot_be_created():
    with pytest.raises(ValueError, match="inseguro"):
        ModelSpec("x", "X", "p", "e", "MIT", ("../fora",), 1, (), "m:f")
    with pytest.raises(ValueError, match="pelo menos um caminho"):
        ModelSpec("x", "X", "p", "e", "MIT", (), 1, (), "m:f")


# ---------- o registro ----------


def test_registry_ids_are_unique_and_every_entry_is_filled_in():
    ids = [spec.id for spec in REGISTRY]
    assert len(ids) == len(set(ids))
    for spec in REGISTRY:
        assert spec.name and spec.purpose and spec.license and spec.required_by, spec.id
        assert spec.expected_size > 0, spec.id
        assert "—" not in spec.purpose + spec.name + "".join(
            spec.required_by
        )  # sem travessão em texto de tela


def test_registry_covers_the_models_this_code_downloads():
    ids = {spec.id for spec in REGISTRY}
    assert {"omnivoice", "kokoro-fp32", "kokoro-int8", "demucs-htdemucs", "whisper-small"} <= ids
    assert {"whisper-tiny", "whisper-base", "whisper-medium", "whisper-large-v3"} <= ids
    assert {"rvm-resnet50", "rvm-mobilenetv3"} <= ids
    assert find_model("omnivoice") is REGISTRY[0] and find_model("nao-existe") is None


def test_every_fetch_path_resolves_to_a_function():
    for spec in REGISTRY:
        assert callable(resolve_fetcher(spec.fetch)), spec.id
    with pytest.raises(LookupError):
        resolve_fetcher("dmaker.pipeline.model_fetchers:nao_existe")


def test_the_kokoro_variants_share_the_voices_file_but_not_the_model():
    fp32, int8 = find_model("kokoro-fp32"), find_model("kokoro-int8")
    assert set(fp32.paths) & set(int8.paths) == {"kokoro/voices-v1.0.bin"}
    assert exclusive_paths(fp32) == ("kokoro/kokoro-v1.0.onnx",)
    assert exclusive_paths(int8) == ("kokoro/kokoro-v1.0.int8.onnx",)
    assert exclusive_paths(find_model("omnivoice")) == ("omnivoice",)


# ---------- contrato com os motores (arquivos distantes que precisam concordar) ----------


def test_registry_paths_match_the_folders_the_engines_really_use():
    """Se um motor mudar de pasta, o registro passa a chamar o modelo de ausente e a pasta de sobra."""
    from dmaker.media import matting
    from dmaker.media.separation import DemucsSeparator
    from dmaker.voice.kokoro import MODEL_FILES, VOICES_FILE, KokoroSynthesizer
    from dmaker.voice.synth import OmniVoiceSynthesizer

    models = config.MODELS_DIR
    assert find_model("omnivoice").paths == (
        OmniVoiceSynthesizer().models_dir.relative_to(models).as_posix(),
    )
    assert find_model("demucs-htdemucs").paths == (
        DemucsSeparator().models_dir.relative_to(models).as_posix(),
    )
    for variant in ("fp32", "int8"):
        folder = KokoroSynthesizer(variant).models_dir.relative_to(models).as_posix()
        spec = find_model(f"kokoro-{variant}")
        assert spec.paths == (f"{folder}/{MODEL_FILES[variant].name}", f"{folder}/{VOICES_FILE.name}")
        assert spec.expected_size == MODEL_FILES[variant].size + VOICES_FILE.size
    for name in matting.MODEL_FILES:
        spec = find_model(f"rvm-{name}")
        assert spec.paths == (matting.model_path(name, models).relative_to(models).as_posix(),)


def test_whisper_entries_match_the_cache_folder_faster_whisper_creates():
    _MODELS = pytest.importorskip("faster_whisper.utils")._MODELS

    for spec in REGISTRY:
        if spec.engine == "faster-whisper":
            repo = _MODELS[spec.variant]  # ex.: Systran/faster-whisper-small
            assert spec.paths == (f"models--{repo.replace('/', '--')}",)
