"""Os plugins LV2 e LADSPA de verdade, pelo ffmpeg de verdade, com um plugin de teste próprio (um eco; o código está em
`tests/plugin_fixture`). Pula sem ele: aponte `DMAKER_TEST_PLUGINS` para a pasta com `lv2/` e `ladspa/` compilados e, para o LV2,
`DMAKER_FFMPEG_LV2_DIR` para um ffmpeg com o filtro `lv2`; o LADSPA usa o ffmpeg principal (o build completo) ou o de
`DMAKER_FFMPEG_LADSPA_DIR`.

O critério do card: o plugin aplicado pelo DMaker dá o MESMO arquivo que o ffmpeg direto com os mesmos parâmetros, e mexer num
parâmetro muda o som de forma que se mede (a posição do eco, a razão entre os ecos, o tamanho do primeiro eco)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

from dmaker.domain.audio_effects import parse_effect
from dmaker.domain.spec import Project
from dmaker.media.ffmpeg import SubprocessRunner, ffmpeg_path
from dmaker.media.plugin_host import host_ffmpeg
from dmaker.media.plugin_scan import PluginRoot
from dmaker.media.wavio import read_wav_float
from dmaker.pipeline import RenderOptions, RenderPipeline
from dmaker.pipeline import plugins as plugins_module
from dmaker.pipeline.audio_effects import AudioItem, EffectProcessor
from dmaker.pipeline.plugins import PluginService

from .conftest import requires_ffmpeg

PLUGIN_DIR = os.environ.get("DMAKER_TEST_PLUGINS")
pytestmark = [
    requires_ffmpeg,
    pytest.mark.skipif(
        not PLUGIN_DIR, reason="DMAKER_TEST_PLUGINS não aponta para o plugin de teste compilado"
    ),
]

RATE = 48000
URI = "urn:dmaker:test:echo"
LADSPA_REF = "dm_echo.dll#dm_echo"
CONTROL_NAMES = {"lv2": ("delay_ms", "feedback", "mix"), "ladspa": ("c0", "c1", "c2")}
REFERENCE = {"lv2": URI, "ladspa": LADSPA_REF}


@pytest.fixture(scope="module")
def service() -> PluginService:
    root = Path(PLUGIN_DIR or ".")
    return PluginService(
        roots=lambda: [PluginRoot("lv2", root / "lv2"), PluginRoot("ladspa", root / "ladspa")]
    )


@pytest.fixture(params=["lv2", "ladspa"])
def format_name(request, service) -> str:
    if host_ffmpeg(request.param) is None:
        pytest.skip(f"nenhum ffmpeg com o filtro {request.param} (DMAKER_FFMPEG_{request.param.upper()}_DIR)")
    if service.find(REFERENCE[request.param]) is None:
        pytest.skip(f"o plugin {request.param} de teste não está em {PLUGIN_DIR}")
    return request.param


@pytest.fixture
def processor(tmp_path, service) -> EffectProcessor:
    return EffectProcessor(SubprocessRunner(quiet=True), tmp_path / "fx", plugins=service)


def write_float_wav(path: Path, samples: np.ndarray) -> Path:
    raw = path.with_suffix(".f32")
    np.asarray(samples, dtype="<f4").tofile(raw)
    subprocess.run(
        [
            str(ffmpeg_path()),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "f32le",
            "-ar",
            str(RATE),
            "-ac",
        ]
        + [str(samples.shape[1]), "-i", str(raw), "-c:a", "pcm_f32le", str(path)],
        check=True,
    )
    return path


def clicks(tmp_path: Path, name: str, *at: float, seconds: float = 3.0) -> Path:
    """Estéreo: um clique de 0,8 na esquerda e de 0,4 na direita em cada instante."""
    samples = np.zeros((round(seconds * RATE), 2), dtype="<f4")
    for instant in at:
        samples[round(instant * RATE)] = (0.8, 0.4)
    return write_float_wav(tmp_path / f"{name}.wav", samples)


def effect(format_name: str, delay: float = 300.0, feedback: float = 0.5, mix: float = 0.8, **interval):
    names = CONTROL_NAMES[format_name]
    params = dict(zip(names, (delay, feedback, mix), strict=True))
    return parse_effect(
        {
            "type": "plugin",
            "format": format_name,
            "plugin": REFERENCE[format_name],
            "params": params,
            **interval,
        }
    )


def apply(processor, source: Path, seconds: float, *chain) -> np.ndarray:
    done = processor.process(AudioItem(source, seconds, tuple(chain)))
    assert done is not None
    samples, rate = read_wav_float(done.path)
    assert rate == RATE
    return samples


def peaks(channel: np.ndarray, floor: float = 0.02) -> list[tuple[float, float]]:
    found: list[list[float]] = []
    for position in np.flatnonzero(np.abs(channel) > floor):
        if not found or position - found[-1][0] > 50:
            found.append([position, abs(float(channel[position]))])
        elif abs(channel[position]) > found[-1][1]:
            found[-1] = [position, abs(float(channel[position]))]
    return [(round(position / RATE, 4), round(level, 4)) for position, level in found]


def test_the_plugin_applied_by_dmaker_is_the_same_file_the_ffmpeg_gives_directly(
    format_name, processor, service, tmp_path
):
    source = clicks(tmp_path, "cliques", 0.1)
    mine = apply(processor, source, 3.0, effect(format_name))
    resolved = service.resolve(format_name, REFERENCE[format_name])
    if format_name == "ladspa":  # estéreo: o mesmo grafo, escrito à mão
        graph = (
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            "ladspa=f=./dm_echo.dll:p=dm_echo:c=c0=300|c1=0.5|c2=0.8"
        )
        direct = tmp_path / "direto.wav"
        subprocess.run(
            [
                str(resolved.ffmpeg),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-af",
                graph,
            ]
            + ["-c:a", "pcm_f32le", str(direct)],
            check=True,
            cwd=resolved.cwd,
        )
        reference, _ = read_wav_float(direct)
        length = min(len(reference), len(mine))
        assert np.abs(mine[:length] - reference[:length]).max() == 0.0
        return
    # LV2: o plugin é mono, o ffmpeg direto roda um canal de cada vez e o DMaker junta os dois
    for channel in (0, 1):
        mono = tmp_path / f"mono{channel}.wav"
        subprocess.run(
            [str(ffmpeg_path()), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-af"]
            + [f"pan=mono|c0=c{channel}", "-c:a", "pcm_f32le", str(mono)],
            check=True,
        )
        direct = tmp_path / f"direto{channel}.wav"
        subprocess.run(
            [str(resolved.ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(mono), "-af"]
            + [f"lv2=p='{URI.replace(':', chr(92) + ':')}':c='delay_ms=300|feedback=0.5|mix=0.8'"]
            + ["-c:a", "pcm_f32le", str(direct)],
            check=True,
            env={**os.environ, **resolved.env},
        )
        reference, _ = read_wav_float(direct)
        reference = reference.reshape(len(reference), -1)[:, 0]
        length = min(len(reference), len(mine))
        assert np.abs(mine[:length, channel] - reference[:length]).max() == 0.0


def test_the_echo_has_the_right_delay_and_the_stereo_levels_are_kept(format_name, processor, tmp_path):
    result = apply(processor, clicks(tmp_path, "c", 0.1), 3.0, effect(format_name, delay=300.0))
    left = peaks(result[:, 0])
    assert [instant for instant, _ in left[:4]] == [0.1, 0.4, 0.7, 1.0]
    assert [level for _, level in left[:2]] == [0.8, 0.64]  # o seco passa e o primeiro eco é seco x mistura
    assert (
        peaks(result[:, 1])[0][1] == 0.4
    )  # o canal direito tem o nível dele: um plugin mono rodou uma vez por canal


def test_moving_each_control_changes_the_sound_by_what_that_control_does(format_name, processor, tmp_path):
    source = clicks(tmp_path, "c", 0.1)
    for delay in (100.0, 300.0, 600.0):
        found = peaks(apply(processor, source, 3.0, effect(format_name, delay=delay))[:, 0])
        assert found[1][0] == pytest.approx(0.1 + delay / 1000, abs=0.0005)
    for feedback in (0.2, 0.5, 0.8):
        found = peaks(apply(processor, source, 3.0, effect(format_name, feedback=feedback))[:, 0])
        assert found[2][1] / found[1][1] == pytest.approx(feedback, abs=0.001)
    for mix in (0.0, 0.5, 1.0):
        found = peaks(apply(processor, source, 3.0, effect(format_name, mix=mix))[:, 0])
        first_echo = found[1][1] if len(found) > 1 else 0.0
        assert first_echo == pytest.approx(0.8 * mix, abs=0.001)


def test_a_value_out_of_range_renders_and_gives_the_same_file_as_the_limited_value(
    format_name, service, tmp_path
):
    """O ffmpeg recusa o valor fora da faixa; o render usa o limite mais próximo e dá o mesmo som do valor já limitado."""
    source = clicks(tmp_path, "c", 0.1)
    names = CONTROL_NAMES[format_name]
    outside = effect(format_name, delay=5000.0, feedback=2.0, mix=0.8)  # tetos: 1000 ms e 0,95
    limited = effect(format_name, delay=1000.0, feedback=0.95, mix=0.8)
    warnings: list[str] = []
    fitting = EffectProcessor(
        SubprocessRunner(quiet=True), tmp_path / "fx-fora", plugins=service, on_warning=warnings.append
    )
    exact = EffectProcessor(SubprocessRunner(quiet=True), tmp_path / "fx-limite", plugins=service)
    result = apply(fitting, source, 3.0, outside)
    assert np.array_equal(result, apply(exact, source, 3.0, limited))
    assert len(warnings) == 2 and f"({names[0]})" in warnings[0] and "o render usa 1000" in warnings[0]
    assert fitting.key(AudioItem(source, 3.0, (outside,))) == exact.key(AudioItem(source, 3.0, (limited,)))


def test_a_control_the_plugin_does_not_have_is_ignored_and_the_render_does_not_fail(
    format_name, service, tmp_path
):
    source = clicks(tmp_path, "c", 0.1)
    warnings: list[str] = []
    fitting = EffectProcessor(
        SubprocessRunner(quiet=True), tmp_path / "fx-extra", plugins=service, on_warning=warnings.append
    )
    exact = EffectProcessor(SubprocessRunner(quiet=True), tmp_path / "fx-certo", plugins=service)
    extra = effect(format_name)
    extra = extra.model_copy(update={"params": {**extra.params, "c9": 1.0, "inexistente": 1.0}})
    assert np.array_equal(apply(fitting, source, 3.0, extra), apply(exact, source, 3.0, effect(format_name)))
    assert len(warnings) == 2 and all("o render ignora esse valor" in warning for warning in warnings)


def test_in_an_interval_the_sound_outside_it_is_untouched(format_name, processor, tmp_path):
    source = clicks(tmp_path, "tres", 0.5, 1.2, 2.6)
    original, _ = read_wav_float(source)
    result = apply(processor, source, 3.0, effect(format_name, delay=200.0, start=1.0, end=2.0))
    assert np.abs(result[: round(0.99 * RATE)] - original[: round(0.99 * RATE)]).max() == 0.0
    assert np.abs(result[round(2.01 * RATE) :] - original[round(2.01 * RATE) :]).max() == 0.0
    assert [instant for instant, _ in peaks(result[:, 0])] == [0.5, 1.2, 1.4, 1.6, 1.8, 2.6]


def test_a_render_of_a_clip_with_the_plugin_puts_the_echo_in_the_video_audio_and_a_missing_plugin_changes_nothing(
    format_name, service, synthetic_media, tmp_path, monkeypatch
):
    monkeypatch.setattr(plugins_module, "_default", service)

    def render(name: str, chain: list[dict]) -> tuple[np.ndarray, list[str]]:
        project = Project.model_validate(
            {
                "name": name,
                "output": {"preset": "instagram/reels", "quality": "medium"},
                "timeline": [
                    {"type": "clip", "src": str(synthetic_media["clip_a"]), "end": 2.0, "effects": chain}
                ],
                "audio": {"normalize": "off"},
            }
        )
        project.base_dir = tmp_path
        out = tmp_path / f"{name}.mp4"
        result = RenderPipeline(project, RenderOptions(out=out, quiet=True)).run()
        raw = tmp_path / f"{name}.f32"
        subprocess.run(
            [
                str(ffmpeg_path()),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(out),
                "-vn",
                "-f",
                "f32le",
            ]
            + ["-ac", "2", "-ar", str(RATE), str(raw)],
            check=True,
        )
        return np.fromfile(raw, dtype="<f4").reshape(-1, 2), result.warnings

    plain, _ = render("sem", [])
    with_plugin, _ = render("com", [effect(format_name).model_dump(mode="json")])
    absent = {"lv2": "urn:acme:nao-instalado", "ladspa": "nao-instalado.dll#nada"}[format_name]
    missing, warnings = render(
        "ausente", [{"type": "plugin", "format": format_name, "plugin": absent, "params": {}}]
    )
    length = min(len(plain), len(with_plugin), len(missing))
    assert np.abs(with_plugin[:length] - plain[:length]).max() > 0.05  # o eco entrou no som do vídeo
    assert (
        np.abs(missing[:length] - plain[:length]).max() == 0.0
    )  # plugin ausente: o render segue igual ao sem o efeito
    assert any(absent in warning and "pulado" in warning for warning in warnings)
