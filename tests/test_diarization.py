"""Diarização: contas puras, o diarizador com motor falso, o download com hash fixado e a fumaça com o modelo real."""

from __future__ import annotations

import importlib.util
import io
import os
import tarfile
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from dmaker.media.diarization import (
    SAMPLE_RATE,
    SherpaDiarizer,
    SpeakerTurn,
    drop_negligible_speakers,
    forced_cluster_counts,
    label_by_appearance,
    speaker_label,
    speaking_seconds,
)
from dmaker.media.downloads import RemoteFile, ensure_archive_member, ensure_file, is_intact
from dmaker.media.wavio import write_wav
from dmaker.voice.speakers import assign_speakers

# ---------- contas puras ----------


def test_labels_follow_the_order_of_first_appearance_and_turns_come_sorted():
    raw = [(5.0, 8.0, 7), (0.0, 4.0, 2), (4.0, 5.0, 7), (9.0, 12.0, 2)]
    turns = label_by_appearance(raw)
    assert [(t.start, t.end, t.speaker) for t in turns] == [
        (0.0, 4.0, "Falante 1"),
        (4.0, 5.0, "Falante 2"),
        (5.0, 8.0, "Falante 2"),
        (9.0, 12.0, "Falante 1"),
    ]
    assert speaker_label(3) == "Falante 3"


def test_empty_or_backwards_turns_are_dropped():
    assert label_by_appearance([(3.0, 3.0, 0), (5.0, 4.0, 0)]) == []


def test_speaking_seconds_sums_each_speaker():
    turns = [SpeakerTurn(0, 4, "Falante 1"), SpeakerTurn(4, 5, "Falante 2"), SpeakerTurn(6, 8, "Falante 1")]
    assert speaking_seconds(turns) == {"Falante 1": 6.0, "Falante 2": 1.0}


def test_a_ghost_speaker_is_dropped_and_the_rest_is_renumbered_without_gaps():
    turns = [
        SpeakerTurn(0, 5, "Falante 1"),
        SpeakerTurn(5, 5.4, "Falante 2"),  # estalo isolado como "pessoa"
        SpeakerTurn(6, 12, "Falante 3"),
    ]
    kept = drop_negligible_speakers(turns, min_seconds=1.0)
    assert [(t.start, t.speaker) for t in kept] == [(0, "Falante 1"), (6, "Falante 2")]


def test_forced_counts_start_at_the_request_and_climb():
    assert forced_cluster_counts(2) == [2, 3, 4]


# ---------- o diarizador com motor falso ----------


class FakeEngine:
    """Devolve grupos conforme `num_clusters` pedido, como o sherpa-onnx (que entrega um falante a menos)."""

    def __init__(self, by_clusters: dict[int, list[tuple[float, float, int]]]):
        self.by_clusters = by_clusters
        self.calls: list[int] = []

    def run(self, samples, num_clusters, on_progress):
        self.calls.append(num_clusters)
        if on_progress:
            on_progress(1, 1)
        return self.by_clusters[num_clusters]


def silent_wav(path: Path, seconds: float = 2.0, rate: int = SAMPLE_RATE) -> Path:
    return write_wav(path, np.zeros(int(seconds * rate), dtype=np.float32), rate)


TWO_VOICES = [(0.0, 5.0, 4), (5.0, 9.0, 9), (9.0, 14.0, 4)]


def diarizer_with(engine: FakeEngine) -> SherpaDiarizer:
    return SherpaDiarizer(engine_loader=lambda: engine)


def test_without_a_count_the_audio_decides_and_progress_is_reported(tmp_path: Path):
    engine = FakeEngine({-1: TWO_VOICES})
    seen: list[tuple[int, int]] = []
    turns = diarizer_with(engine).diarize(
        silent_wav(tmp_path / "a.wav"), on_progress=lambda d, t: seen.append((d, t))
    )
    assert [t.speaker for t in turns] == ["Falante 1", "Falante 2", "Falante 1"]
    assert engine.calls == [-1] and seen == [(1, 1)]


def test_asking_for_n_speakers_climbs_until_the_count_matches(tmp_path: Path):
    one_speaker = [(0.0, 14.0, 0)]
    engine = FakeEngine({2: one_speaker, 3: TWO_VOICES, 4: TWO_VOICES})
    turns = diarizer_with(engine).diarize(silent_wav(tmp_path / "a.wav"), num_speakers=2)
    assert len({t.speaker for t in turns}) == 2
    assert engine.calls == [2, 3]  # parou na primeira que bateu


def test_when_the_count_never_matches_the_closest_attempt_wins(tmp_path: Path):
    three = [(0.0, 4.0, 1), (4.0, 8.0, 2), (8.0, 12.0, 3)]
    engine = FakeEngine({2: [(0.0, 12.0, 0)], 3: three, 4: three})
    turns = diarizer_with(engine).diarize(silent_wav(tmp_path / "a.wav"), num_speakers=2)
    assert engine.calls == [2, 3, 4]
    assert (
        len({t.speaker for t in turns}) == 1
    )  # todas distam 1 do pedido: vale a primeira, a mais perto de 2


def test_the_engine_loads_once_and_wrong_input_is_refused(tmp_path: Path):
    loads: list[int] = []

    def loader():
        loads.append(1)
        return FakeEngine({-1: TWO_VOICES})

    diarizer = SherpaDiarizer(engine_loader=loader)
    wav = silent_wav(tmp_path / "a.wav")
    diarizer.diarize(wav)
    diarizer.diarize(wav)
    assert loads == [1]
    with pytest.raises(ValueError, match="16000 Hz"):
        diarizer.diarize(silent_wav(tmp_path / "b.wav", rate=24000))
    with pytest.raises(ValueError, match="1 ou mais"):
        diarizer.diarize(wav, num_speakers=0)


def test_ghost_speakers_are_dropped_only_when_the_audio_decides(tmp_path: Path):
    ghost = [(0.0, 8.0, 0), (8.0, 8.3, 5), (9.0, 14.0, 3)]
    wav = silent_wav(tmp_path / "a.wav")
    auto = diarizer_with(FakeEngine({-1: ghost})).diarize(wav)
    assert len({t.speaker for t in auto}) == 2
    forced = diarizer_with(FakeEngine({2: ghost, 3: ghost, 4: ghost})).diarize(wav, num_speakers=3)
    assert len({t.speaker for t in forced}) == 3


# ---------- download com hash fixado ----------


def remote(name: str, payload: bytes, url: str = "https://exemplo.invalido/x") -> RemoteFile:
    return RemoteFile(name, url, len(payload), sha256(payload).hexdigest())


def fake_downloader(payloads: dict[str, bytes], calls: list[str]):
    def download(url: str, destination: Path) -> None:
        calls.append(url)
        destination.write_bytes(payloads[url])

    return download


def test_ensure_file_downloads_once_and_reuses_the_intact_file(tmp_path: Path):
    payload = b"modelo"
    expected = remote("m.onnx", payload, "u1")
    calls: list[str] = []
    path = ensure_file(tmp_path, expected, fake_downloader({"u1": payload}, calls))
    again = ensure_file(tmp_path, expected, fake_downloader({"u1": payload}, calls))
    assert path == again == tmp_path / "m.onnx" and is_intact(path, expected)
    assert calls == ["u1"] and not list(tmp_path.glob("*.part"))


def test_a_corrupted_download_is_refused_and_leaves_nothing_behind(tmp_path: Path):
    expected = remote("m.onnx", b"modelo", "u1")
    with pytest.raises(RuntimeError, match="corrompido"):
        ensure_file(tmp_path, expected, fake_downloader({"u1": b"outra coisa"}, []))
    assert list(tmp_path.iterdir()) == []


def make_archive(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:bz2") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_only_the_named_member_is_extracted_and_the_archive_is_removed(tmp_path: Path):
    model = b"pesos do modelo"
    pack = make_archive({"pasta/model.onnx": model, "../../fora.txt": b"malicioso"})
    archive, extracted = remote("pacote.tar.bz2", pack, "u2"), remote("seg.onnx", model)
    calls: list[str] = []
    target = ensure_archive_member(
        tmp_path / "modelos", archive, "pasta/model.onnx", extracted, fake_downloader({"u2": pack}, calls)
    )
    assert target.read_bytes() == model
    assert sorted(p.name for p in (tmp_path / "modelos").iterdir()) == ["seg.onnx"]
    assert not (tmp_path / "fora.txt").exists()
    ensure_archive_member(  # já íntegro: nem baixa de novo
        tmp_path / "modelos", archive, "pasta/model.onnx", extracted, fake_downloader({"u2": pack}, calls)
    )
    assert calls == ["u2"]


def test_a_missing_member_or_a_wrong_hash_inside_the_archive_is_refused(tmp_path: Path):
    pack = make_archive({"pasta/model.onnx": b"outro conteudo"})
    archive = remote("pacote.tar.bz2", pack, "u2")
    download = fake_downloader({"u2": pack}, [])
    with pytest.raises(RuntimeError, match="não traz"):
        ensure_archive_member(tmp_path / "a", archive, "pasta/nada.onnx", remote("x.onnx", b"x"), download)
    with pytest.raises(RuntimeError, match="não bate"):
        ensure_archive_member(tmp_path / "b", archive, "pasta/model.onnx", remote("x.onnx", b"x"), download)
    assert [p.name for p in (tmp_path / "b").iterdir()] == []


# ---------- fumaça: o modelo de verdade ----------


@pytest.mark.skipif(
    os.environ.get("DMAKER_VOICE_SMOKE") != "1", reason="modelo real: defina DMAKER_VOICE_SMOKE=1"
)
@pytest.mark.skipif(
    importlib.util.find_spec("sherpa_onnx") is None or importlib.util.find_spec("kokoro_onnx") is None,
    reason="sherpa-onnx/kokoro-onnx não instalados (pip install -e .[voice])",
)
def test_two_kokoro_voices_are_told_apart(tmp_path: Path):
    """Duas vozes prontas alternando 6 frases: 2 falantes e quase todo o tempo com o falante certo."""
    from dmaker.media.ffmpeg import SubprocessRunner
    from dmaker.text.transcribe import extract_audio_wav
    from dmaker.voice.kokoro import KokoroSynthesizer
    from dmaker.voice.library import VoiceLibrary
    from dmaker.voice.synth import VoiceRequest

    phrases = [
        "Bom dia, pessoal. Hoje eu vou mostrar como funciona o nosso novo editor de vídeos curtos.",
        "Que bom, eu estava esperando por isso. Ele consegue traduzir a fala e manter a música de fundo?",
        "Consegue sim. Ele separa a voz do fundo, traduz cada frase e refaz a fala com a voz de cada pessoa.",
        "Isso é muito útil para quem grava entrevistas, porque cada pessoa mantém a própria voz.",
        "Exatamente. E se alguma frase sair com a voz trocada, dá para corrigir o falante na tabela.",
        "Perfeito. Então vamos começar o teste agora e ver se o resultado fica natural.",
    ]
    library, synthesizer = VoiceLibrary(tmp_path / "vozes"), KokoroSynthesizer()
    pieces, truth, cursor = [], [], 0.0
    pause = np.zeros(int(0.35 * 24000), dtype=np.float32)
    for index, text in enumerate(phrases):
        voice = "dora" if index % 2 == 0 else "alex"
        speech = synthesizer.synthesize(VoiceRequest(text=text, voice=library.get(voice)))
        seconds = len(speech.samples) / speech.sample_rate
        truth.append((cursor, cursor + seconds, voice))
        pieces += [speech.samples, pause]
        cursor += seconds + 0.35
    full = write_wav(tmp_path / "dialogo24.wav", np.concatenate(pieces), 24000)
    wav = extract_audio_wav(
        SubprocessRunner(quiet=True), full, tmp_path / "dialogo16.wav"
    )  # como o pipeline faz

    turns = SherpaDiarizer().diarize(wav)
    assert {t.speaker for t in turns} == {"Falante 1", "Falante 2"}

    # o falante 1 é o primeiro a falar (dora). Duas medidas: a fala inteira de cada frase (o que a dublagem usa) e
    # o tempo de cada instante (mais severa: o começo do arquivo, sem pausa antes da primeira fala, fragmenta)
    expected = {"dora": "Falante 1", "alex": "Falante 2"}
    phrases_heard = assign_speakers([SimpleNamespace(start=a, end=b) for a, b, _ in truth], turns)
    assert phrases_heard == [expected[voice] for _, _, voice in truth]
    ticks = [(tick, voice) for start, end, voice in truth for tick in np.arange(start, end, 0.01)]
    heard = [[t.speaker for t in turns if t.start <= tick < t.end] for tick, _ in ticks]
    covered = [(h, voice) for h, (_, voice) in zip(heard, ticks, strict=True) if h]
    correct = sum(h == [expected[voice]] for h, voice in covered)
    assert len(covered) / len(ticks) >= 0.9  # pausas curtas entre palavras ficam fora dos turnos
    assert correct / len(covered) >= 0.85
