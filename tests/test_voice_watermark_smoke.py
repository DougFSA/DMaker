"""Fumaça da marca d'água com a AudioSeal real: baixa os pesos na primeira vez e roda na CPU.

Só roda com `DMAKER_VOICE_SMOKE=1` e com torch, audioseal e kokoro instalados (extra `voice`). Cobre o que
os testes com marcador falso não alcançam: a marca é inaudível, sobrevive ao AAC 192k, ao acabamento
broadcast da narração, à aceleração da dublagem e à mixagem com fundo, e a fala sem marca não é acusada.
"""

from __future__ import annotations

import importlib.util
import os

import numpy as np
import pytest

from dmaker.filtergraph.voice import OUTPUT_SAMPLE_RATE, encoder_args
from dmaker.media.ffmpeg import FFmpegCommand, SubprocessRunner
from dmaker.media.wavio import write_wav
from dmaker.pipeline.voices import verify_watermark
from dmaker.voice.library import VoiceLibrary
from dmaker.voice.postprocess import finish_speech
from dmaker.voice.synth import VoiceRequest
from dmaker.voice.watermark import AudioSealWatermarker

from .conftest import requires_ffmpeg

pytestmark = [
    pytest.mark.skipif(os.environ.get("DMAKER_VOICE_SMOKE") != "1", reason="defina DMAKER_VOICE_SMOKE=1"),
    pytest.mark.skipif(
        any(importlib.util.find_spec(name) is None for name in ("torch", "audioseal", "kokoro_onnx")),
        reason="torch/audioseal/kokoro não instalados (pip install -e .[voice])",
    ),
    requires_ffmpeg,
]

TEXT = "Hoje vamos falar sobre como editar vídeos curtos de forma rápida e simples, sem complicação nenhuma."
MAX_RELATIVE_ENERGY_DB = -27.0  # a marca (ganho 0.7, cerca de -28 dB) tem de ficar abaixo disso da fala


def _relative_energy_db(plain: np.ndarray, marked: np.ndarray) -> float:
    residue = marked - plain
    return float(10 * np.log10((residue**2).sum() / (plain**2).sum()))


def test_mark_is_inaudible_survives_aac_and_is_absent_from_plain_speech(tmp_path):
    from dmaker.voice.kokoro import KokoroSynthesizer

    speech = KokoroSynthesizer().synthesize(VoiceRequest(text=TEXT, voice=VoiceLibrary(tmp_path).get("dora")))
    plain = finish_speech(speech.samples, speech.sample_rate)
    marker = AudioSealWatermarker()
    marked = marker.embed(plain, speech.sample_rate)

    assert len(marked) == len(plain)
    assert _relative_energy_db(plain, marked) < MAX_RELATIVE_ENERGY_DB

    runner = SubprocessRunner(quiet=True)
    for label, samples, expected in (("marcada", marked, True), ("sem-marca", plain, False)):
        wav = write_wav(tmp_path / f"{label}.wav", samples, speech.sample_rate)
        m4a = tmp_path / f"{label}.m4a"
        runner.run(
            FFmpegCommand(["-i", str(wav), "-ar", str(OUTPUT_SAMPLE_RATE), *encoder_args(m4a), str(m4a)])
        )
        result = verify_watermark(m4a, runner=runner, watermarker=marker)
        assert result.detected is expected, f"{label}: {result}"


SHORT_TEXT = "Teste da develop."  # a frase curta que reprovou a primeira entrega
LONG_TEXT = "Para editar vídeos curtos de forma rápida, basta escrever o que você quer e o editor monta tudo sozinho para você."
# ruído rosa cerca de 31 dB abaixo da fala (RMS -54 dBFS contra -23 dBFS): um fundo discreto de dublagem; com
# o fundo a 24 dB a detecção cai para 0.3 a 0.4 e a 18 dB, para 0.2 a 0.3 (ver o relatório do DMK-7)
NOISE_BED = ["-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.01:sample_rate=48000:duration=14"]


def _narration(tmp_path):
    from dmaker.pipeline.narration import NarrationService
    from dmaker.voice.kokoro import KokoroSynthesizer

    runner = SubprocessRunner(quiet=True)
    marker = AudioSealWatermarker()
    service = NarrationService(KokoroSynthesizer(), runner, tmp_path / "cache", watermarker=marker)
    return service, runner, marker


def _voice(tmp_path):
    return VoiceLibrary(tmp_path).get("dora")


def test_narration_with_the_broadcast_finish_keeps_the_mark_through_the_m4a(tmp_path):
    service, runner, marker = _narration(tmp_path)
    out = tmp_path / "narracao.m4a"

    service.render(SHORT_TEXT, out, _voice(tmp_path), language="pt", master=True)

    assert verify_watermark(out, runner=runner, watermarker=marker).detected


def test_dubbing_speed_up_before_the_mark_survives_the_mix_with_a_background_bed(tmp_path):
    from dmaker.filtergraph.dub import DubClip, dub_mix_command
    from dmaker.filtergraph.voice import SpeechFinish

    service, runner, marker = _narration(tmp_path)
    request = VoiceRequest(text=LONG_TEXT, language="pt", voice=_voice(tmp_path))
    for tempo in (1.15, 0.9):
        speech, seconds = service.speak(request, SpeechFinish(tempo=tempo))
        bed = tmp_path / f"fundo-{tempo}.wav"
        runner.run(FFmpegCommand([*NOISE_BED, "-c:a", "pcm_s16le", str(bed)]))
        out = tmp_path / f"dublagem-{tempo}.m4a"
        mix = dub_mix_command(
            tmp_path / "origem.mp4",
            bed,
            [DubClip(speech, 0.5)],
            out,
            tmp_path / "g.txt",
            3.0,
            has_video=False,
        )
        (tmp_path / "g.txt").write_text(mix.graph, encoding="utf-8")
        runner.run(mix.command)
        assert verify_watermark(out, runner=runner, watermarker=marker).detected, f"tempo {tempo}"


def test_speech_without_the_mark_is_not_accused_after_the_same_chain(tmp_path):
    from dmaker.pipeline.narration import NarrationService
    from dmaker.voice.kokoro import KokoroSynthesizer
    from dmaker.voice.watermark import NullWatermarker

    runner = SubprocessRunner(quiet=True)
    service = NarrationService(KokoroSynthesizer(), runner, tmp_path / "cache", watermarker=NullWatermarker())
    out = tmp_path / "sem-marca.m4a"

    service.render(SHORT_TEXT, out, _voice(tmp_path), language="pt", master=True)

    assert not verify_watermark(out, runner=runner, watermarker=AudioSealWatermarker()).detected


# ---------- veredito em três níveis e etiqueta de procedência (DMK-7, ajuste 2) ----------


def _lavfi(tmp_path, name: str, *sources: str, graph: str | None = None):
    """Gera um wav de 30 s com o ffmpeg a partir de fontes sintéticas (tom, acordes, ruído)."""
    out = tmp_path / name
    args = []
    for source in sources:
        args += ["-f", "lavfi", "-i", source]
    if graph:
        args += ["-filter_complex", graph]
    SubprocessRunner(quiet=True).run(FFmpegCommand([*args, "-c:a", "pcm_s16le", str(out)]))
    return out


def test_a_pure_tone_and_synthetic_chords_are_never_found(tmp_path):
    """A fração de quadros é alta em tons e acordes (medido: 0.90 e 0.27); só a assinatura de 16 bits separa."""
    tone = _lavfi(tmp_path, "tom.wav", "sine=frequency=440:duration=30:sample_rate=48000")
    chords = _lavfi(
        tmp_path,
        "acordes.wav",
        "sine=frequency=220:duration=30:sample_rate=48000",
        "sine=frequency=277:duration=30:sample_rate=48000",
        "sine=frequency=330:duration=30:sample_rate=48000",
        "anoisesrc=color=pink:amplitude=0.02:duration=30:sample_rate=48000",
        graph="amix=inputs=4:normalize=0,volume=0.8",
    )
    noise = _lavfi(tmp_path, "rosa.wav", "anoisesrc=color=pink:amplitude=0.3:duration=30:sample_rate=48000")
    marker = AudioSealWatermarker()

    verdicts = {
        path.stem: verify_watermark(path, watermarker=marker, runner=SubprocessRunner(quiet=True))
        for path in (tone, chords, noise)
    }

    assert all(result.verdict != "found" for result in verdicts.values()), verdicts
    assert verdicts["rosa"].verdict == "absent"


def test_a_narration_without_its_label_is_found_by_the_audio_signature(tmp_path):
    service, runner, marker = _narration(tmp_path)
    labeled = tmp_path / "narracao.m4a"
    service.render(SHORT_TEXT, labeled, _voice(tmp_path), language="pt", master=True)
    stripped = tmp_path / "sem-etiqueta.m4a"
    runner.run(FFmpegCommand(["-i", str(labeled), "-map_metadata", "-1", "-c", "copy", str(stripped)]))

    with_label = verify_watermark(labeled, runner=runner, watermarker=marker)
    without_label = verify_watermark(stripped, runner=runner, watermarker=marker)

    assert with_label.origin == "label" and with_label.verdict == "found"
    assert without_label.origin == "audio" and without_label.verdict == "found"
    assert without_label.matched_bits >= 15


def test_the_alignment_search_recovers_a_marked_speech_that_lost_the_detector_grid(tmp_path):
    from dmaker.media.wavio import read_wav

    service, runner, marker = _narration(tmp_path)
    path, _ = service.speak(VoiceRequest(text=SHORT_TEXT, language="pt", voice=_voice(tmp_path)))
    samples, rate = read_wav(path)
    on_grid = marker.detect(samples, rate)
    shifted = marker.detect(samples[7:], rate)  # 7 amostras a 24 kHz fora da grade de 20 ms

    assert on_grid.verdict == "found"
    assert shifted.verdict == "found", shifted
