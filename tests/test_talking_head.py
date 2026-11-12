"""A cabeça falante: a estimativa de tempo, o protocolo de linhas do worker e o subprocesso (com um worker de mentira)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from dmaker import config
from dmaker.media import ditto_worker, talking_head
from dmaker.media.ditto_worker import WorkerArguments, parse_arguments
from dmaker.media.talking_head import (
    DittoTalkingHead,
    TalkingHeadError,
    TalkingHeadRequest,
    WorkerEvent,
    estimate_seconds,
    format_duration,
    parse_event,
    progress_message,
)


def test_the_estimate_is_the_measured_fixed_cost_plus_a_cost_per_second_of_video():
    assert estimate_seconds(6.0, has_gpu=True) == 135 + 175 * 6
    assert estimate_seconds(6.0, has_gpu=False) == 170 + 1100 * 6
    assert estimate_seconds(0.0, has_gpu=True) == 135  # o preparo fixo se paga mesmo para um clipe curtíssimo
    assert estimate_seconds(30.0, has_gpu=True) < 180 * 30  # o limite de 180 s de render por segundo de vídeo


@pytest.mark.parametrize(
    ("seconds", "text"), [(45, "45 s"), (135, "2 min 15 s"), (1185, "19 min 45 s"), (3900, "1 h 05 min")]
)
def test_durations_read_naturally(seconds, text):
    assert format_duration(seconds) == text


def test_the_worker_arguments_survive_the_command_line():
    arguments = WorkerArguments(
        models_dir=Path("m"),
        cache_dir=Path("c"),
        photo=Path("f.png"),
        audio=Path("a.wav"),
        frames_dir=Path("q"),
        duration=6.04,
        seed=7,
        steps=15,
    )
    assert parse_arguments(arguments.to_command()) == arguments
    assert talking_head.worker_command(arguments)[1:3] == ["-m", "dmaker.media.ditto_worker"]


def test_the_worker_lines_become_events_and_the_library_noise_is_ignored():
    assert parse_event("ETAPA carregando os modelos\n") == WorkerEvent("ETAPA", "carregando os modelos")
    assert parse_event("DISPOSITIVO OpenVINO em GPU integrada (f16)").kind == "DISPOSITIVO"
    assert parse_event("QUADRO 3 150 C:/pasta com espaço/000002.rgb") == WorkerEvent(
        "QUADRO", frame=3, total=150, path="C:/pasta com espaço/000002.rgb"
    )
    assert parse_event("PRONTO 150 612.3").text == "150 quadros em 612.3 s"
    assert parse_event("ERRO ValueError: sem rosto").text == "ValueError: sem rosto"
    assert parse_event("QUADRO x y") is None and parse_event("QUADRO 1") is None
    assert parse_event("2026-11-12 warning: algo da biblioteca") is None
    assert parse_event(ditto_worker.format_event("QUADRO", 2, 9, "x.rgb")) == WorkerEvent(
        "QUADRO", frame=2, total=9, path="x.rgb"
    )


def test_progress_is_logged_every_tenth_frame_and_on_the_last_with_the_time_per_frame():
    def frame(index, total=25):
        return WorkerEvent("QUADRO", frame=index, total=total, path="x")

    assert progress_message(frame(3), 12.0) is None
    assert progress_message(frame(10), 43.0) == "persona realista: quadro 10 de 25 (4.3 s por quadro)"
    assert progress_message(frame(25), 100.0).startswith("persona realista: quadro 25 de 25")
    assert progress_message(WorkerEvent("ETAPA", "x"), 1.0) is None


# ---------- o subprocesso, com um worker de mentira ----------

FAKE_WORKER = """
import sys
from pathlib import Path
args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
frames = Path(args["--frames-dir"])
mode = Path(args["--audio"]).read_text()
print("ETAPA preparando", flush=True)
print("uma linha solta de biblioteca", flush=True)
print("AVISO a foto e pequena", flush=True)
count = 3
for index in range(count):
    size = 5 if mode == "tamanho-errado" and index == 1 else 24
    path = frames / f"{index:06d}.rgb"
    path.write_bytes(bytes([index]) * size)
    print(f"QUADRO {index + 1} {count} {path}", flush=True)
    if mode == "falha" and index == 1:
        print("ERRO RuntimeError: a GPU parou", flush=True)
        sys.exit(1)
print("PRONTO 3 1.0", flush=True)
"""


@pytest.fixture
def head(tmp_path, monkeypatch) -> DittoTalkingHead:
    script = tmp_path / "worker_falso.py"
    script.write_text(FAKE_WORKER, encoding="utf-8")
    monkeypatch.setattr(
        talking_head,
        "worker_command",
        lambda arguments: [sys.executable, str(script), *arguments.to_command()],
    )
    return DittoTalkingHead(models_dir=tmp_path / "models", cache_dir=tmp_path / "ovcache")


def ask(tmp_path: Path, mode: str) -> TalkingHeadRequest:
    audio = tmp_path / "fala.wav"
    audio.write_text(mode, encoding="utf-8")  # o worker de mentira lê o modo no lugar do áudio
    return TalkingHeadRequest(photo=tmp_path / "foto.png", audio=audio, duration=0.12, size=(4, 2))


def test_the_frames_come_out_in_order_and_the_events_reach_the_log_and_the_warnings(tmp_path, head):
    log: list[str] = []
    warnings: list[str] = []
    frames = list(head.frames(ask(tmp_path, "ok"), log.append, warnings.append))
    assert [frame[0] for frame in frames] == [0, 1, 2] and all(len(frame) == 24 for frame in frames)
    assert warnings == ["a foto e pequena"]
    assert (
        log[0] == "persona realista: preparando" and log[-1] == "persona realista: pronto, 3 quadros em 1.0 s"
    )
    assert any("quadro 3 de 3" in line for line in log)


def test_the_frame_files_are_deleted_as_they_are_read_and_the_temp_folder_goes_away(
    tmp_path, head, monkeypatch
):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    list(head.frames(ask(tmp_path, "ok"), lambda _: None, lambda _: None))
    assert list((tmp_path / "cache").glob("ditto_*")) == []


def test_a_worker_failure_becomes_an_error_with_its_message(tmp_path, head, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    with pytest.raises(TalkingHeadError, match="a GPU parou"):
        list(head.frames(ask(tmp_path, "falha"), lambda _: None, lambda _: None))


def test_a_frame_of_the_wrong_size_is_refused(tmp_path, head, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    with pytest.raises(TalkingHeadError, match="5 bytes.*4x2.*24"):
        list(head.frames(ask(tmp_path, "tamanho-errado"), lambda _: None, lambda _: None))


def test_only_one_drawing_runs_at_a_time_and_the_second_waits_with_a_notice(tmp_path, head, monkeypatch):
    from dmaker.pipeline.filelock import FileLock

    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(talking_head, "LOCK_POLL_SECONDS", 0.01)
    other = FileLock(tmp_path / "cache" / "ditto.lock")
    assert other.try_acquire()  # outro processo desenhando
    log: list[str] = []
    waits = []

    real_sleep = talking_head.time.sleep

    def release_after_first_wait(seconds: float) -> None:
        waits.append(seconds)
        other.release()  # o outro termina
        real_sleep(0)

    monkeypatch.setattr(talking_head.time, "sleep", release_after_first_wait)
    frames = list(head.frames(ask(tmp_path, "ok"), log.append, lambda _: None))
    assert len(frames) == 3 and waits and "aguardando a vez" in log[0]
