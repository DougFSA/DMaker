"""Os quadros de instante em segundo plano: pedir, acompanhar, cache, erro e o pedido novo que supera o antigo.
O renderizador é falso (sem ffmpeg): aqui só o que as tarefas decidem."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from dmaker.domain.spec import Project
from dmaker.media.ffmpeg import FFmpegError
from dmaker.pipeline.instant_frame import InstantFrame
from dmaker.pipeline.instant_frame_tasks import (
    InstantFrameStatus,
    InstantFrameTasks,
    failure_message,
)

PROJECT = Project.model_validate(
    {"name": "p", "timeline": [{"type": "card", "title": "x", "duration": 5.0, "motion": "none"}]}
)


class FakeRenderer:
    """Guarda o que renderizou; `gate` segura o trabalho até alguém liberar, para os testes controlarem a corrida."""

    def __init__(self, gate: threading.Event | None = None, fail: Exception | None = None) -> None:
        self.gate, self.fail = gate, fail
        self.rendered: list[str] = []
        self.disk: dict[tuple[str, str], InstantFrame] = {}

    def key(self, project: Project, t: float) -> str:
        return f"{round(t * 30):016x}"

    def instant(self, project: Project, t: float) -> float:
        return round(t * 30) / 30

    def cached(self, name: str, key: str) -> InstantFrame | None:
        return self.disk.get((name, key))

    def render(self, project: Project, t: float, key: str | None = None, checkpoint=None) -> InstantFrame:
        if self.gate is not None:
            assert self.gate.wait(10), "o teste esqueceu de liberar o trabalho"
        if checkpoint is not None:
            checkpoint()
        if self.fail is not None:
            raise self.fail
        frame = InstantFrame(Path(f"{key}.png"), key or "", self.instant(project, t), ("uma nota",))
        self.disk[(project.name, frame.key)] = frame
        self.rendered.append(frame.key)
        return frame


def wait_until(
    tasks: InstantFrameTasks, renderer: FakeRenderer, key: str, *, still: str = "pending"
) -> InstantFrameStatus:
    deadline = time.time() + 10
    while time.time() < deadline:
        status = tasks.status("p", key, renderer)
        if status is not None and status.state != still:
            return status
        time.sleep(0.01)
    raise AssertionError("o quadro não saiu do estado " + still)


def factory(renderer: FakeRenderer):
    return lambda runner, log: renderer


def test_a_request_starts_the_frame_in_the_background_and_the_next_one_comes_from_the_cache():
    tasks, renderer = InstantFrameTasks(), FakeRenderer()
    asked = tasks.request(PROJECT, 1.0, factory(renderer))
    assert (
        asked.key == f"{30:016x}" and asked.at == pytest.approx(1.0) and asked.state in ("pending", "ready")
    )

    done = wait_until(tasks, renderer, asked.key)
    assert done.state == "ready" and done.frame.path == Path(f"{asked.key}.png")
    assert done.notes == ["uma nota"] and done.percent == 100 and done.error is None

    again = tasks.request(PROJECT, 1.0, factory(renderer))  # já está em cache: pronto na hora
    assert again.state == "ready" and renderer.rendered == [asked.key]


def test_the_same_pending_frame_asked_twice_is_made_once():
    gate = threading.Event()
    tasks, renderer = InstantFrameTasks(), FakeRenderer(gate)
    first = tasks.request(PROJECT, 1.0, factory(renderer))
    second = tasks.request(PROJECT, 1.0, factory(renderer))
    assert second is first and first.state == "pending"
    gate.set()
    wait_until(tasks, renderer, first.key)
    assert renderer.rendered == [first.key]


def test_a_newer_request_of_the_same_project_supersedes_the_one_in_progress():
    gate = threading.Event()
    tasks, renderer = InstantFrameTasks(), FakeRenderer(gate)
    old = tasks.request(PROJECT, 1.0, factory(renderer))
    new = tasks.request(PROJECT, 2.0, factory(renderer))
    assert old.state == "superseded" and new.state == "pending"  # na hora, sem esperar o ffmpeg

    gate.set()
    assert wait_until(tasks, renderer, new.key).state == "ready"
    assert tasks.status("p", old.key, renderer).state == "superseded"
    assert renderer.rendered == [new.key]  # o antigo parou no ponto de parada e nada entregou


def test_a_request_that_was_still_waiting_its_turn_never_starts():
    gate = threading.Event()
    tasks, renderer = InstantFrameTasks(), FakeRenderer(gate)
    first = tasks.request(PROJECT, 1.0, factory(renderer))  # segura a vez
    waiting = tasks.request(PROJECT, 2.0, factory(renderer))
    last = tasks.request(PROJECT, 3.0, factory(renderer))
    assert first.state == "superseded" and waiting.state == "superseded" and last.state == "pending"

    gate.set()
    assert wait_until(tasks, renderer, last.key).state == "ready"
    assert renderer.rendered == [last.key]


def test_projects_do_not_supersede_each_other():
    gate = threading.Event()
    tasks, renderer = InstantFrameTasks(), FakeRenderer(gate)
    other = Project.model_validate({**PROJECT.model_dump(mode="json"), "name": "q"})
    mine = tasks.request(PROJECT, 1.0, factory(renderer))
    theirs = tasks.request(other, 2.0, factory(renderer))
    assert mine.state == "pending" and theirs.state == "pending"
    gate.set()
    assert wait_until(tasks, renderer, mine.key).state == "ready"


def test_a_failure_becomes_an_error_state_with_a_message_in_portuguese():
    tasks, renderer = (
        InstantFrameTasks(),
        FakeRenderer(fail=FileNotFoundError("Arquivo não encontrado: take.mp4")),
    )
    asked = tasks.request(PROJECT, 1.0, factory(renderer))
    done = wait_until(tasks, renderer, asked.key)
    assert done.state == "error" and done.error == "Arquivo não encontrado: take.mp4" and done.frame is None

    renderer.fail = None  # o arquivo voltou: pedir de novo refaz (um erro não fica preso na memória)
    retry = tasks.request(PROJECT, 1.0, factory(renderer))
    assert retry.state in ("pending", "ready") and wait_until(tasks, renderer, asked.key).state == "ready"


def test_failure_messages():
    assert failure_message(FileNotFoundError("falta o arquivo")) == "falta o arquivo"
    assert failure_message(ValueError("sem duração")) == "sem duração"
    assert failure_message(KeyError("Preset desconhecido: x")) == "Preset desconhecido: x"
    ffmpeg = failure_message(FFmpegError("falhou", ["ffmpeg"], "linha 1\nFilter not found"))
    assert ffmpeg == "O ffmpeg falhou ao montar o quadro (Filter not found)."
    assert failure_message(RuntimeError("boom")) == "Não foi possível montar o quadro: RuntimeError: boom"


def test_an_unknown_key_is_unknown_and_a_stored_frame_still_counts_after_a_restart():
    renderer = FakeRenderer()
    assert InstantFrameTasks().status("p", f"{1:016x}", renderer) is None
    renderer.disk[("p", f"{1:016x}")] = InstantFrame(Path("a.png"), f"{1:016x}", 1 / 30, ("n",))
    status = InstantFrameTasks().status("p", f"{1:016x}", renderer)  # outro processo: nada na memória
    assert status.state == "ready" and status.notes == ["n"]


def test_a_ready_frame_whose_file_was_cleaned_must_be_asked_again():
    tasks, renderer = InstantFrameTasks(), FakeRenderer()
    asked = tasks.request(PROJECT, 1.0, factory(renderer))
    wait_until(tasks, renderer, asked.key)
    renderer.disk.clear()  # `dmaker clean` apagou o arquivo
    assert tasks.status("p", asked.key, renderer) is None
    assert tasks.request(PROJECT, 1.0, factory(renderer)).state in ("pending", "ready")
