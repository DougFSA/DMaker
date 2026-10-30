"""Resposta em fluxo dos motores do agente (Ollama e compatível com a OpenAI) e o Parar que fecha a conexão."""

from __future__ import annotations

import json
import socket
import threading
import time

import pytest

from dmaker.agent.llm import OllamaChat, Reply, StreamingChat, ToolCall
from dmaker.agent.openai_chat import OpenAICompatibleChat, image_data_uri, to_openai_messages
from dmaker.agent.transport import ChatStreamError, StreamGuard

from .test_agent import FakeOpener

# ---------- dublês de resposta em fluxo ----------


def lines_of(*events: dict | str) -> list[bytes]:
    """As linhas de um fluxo NDJSON (ou SSE, se vierem textos): cada evento termina em quebra de linha."""
    return [(e if isinstance(e, str) else json.dumps(e)).encode("utf-8") + b"\n" for e in events]


class StreamResponse:
    """Dublê de `urlopen` em fluxo: entrega as linhas uma a uma, como `for linha in resposta`."""

    def __init__(self, lines: list[bytes], hang_after: int | None = None):
        self.lines = lines
        self.hang_after = hang_after  # depois de N linhas fica esperando, até alguém fechar a resposta
        self.closed = threading.Event()
        self.delivered = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.closed.set()
        return False

    def close(self):
        self.closed.set()

    def __iter__(self):
        for index, line in enumerate(self.lines):
            if self.hang_after is not None and index >= self.hang_after:
                self.closed.wait(timeout=10)
                raise OSError("conexão fechada")
            self.delivered += 1
            yield line


class StreamOpener:
    """Grava a requisição e devolve a resposta programada (ou bloqueia como um servidor que ainda lê o pedido)."""

    def __init__(self, response: StreamResponse | None = None, raises: Exception | None = None):
        self.response = response
        self.raises = raises
        self.requests: list = []

    def __call__(self, req, timeout=None):
        self.requests.append((req, timeout))
        if self.raises is not None:
            raise self.raises
        return self.response

    def body(self) -> dict:
        return json.loads(self.requests[0][0].data.decode("utf-8"))


def ollama_chunk(content: str = "", thinking: str = "", **extra) -> dict:
    message = {"role": "assistant", "content": content}
    if thinking:
        message["thinking"] = thinking
    return {"model": "m", "message": message, "done": False, **extra}


DONE = {"model": "m", "message": {"role": "assistant", "content": ""}, "done": True, "done_reason": "stop"}


class Collector:
    def __init__(self):
        self.deltas: list[tuple[str, str]] = []

    def __call__(self, kind, text):
        self.deltas.append((kind, text))


# ---------- OllamaChat.stream ----------


def test_the_chunks_arrive_in_order_with_the_reasoning_apart_from_the_answer():
    opener = StreamOpener(
        StreamResponse(
            lines_of(
                ollama_chunk(thinking="Vou "),
                ollama_chunk(thinking="pensar."),
                ollama_chunk(content="Olá"),
                ollama_chunk(content=", mundo"),
                {**DONE, "prompt_eval_count": 11, "eval_count": 4},
            )
        )
    )
    seen = Collector()

    reply = OllamaChat(model="m", stream_opener=opener).stream([], [], seen)

    assert seen.deltas == [
        ("thinking", "Vou "),
        ("thinking", "pensar."),
        ("answer", "Olá"),
        ("answer", ", mundo"),
    ]
    assert reply == Reply(
        content="Olá, mundo", thinking="Vou pensar.", prompt_tokens=11, completion_tokens=4, interrupted=False
    )


def test_empty_pieces_are_not_announced():
    opener = StreamOpener(StreamResponse(lines_of(ollama_chunk(), ollama_chunk(content="x"), DONE)))
    seen = Collector()

    OllamaChat(model="m", stream_opener=opener).stream([], [], seen)

    assert seen.deltas == [("answer", "x")]


def test_the_tool_calls_come_with_the_final_reply():
    call = {"function": {"name": "presets", "arguments": {"platform": "instagram"}}}
    opener = StreamOpener(
        StreamResponse(
            lines_of(
                ollama_chunk(content="vou ver"),
                {"message": {"role": "assistant", "content": "", "tool_calls": [call]}, "done": False},
                {**DONE, "eval_count": 7},
            )
        )
    )

    reply = OllamaChat(model="m", stream_opener=opener).stream([], [], Collector())

    assert reply.tool_calls == [ToolCall("presets", {"platform": "instagram"})]
    assert reply.content == "vou ver" and reply.completion_tokens == 7 and reply.interrupted is False


def test_the_request_asks_for_a_stream_and_carries_the_call_options():
    opener = StreamOpener(StreamResponse(lines_of(DONE)))
    chat = OllamaChat(
        model="gpt-oss:20b",
        stream_opener=opener,
        num_ctx=8192,
        temperature=0.2,
        seed=42,
        think="high",
        timeout=30.0,
    )
    messages = [{"role": "user", "content": "o que é isto?", "images": ["aGVsbG8="]}]

    chat.stream(messages, [{"type": "function"}], Collector())

    request, timeout = opener.requests[0]
    body = opener.body()
    assert request.get_full_url().endswith("/api/chat") and request.get_method() == "POST"
    assert body["model"] == "gpt-oss:20b" and body["stream"] is True and body["think"] == "high"
    assert body["options"] == {"num_ctx": 8192, "temperature": 0.2, "seed": 42}
    assert body["messages"][0]["images"] == [
        "aGVsbG8="
    ]  # as imagens vão cruas, em base64, dentro da mensagem
    assert body["tools"] == [{"type": "function"}] and body["keep_alive"] == "60m"
    assert timeout == 30.0  # no fluxo vale por leitura (cada espera por dados), não pela resposta inteira


def test_the_seed_and_the_think_switch_only_travel_when_set():
    opener = StreamOpener(StreamResponse(lines_of(DONE)))

    OllamaChat(model="m", stream_opener=opener).stream([], [], Collector())

    body = opener.body()
    assert body["options"] == {"num_ctx": 16384} and "think" not in body


@pytest.mark.parametrize("think", [True, False, "low", "medium", "high"])
def test_the_effort_goes_as_a_switch_or_as_a_level(think):
    opener = StreamOpener(StreamResponse(lines_of(DONE)))

    OllamaChat(model="m", think=think, stream_opener=opener).stream([], [], Collector())

    assert opener.body()["think"] == think


def test_the_whole_reply_call_also_carries_the_seed():
    opener = FakeOpener({"message": {"content": "oi"}})

    OllamaChat(model="m", seed=7, opener=opener).chat([], [])

    assert json.loads(opener.requests[0][0].data)["options"]["seed"] == 7


def test_stopping_in_the_middle_returns_what_arrived_and_closes_the_connection():
    response = StreamResponse(
        lines_of(ollama_chunk(content="a"), ollama_chunk(content="b"), ollama_chunk(content="c"), DONE)
    )
    opener = StreamOpener(response)
    seen = Collector()

    reply = OllamaChat(model="m", stream_opener=opener).stream(
        [], [], seen, should_stop=lambda: len(seen.deltas) >= 2
    )

    assert reply.interrupted is True and reply.content == "ab"
    assert response.delivered == 2 and response.closed.is_set()  # não leu o resto: fechou a conexão


def test_an_interrupted_reply_never_carries_tool_calls():
    call = {"function": {"name": "render_project", "arguments": {"name_or_path": "x"}}}
    response = StreamResponse(
        lines_of(
            {"message": {"role": "assistant", "content": "", "tool_calls": [call]}, "done": False},
            ollama_chunk(content="texto"),
            DONE,
        )
    )
    seen = Collector()

    reply = OllamaChat(model="m", stream_opener=StreamOpener(response)).stream(
        [], [], seen, should_stop=lambda: bool(seen.deltas)
    )

    assert reply.interrupted is True and reply.tool_calls == []  # parou: nenhuma ferramenta pode rodar


def test_stopping_before_anything_opens_never_touches_the_server():
    opener = StreamOpener(StreamResponse(lines_of(DONE)))

    reply = OllamaChat(model="m", stream_opener=opener).stream([], [], Collector(), should_stop=lambda: True)

    assert reply == Reply(content="", interrupted=True) and opener.requests == []


def test_abort_closes_the_response_while_the_model_is_still_silent():
    response = StreamResponse(lines_of(ollama_chunk(content="a"), DONE), hang_after=0)
    chat = OllamaChat(model="m", stream_opener=StreamOpener(response))
    stop = threading.Event()
    outcome: list[Reply] = []
    worker = threading.Thread(
        target=lambda: outcome.append(chat.stream([], [], Collector(), should_stop=stop.is_set))
    )

    worker.start()
    time.sleep(0.2)  # a leitura está parada, sem nenhum trecho
    stop.set()
    chat.abort()
    worker.join(timeout=5)

    assert not worker.is_alive(), "o Parar não acordou a leitura"
    assert outcome[0].interrupted is True and outcome[0].content == "" and response.closed.is_set()


def test_a_stop_asked_before_the_stream_starts_is_not_lost_when_the_signal_was_set_first():
    chat = OllamaChat(model="m", stream_opener=StreamOpener(StreamResponse(lines_of(DONE))))
    stop = threading.Event()
    stop.set()
    chat.abort()

    reply = chat.stream([], [], Collector(), should_stop=stop.is_set)

    assert reply.interrupted is True


def test_an_old_abort_does_not_cancel_the_next_stream():
    opener = StreamOpener(StreamResponse(lines_of(ollama_chunk(content="oi"), DONE)))
    chat = OllamaChat(model="m", stream_opener=opener)
    chat.abort()  # ninguém estava lendo: não pode sobrar nada para o fluxo seguinte

    reply = chat.stream([], [], Collector())

    assert reply.interrupted is False and reply.content == "oi"


def test_an_error_line_in_the_middle_of_the_stream_is_reported():
    opener = StreamOpener(
        StreamResponse(lines_of(ollama_chunk(content="a"), {"error": "memória insuficiente"}))
    )

    with pytest.raises(ChatStreamError, match="memória insuficiente"):
        OllamaChat(model="m", stream_opener=opener).stream([], [], Collector())


def test_a_stream_that_ends_without_done_is_an_error_not_a_silent_cut():
    opener = StreamOpener(StreamResponse(lines_of(ollama_chunk(content="a"))))

    with pytest.raises(ChatStreamError, match="terminou antes do fim"):
        OllamaChat(model="m", stream_opener=opener).stream([], [], Collector())


def test_an_unreadable_line_is_reported_with_a_clear_message():
    opener = StreamOpener(StreamResponse([b"isto nao e json\n"]))

    with pytest.raises(ChatStreamError, match="ilegível"):
        OllamaChat(model="m", stream_opener=opener).stream([], [], Collector())


def test_a_connection_failure_is_raised_when_nobody_asked_to_stop():
    opener = StreamOpener(raises=OSError("conexão recusada"))

    with pytest.raises(OSError, match="recusada"):
        OllamaChat(model="m", stream_opener=opener).stream([], [], Collector())


def test_blank_lines_between_events_are_skipped():
    opener = StreamOpener(
        StreamResponse([b"\n", *lines_of(ollama_chunk(content="a")), b"  \n", *lines_of(DONE)])
    )
    seen = Collector()

    reply = OllamaChat(model="m", stream_opener=opener).stream([], [], seen)

    assert reply.content == "a"


def test_only_the_streaming_engines_satisfy_the_streaming_protocol():
    class OnlyChat:
        def chat(self, messages, tools):
            return Reply("")

    assert isinstance(OllamaChat(model="m"), StreamingChat)
    assert isinstance(OpenAICompatibleChat(model="m"), StreamingChat)
    assert not isinstance(
        OnlyChat(), StreamingChat
    )  # os 13 falsos de teste e a tradução continuam só com chat()


# ---------- OpenAICompatibleChat.stream (SSE) ----------


def sse(payload: dict | str) -> str:
    return "data: " + (payload if isinstance(payload, str) else json.dumps(payload))


def delta(**fields) -> dict:
    return {"choices": [{"index": 0, "delta": fields, "finish_reason": None}]}


def test_openai_sse_chunks_arrive_in_order_with_usage_at_the_end():
    opener = StreamOpener(
        StreamResponse(
            lines_of(
                ": ping",
                sse(delta(role="assistant", content="")),
                sse(delta(reasoning_content="Hmm. ")),
                sse(delta(content="Olá")),
                sse(delta(content=" de novo")),
                sse({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}),
                sse({"choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": 5}}),
                "data: [DONE]",
            )
        )
    )
    seen = Collector()

    reply = OpenAICompatibleChat(model="m", stream_opener=opener).stream([], [], seen)

    assert seen.deltas == [("thinking", "Hmm. "), ("answer", "Olá"), ("answer", " de novo")]
    assert reply == Reply(
        content="Olá de novo", thinking="Hmm. ", prompt_tokens=20, completion_tokens=5, interrupted=False
    )
    body = opener.body()
    assert body["stream"] is True and body["stream_options"] == {"include_usage": True}
    assert opener.requests[0][0].get_full_url().endswith("/v1/chat/completions")


def test_openai_tool_call_arguments_come_in_pieces_and_are_joined_by_index():
    first = {"index": 0, "id": "c1", "function": {"name": "presets", "arguments": ""}}
    pieces = [
        delta(tool_calls=[first]),
        delta(tool_calls=[{"index": 0, "function": {"arguments": '{"platform": '}}]),
        delta(tool_calls=[{"index": 0, "function": {"arguments": '"instagram"}'}}]),
        delta(tool_calls=[{"index": 1, "id": "c2", "function": {"name": "job_status", "arguments": "{}"}}]),
    ]
    opener = StreamOpener(StreamResponse(lines_of(*[sse(p) for p in pieces], "data: [DONE]")))

    reply = OpenAICompatibleChat(model="m", stream_opener=opener).stream([], [], Collector())

    assert reply.tool_calls == [ToolCall("presets", {"platform": "instagram"}), ToolCall("job_status", {})]


def test_openai_stream_without_done_but_with_a_finish_reason_still_completes():
    stop = {"choices": [{"index": 0, "delta": {"content": "fim"}, "finish_reason": "stop"}]}
    opener = StreamOpener(StreamResponse(lines_of(sse(stop))))

    reply = OpenAICompatibleChat(model="m", stream_opener=opener).stream([], [], Collector())

    assert reply.content == "fim" and reply.interrupted is False


def test_openai_stream_cut_before_any_finish_is_an_error():
    opener = StreamOpener(StreamResponse(lines_of(sse(delta(content="a")))))

    with pytest.raises(ChatStreamError, match="terminou antes do fim"):
        OpenAICompatibleChat(model="m", stream_opener=opener).stream([], [], Collector())


def test_openai_stop_in_the_middle_closes_and_keeps_the_partial_text():
    response = StreamResponse(lines_of(sse(delta(content="a")), sse(delta(content="b")), "data: [DONE]"))
    seen = Collector()

    reply = OpenAICompatibleChat(model="m", stream_opener=StreamOpener(response)).stream(
        [], [], seen, should_stop=lambda: bool(seen.deltas)
    )

    assert reply.interrupted is True and reply.content == "a" and response.closed.is_set()


def test_openai_stream_error_event_is_reported():
    opener = StreamOpener(StreamResponse(lines_of(sse({"error": {"message": "contexto estourou"}}))))

    with pytest.raises(ChatStreamError, match="contexto estourou"):
        OpenAICompatibleChat(model="m", stream_opener=opener).stream([], [], Collector())


def test_openai_request_carries_temperature_seed_tools_and_the_key():
    opener = StreamOpener(StreamResponse(lines_of("data: [DONE]")))
    chat = OpenAICompatibleChat(
        model="m", temperature=0.3, seed=9, api_key="segredo", stream_opener=opener, timeout=12.0
    )

    chat.stream([{"role": "user", "content": "oi"}], [{"type": "function"}], Collector())

    request, timeout = opener.requests[0]
    body = opener.body()
    assert body["temperature"] == 0.3 and body["seed"] == 9 and body["tools"] == [{"type": "function"}]
    assert request.get_header("Authorization") == "Bearer segredo" and timeout == 12.0


# ---------- imagens no motor openai ----------


def test_images_become_image_url_parts_with_the_type_from_the_signature():
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "o que é isto?", "images": ["iVBORw0KGgo=", "/9j/4AAQ"]},
        {"role": "user", "content": "só texto"},
    ]

    converted = to_openai_messages(messages)

    assert converted[0] == {"role": "system", "content": "s"}
    assert converted[1]["content"] == [
        {"type": "text", "text": "o que é isto?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,/9j/4AAQ"}},
    ]
    assert converted[2] == {"role": "user", "content": "só texto"}


def test_image_data_uri_knows_webp_keeps_ready_uris_and_defaults_to_png():
    assert image_data_uri("UklGRgAAAA==").startswith("data:image/webp;base64,")
    assert image_data_uri("data:image/gif;base64,AAAA") == "data:image/gif;base64,AAAA"
    assert image_data_uri("AAAA").startswith("data:image/png;base64,")


# ---------- o Parar com sockets de verdade ----------


class RawServer:
    """Servidor TCP mínimo: lê o pedido e deixa o teste decidir o que responder; avisa quando o cliente fecha."""

    def __init__(self, respond):
        self.respond = respond
        self.client_closed = threading.Event()
        self._listener = socket.socket()
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self.port = self._listener.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _serve(self):
        try:
            conn, _ = self._listener.accept()
        except OSError:
            return
        with conn:
            conn.settimeout(15)
            received = b""
            while b"\r\n\r\n" not in received:
                received += conn.recv(65536)
            head, _, body = received.partition(b"\r\n\r\n")
            length = next(
                (
                    int(line.split(b":")[1])
                    for line in head.split(b"\r\n")
                    if line.lower().startswith(b"content-length")
                ),
                0,
            )
            while len(body) < length:
                body += conn.recv(65536)
            self.respond(conn)
            try:  # o cliente fechar a conexão faz o recv devolver vazio (ou reiniciar a conexão)
                while conn.recv(4096):
                    pass
            except OSError:
                pass
            self.client_closed.set()

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc_info):
        self._listener.close()
        self._thread.join(timeout=5)
        return False


def chunked(conn: socket.socket, text: str) -> None:
    data = text.encode("utf-8")
    conn.sendall(f"{len(data):x}\r\n".encode() + data + b"\r\n")


def start_chunked_response(conn: socket.socket) -> None:
    conn.sendall(
        b"HTTP/1.1 200 OK\r\nContent-Type: application/x-ndjson\r\nTransfer-Encoding: chunked\r\n\r\n"
    )


def run_in_thread(chat, stop: threading.Event, seen) -> tuple[threading.Thread, list]:
    outcome: list = []

    def work():
        try:
            outcome.append(
                chat.stream([{"role": "user", "content": "oi"}], [], seen, should_stop=stop.is_set)
            )
        except Exception as exc:  # noqa: BLE001 - o teste confere o que veio
            outcome.append(exc)

    worker = threading.Thread(target=work)
    worker.start()
    return worker, outcome


def test_stop_before_the_first_chunk_closes_the_real_connection():
    """O modelo ainda lê o pedido: o servidor aceitou a conexão e não respondeu nada (nem os cabeçalhos)."""
    with RawServer(lambda conn: None) as server:
        chat = OllamaChat(model="m", base_url=server.url, timeout=30)
        stop = threading.Event()
        worker, outcome = run_in_thread(chat, stop, Collector())
        time.sleep(0.5)  # a leitura está presa nos cabeçalhos que nunca chegam

        started = time.monotonic()
        stop.set()
        chat.abort()
        worker.join(timeout=5)

        assert not worker.is_alive(), "o Parar não acordou a leitura presa nos cabeçalhos"
        assert time.monotonic() - started < 3
        assert isinstance(outcome[0], Reply) and outcome[0].interrupted is True
        assert server.client_closed.wait(timeout=5), "o servidor não viu a conexão cair"


def test_stop_between_chunks_closes_the_real_connection():
    def respond(conn):
        start_chunked_response(conn)
        chunked(conn, json.dumps(ollama_chunk(content="primeiro")) + "\n")  # e depois silêncio

    with RawServer(respond) as server:
        chat = OllamaChat(model="m", base_url=server.url, timeout=30)
        stop = threading.Event()
        first_chunk = threading.Event()

        def on_delta(kind, text):
            first_chunk.set()

        worker, outcome = run_in_thread(chat, stop, on_delta)
        assert first_chunk.wait(timeout=5), "o primeiro trecho não chegou"

        stop.set()
        chat.abort()
        worker.join(timeout=5)

        assert not worker.is_alive()
        assert outcome[0].interrupted is True and outcome[0].content == "primeiro"
        assert server.client_closed.wait(timeout=5)


def test_chunks_are_delivered_as_they_arrive_not_at_the_end():
    def respond(conn):
        start_chunked_response(conn)
        for word in ("um", "dois", "três"):
            chunked(conn, json.dumps(ollama_chunk(content=word)) + "\n")
            time.sleep(0.3)
        chunked(conn, json.dumps(DONE) + "\n")
        conn.sendall(b"0\r\n\r\n")

    with RawServer(respond) as server:
        arrivals: list[tuple[str, float]] = []
        started = time.monotonic()

        reply = OllamaChat(model="m", base_url=server.url, timeout=30).stream(
            [], [], lambda kind, text: arrivals.append((text, time.monotonic() - started))
        )

    assert reply.content == "umdoistrês" and reply.interrupted is False
    assert [word for word, _ in arrivals] == ["um", "dois", "três"]
    assert arrivals[-1][1] - arrivals[0][1] >= 0.4  # chegaram espaçados: houve fluxo de verdade


def test_openai_stop_before_the_first_chunk_closes_the_real_connection():
    with RawServer(lambda conn: None) as server:
        chat = OpenAICompatibleChat(model="m", base_url=server.url, timeout=30)
        stop = threading.Event()
        worker, outcome = run_in_thread(chat, stop, Collector())
        time.sleep(0.5)

        stop.set()
        chat.abort()
        worker.join(timeout=5)

        assert not worker.is_alive()
        assert outcome[0].interrupted is True
        assert server.client_closed.wait(timeout=5)


def test_the_guard_closes_late_registrations_when_the_stop_already_came():
    guard = StreamGuard()
    closed = []
    guard.begin()
    guard.abort()

    kept = guard.register(lambda: closed.append("fechou"))

    assert kept is False and closed == ["fechou"] and guard.aborted is True
