"""Render e exportação de áudio com o ffmpeg de verdade: sinais conhecidos, medidas numéricas.

Cobre os critérios do chamado: uma narração sozinha sai em MP3 e WAV a -16 LUFS sem nenhum quadro de vídeo; as
etiquetas aparecem no ffprobe; um áudio de 10 minutos com 5 regiões sai em 5 arquivos com a duração certa; as trilhas
somadas reproduzem a mixagem; um PCM bruto importa e soa certo.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np
import pytest

from dmaker import config
from dmaker.domain.audio_export import ExportRequest
from dmaker.domain.spec import Project
from dmaker.media.ffmpeg import SubprocessRunner
from dmaker.media.wavio import read_wav_channels
from dmaker.pipeline import RenderOptions, create_renderer
from dmaker.pipeline.audio_export import AudioExporter
from dmaker.pipeline.audio_import import RawImportError, import_raw_audio
from dmaker.pipeline.audio_render import AudioRenderPipeline

pytestmark = pytest.mark.skipif(config.find_tool("ffmpeg") is None, reason="precisa do ffmpeg")


def ffmpeg(*args: str) -> None:
    subprocess.run([str(config.find_tool("ffmpeg")), "-y", "-loglevel", "error", *args], check=True)


def ffprobe(path: Path, entries: str) -> dict:
    run = subprocess.run(
        [str(config.find_tool("ffprobe")), "-v", "error", "-show_entries", entries, "-of", "json", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(run.stdout)


def tags_of(path: Path) -> dict[str, str]:
    """As etiquetas do arquivo, do contêiner ou do fluxo (o OGG e o Opus as guardam no fluxo), em minúsculas."""
    info = ffprobe(path, "format_tags:stream_tags")
    found = dict(info.get("format", {}).get("tags", {}))
    for stream in info.get("streams", []):
        found.update(stream.get("tags", {}))
    return {key.lower(): value for key, value in found.items()}


def duration(path: Path) -> float:
    return float(ffprobe(path, "format=duration")["format"]["duration"])


def loudness(path: Path) -> float:
    """O volume integrado em LUFS, medido pelo `ebur128` do ffmpeg."""
    run = subprocess.run(
        [
            str(config.find_tool("ffmpeg")),
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            "ebur128",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", run.stderr)[-1])


def tone(
    path: Path, seconds: float, hz: float = 220, *, rate: int = 48000, slow_tremolo: bool = True
) -> Path:
    """Um tom com um tremolo lento: o volume varia como o de uma fala (um tom constante mede LRA 0, e o loudnorm
    trata isso como medição ausente)."""
    modulation = ",tremolo=f=0.15:d=0.6" if slow_tremolo else ""
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"sine=f={hz}:d={seconds}:r={rate}",
        "-af",
        f"aformat=channel_layouts=stereo{modulation}",
        str(path),
    )
    return path


def make_project(tmp_path: Path, **spec) -> Project:
    base = {"name": "ep", "timeline": [], "audio": {"target_lufs": -16}, **spec}
    project = Project.model_validate(base)
    project.base_dir = tmp_path
    return project


def pipeline(project: Project, tmp_path: Path, **options) -> AudioRenderPipeline:
    return AudioRenderPipeline(
        project,
        RenderOptions(quiet=True, **options),
        runner=SubprocessRunner(quiet=True),
        output_dir=tmp_path / "saida",
    )


def test_a_narration_alone_leaves_as_mp3_and_wav_at_minus_16_lufs_with_no_video(tmp_path):
    voice = tone(tmp_path / "voz.wav", 20)
    results = {}
    for preset, fmt, name in (
        ("audio/mp3", {"bitrate_k": 192}, "ep.mp3"),
        ("audio/wav", {"bit_depth": 24}, "ep.wav"),
    ):
        project = make_project(
            tmp_path,
            output={"preset": preset, "audio_format": fmt},
            audio={"voiceover": [{"src": "voz.wav"}], "target_lufs": -16},
        )
        out = tmp_path / name
        create_renderer(
            project, RenderOptions(quiet=True, out=out), runner=SubprocessRunner(quiet=True)
        ).run()
        info = ffprobe(out, "stream=codec_type,codec_name,bit_rate,bits_per_sample,sample_rate,channels")
        results[name] = (info["streams"], loudness(out), duration(out))
    mp3_streams, mp3_lufs, mp3_seconds = results["ep.mp3"]
    wav_streams, wav_lufs, wav_seconds = results["ep.wav"]
    assert [s["codec_type"] for s in mp3_streams + wav_streams] == [
        "audio",
        "audio",
    ]  # nenhum quadro de vídeo
    assert mp3_streams[0]["codec_name"] == "mp3" and int(mp3_streams[0]["bit_rate"]) == 192_000
    assert wav_streams[0]["codec_name"] == "pcm_s24le" and wav_streams[0]["bits_per_sample"] == 24
    assert wav_lufs == pytest.approx(-16, abs=0.3)
    assert mp3_lufs == pytest.approx(-16, abs=0.5)  # a codificação com perda mexe um pouco no volume medido
    assert mp3_seconds == pytest.approx(20, abs=0.1) and wav_seconds == pytest.approx(20, abs=0.01)
    assert voice.exists()


def test_the_loudness_targets_of_the_card_are_reached(tmp_path):
    tone(tmp_path / "voz.wav", 20)
    for target, lufs in (("redes", -14), ("podcast", -16), ("broadcast", -23)):
        project = make_project(
            tmp_path, output={"preset": "audio/wav"}, audio={"voiceover": [{"src": "voz.wav"}]}
        )
        out = tmp_path / f"{target}.wav"
        from dmaker.pipeline.audio_service import build_pipeline

        build_pipeline(
            project,
            None,
            loudness=target,
            options=RenderOptions(quiet=True, out=out),
            runner=SubprocessRunner(quiet=True),
        ).run()
        assert loudness(out) == pytest.approx(lufs, abs=0.3), target


def test_the_tags_show_in_the_ffprobe_of_the_mp3_and_the_flac(tmp_path):
    tone(tmp_path / "voz.wav", 6)
    meta = {
        "artist": "Fulano de Tal",
        "title": "Episódio 12",
        "album": "Temporada 2",
        "track": "12",
        "year": "2026",
        "genre": "Podcast",
        "comment": "Teste",
    }
    for preset, name in (
        ("audio/mp3", "ep.mp3"),
        ("audio/flac", "ep.flac"),
        ("audio/ogg", "ep.ogg"),
        ("audio/m4a", "ep.m4a"),
    ):
        project = make_project(
            tmp_path,
            output={"preset": preset, "metadata": meta},
            audio={"voiceover": [{"src": "voz.wav"}], "target_lufs": -16},
        )
        out = tmp_path / name
        create_renderer(
            project, RenderOptions(quiet=True, out=out), runner=SubprocessRunner(quiet=True)
        ).run()
        tags = tags_of(out)
        assert {k: tags[k] for k in ("artist", "title", "album", "track", "genre", "comment")} == {
            "artist": "Fulano de Tal",
            "title": "Episódio 12",
            "album": "Temporada 2",
            "track": "12",
            "genre": "Podcast",
            "comment": "Teste",
        }, preset
        assert tags["date"] == "2026", preset
    assert (tmp_path / "ep.mp3").read_bytes()[:5] == b"ID3\x03\x00"  # ID3v2.3


def test_a_ten_minute_audio_with_five_regions_leaves_in_five_files_with_the_right_durations(tmp_path):
    # 10 minutos em 8 kHz mono: o suficiente para provar a conta, sem encher a pasta temporária
    ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "sine=f=180:d=600:r=8000",
        "-af",
        "tremolo=f=0.1:d=0.5",
        str(tmp_path / "longo.wav"),
    )
    regions = [
        (0, 95.25, "Abertura"),
        (95.25, 210.5, "Entrevista: parte 1"),
        (210.5, 330, ""),
        (330, 480.125, "Entrevista: parte 1"),
        (480.125, 600, "Fim"),
    ]
    project = make_project(
        tmp_path,
        output={"preset": "audio/flac"},
        audio={"voiceover": [{"src": "longo.wav"}], "target_lufs": -16},
        markers=[{"start": a, "end": b, "text": t} for a, b, t in regions],
    )
    result = AudioExporter(pipeline(project, tmp_path)).run(ExportRequest(mode="regions"))
    names = [f.path.name for f in result.files]
    assert names == [
        "Abertura.flac",
        "Entrevista parte 1-02.flac",
        "regiao-03.flac",
        "Entrevista parte 1-04.flac",
        "Fim.flac",
    ]
    for (start, end, _), exported in zip(regions, result.files, strict=True):
        assert exported.path.exists()
        assert abs(duration(exported.path) - (end - start)) <= 0.010, exported.path.name
    # cada região é uma entrega própria: chega ao alvo de loudness sozinha
    assert all(abs(loudness(f.path) - -16) <= 0.7 for f in result.files)
    # e a referência de ponto flutuante não fica no disco
    assert not list(Path(result.files[0].path).parent.glob("*.wav"))


def test_the_selection_exports_just_the_interval_and_accepts_a_marker(tmp_path):
    tone(tmp_path / "voz.wav", 30)
    project = make_project(
        tmp_path,
        output={"preset": "audio/wav"},
        audio={"voiceover": [{"src": "voz.wav"}], "target_lufs": -16},
        markers=[{"start": 10, "end": 14.5, "text": "Trecho"}],
    )
    result = AudioExporter(pipeline(project, tmp_path)).run(
        ExportRequest(mode="selection", start="marker:Trecho", end="marker:Trecho")
    )
    assert [f.path.name for f in result.files] == ["ep__audio-wav__selecao.wav"]
    assert duration(result.files[0].path) == pytest.approx(4.5, abs=0.01)


def test_the_stems_add_up_to_the_mix(tmp_path):
    tone(tmp_path / "voz.wav", 40, 220)
    tone(tmp_path / "musica.wav", 40, 330)
    project = make_project(
        tmp_path,
        output={"preset": "audio/wav"},
        audio={
            "voiceover": [{"src": "voz.wav", "start": 2}],
            "music": {"src": "musica.wav", "volume": 0.3},
            "sfx": [{"sound": "pop", "at": 5}, {"sound": "ding", "at": 20}],
            "target_lufs": -16,
        },
    )
    mix_path = tmp_path / "mix.wav"
    mix = AudioExporter(pipeline(project, tmp_path, out=mix_path)).run(ExportRequest(mode="mix"))
    stems = AudioExporter(pipeline(project, tmp_path)).run(ExportRequest(mode="stems"))
    assert [f.track for f in stems.files] == ["VO", "MUS", "SFX"] and not stems.warnings
    reference, _ = read_wav_channels(mix.files[0].path)
    total = np.zeros(reference.shape, dtype=np.float64)
    for f in stems.files:
        samples, _ = read_wav_channels(f.path)
        assert len(samples) == len(reference), f.path.name  # todas têm o tamanho do projeto
        total += samples
    difference = total - reference
    rms = lambda x: float(np.sqrt(np.mean(np.square(x.astype(np.float64)))))  # noqa: E731
    relative_db = 20 * np.log10(rms(difference) / rms(reference))
    assert relative_db < -60, f"a soma das trilhas difere do mix em {relative_db:.1f} dB"
    assert float(np.max(np.abs(difference))) < 0.001  # poucos degraus de 16 bits


def test_item_and_master_effects_reach_the_audio_file(tmp_path):
    """A cadeia de efeitos (DMK-51) vale na saída de áudio: +6 dB no item e -6 dB no master, medidos no arquivo."""
    tone(tmp_path / "voz.wav", 10, slow_tremolo=False)

    def level(**audio) -> float:
        project = make_project(
            tmp_path,
            output={"preset": "audio/wav"},
            audio={"voiceover": [{"src": "voz.wav", **audio.pop("item", {})}], "normalize": "off", **audio},
        )
        result = AudioExporter(pipeline(project, tmp_path, out=tmp_path / "x.wav")).run(ExportRequest())
        samples, _ = read_wav_channels(result.files[0].path)
        return float(20 * np.log10(np.sqrt(np.mean(np.square(samples.astype(np.float64))))))

    plain = level()
    louder = level(item={"effects": [{"type": "amplify", "gain_db": 6}]})
    quieter = level(master_effects=[{"type": "amplify", "gain_db": -6}])
    assert louder - plain == pytest.approx(6.0, abs=0.1)
    assert quieter - plain == pytest.approx(-6.0, abs=0.1)


def test_the_music_stem_carries_the_ducking_it_suffers_in_the_mix(tmp_path):
    tone(tmp_path / "voz.wav", 20, 220, slow_tremolo=False)
    tone(tmp_path / "musica.wav", 20, 330, slow_tremolo=False)
    project = make_project(
        tmp_path,
        output={"preset": "audio/wav"},
        audio={
            "voiceover": [{"src": "voz.wav", "start": 8, "end": 18}],
            "music": {"src": "musica.wav", "volume": 0.4, "ducking": True},
            "normalize": "off",
        },
    )
    stems = AudioExporter(pipeline(project, tmp_path)).run(ExportRequest(mode="stems", tracks=("MUS",)))
    music, _ = read_wav_channels(stems.files[0].path)
    rate = 48000
    level = lambda a, b: float(np.sqrt(np.mean(np.square(music[int(a * rate) : int(b * rate)]))))  # noqa: E731
    assert level(10, 16) < level(1, 6) * 0.6  # sob a voz a música está abaixada; antes dela, não


def test_a_raw_pcm_of_16_bits_48_khz_mono_imports_and_sounds_right(tmp_path):
    rate, seconds, hz = 48000, 2.0, 440.0
    samples = np.round(0.5 * 32767 * np.sin(2 * np.pi * hz * np.arange(int(rate * seconds)) / rate)).astype(
        "<i2"
    )
    raw = tmp_path / "gravacao.pcm"
    raw.write_bytes(samples.tobytes())
    original = raw.read_bytes()
    imported = import_raw_audio(
        "bruto",
        raw,
        encoding="s16",
        byte_order="little",
        channels=1,
        sample_rate=rate,
        start=1.5,
        runner=SubprocessRunner(quiet=True),
    )
    assert raw.read_bytes() == original  # o arquivo original não muda
    assert imported.wav == config.PROJECTS_DIR / "bruto" / "gravacao.wav" and imported.created_project
    assert imported.duration == pytest.approx(seconds)
    decoded, wav_rate = read_wav_channels(imported.wav)
    assert wav_rate == rate and decoded.shape == (len(samples), 1)
    spectrum = np.abs(np.fft.rfft(decoded[:, 0] * np.hanning(len(decoded))))
    assert np.argmax(spectrum) * wav_rate / len(decoded) == pytest.approx(
        hz, abs=1.0
    )  # soa na frequência certa
    saved = Project.load(config.PROJECTS_DIR / "bruto" / "spec.json")
    assert saved.output.preset == "audio/wav" and saved.timeline == []
    assert [(c.src, c.start) for c in saved.audio.voiceover] == [("gravacao.wav", 1.5)]
    with pytest.raises(RawImportError, match="já existe"):
        import_raw_audio("bruto", raw, sample_rate=rate, runner=SubprocessRunner(quiet=True))


def test_raw_pcm_in_other_byte_orders_and_encodings_decodes_to_the_same_wave(tmp_path):
    rate = 16000
    wave = (0.4 * np.sin(2 * np.pi * 300 * np.arange(rate) / rate)).astype(np.float32)
    cases = {
        ("s16", "big"): np.round(wave * 32767).astype(">i2"),
        ("f32", "little"): wave.astype("<f4"),
        ("u8", "little"): (np.round(wave * 127) + 128).astype("u1"),
    }
    for (encoding, order), data in cases.items():
        raw = tmp_path / f"{encoding}{order}.raw"
        raw.write_bytes(data.tobytes())
        imported = import_raw_audio(
            f"projeto-{encoding}",
            raw,
            encoding=encoding,
            byte_order=order,
            sample_rate=rate,
            runner=SubprocessRunner(quiet=True),
        )
        decoded, _ = read_wav_channels(imported.wav) if encoding == "s16" else _read_as_16_bits(imported.wav)
        assert np.max(np.abs(decoded[:, 0] - wave)) < 0.02, (encoding, order)


def _read_as_16_bits(path: Path) -> tuple[np.ndarray, int]:
    """O WAV de outra profundidade (8 bits, ponto flutuante), decodificado para 16 bits pelo ffmpeg: o leitor do
    núcleo só lê 16 bits."""
    out = path.with_name(path.stem + "_16.wav")
    ffmpeg("-i", str(path), "-c:a", "pcm_s16le", str(out))
    return read_wav_channels(out)
