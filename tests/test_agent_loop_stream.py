"""O laço do agente em fluxo: trechos agrupados, etapas, Parar em cada ponto, aparo do histórico e conversa livre."""

from __future__ import annotations

import threading

from dmaker.agent.free_session import FREE_SYSTEM_PROMPT, NO_TOOLS_ANSWER, FreeSession
from dmaker.agent.llm import Reply, StreamingChat, ToolCall, reply_stoppable
from dmaker.agent.loop import INTERRUPTED_MARK, STOPPED_TOOL_RESULT, AgentLoop, TurnControl
from dmaker.agent.safety import ConfirmationRequest, ToolGate
from dmaker.agent.tools import ToolSpec
from dmaker.agent.triage import triage

# ---------- dublês ----------


class Turn:
    """Uma resposta programada do modelo falso: os trechos, as chamadas de ferramenta e como termina."""

    def __init__(self, chunks=(), tool_calls=(), thinking=None, hang_after=None, prompt_tokens=None):
        self.chunks = list(chunks)  # [("answer" | "thinking", texto)]
        self.tool_calls = list(tool_calls)
        self.thinking = thinking
        self.hang_after = (
            hang_after  # fica parado depois de N trechos, como um modelo lendo o pedido (0: antes do 1º)
        )
        self.prompt_tokens = prompt_tokens


class FlowChat:
    """Um motor em fluxo falso: entrega os trechos de cada `Turn`, respeita `should_stop` e `abort()` como o de verdade."""

    def __init__(self, *turns: Turn):
        self.turns = list(turns)
        self.requests: list[tuple[list[dict], list[dict]]] = []
        self.aborts = 0
        self._aborted = threading.Event()
        self.waiting = threading.Event()  # fica de pé quando o fluxo parou à espera do Parar

    def chat(self, messages, tools):
        raise AssertionError("o laço devia usar o fluxo")

    def abort(self):
        self.aborts += 1
        self._aborted.set()

    def stream(self, messages, tools, on_delta, should_stop=None):
        self.requests.append(([dict(m) for m in messages], tools))
        self._aborted.clear()
        turn = self.turns.pop(0)
        content, thinking = [], []
        for index, (kind, text) in enumerate(turn.chunks):
            if turn.hang_after is not None and index >= turn.hang_after:
                break
            (thinking if kind == "thinking" else content).append(text)
            on_delta(kind, text)
            if should_stop is not None and should_stop():
                return Reply("".join(content), thinking="".join(thinking) or None, interrupted=True)
        if turn.hang_after is not None:
            self.waiting.set()
            self._aborted.wait(timeout=10)
            return Reply("".join(content), thinking="".join(thinking) or None, interrupted=True)
        return Reply(
            "".join(content),
            tool_calls=turn.tool_calls,
            thinking=turn.thinking or ("".join(thinking) or None),
            prompt_tokens=turn.prompt_tokens,
        )


class OnlyChat:
    """Um motor sem fluxo (só `chat`), como os falsos de antes: nada de evento novo pode aparecer."""

    def __init__(self, *replies: Reply):
        self.replies = list(replies)

    def chat(self, messages, tools):
        return self.replies.pop(0)


class Host:
    def __init__(self, result="feito"):
        self.calls: list[tuple[str, dict]] = []
        self.result = result

    def specs(self):
        return [
            ToolSpec(
                "render_project",
                "r",
                {"type": "object", "properties": {"name_or_path": {"type": "string"}}},
            ),
            ToolSpec("presets", "p", {"type": "object", "properties": {}}),
        ]

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        return self.result


def make_loop(chat, host=None, gate=None, **kwargs):
    events: list[tuple[str, dict]] = []
    loop = AgentLoop(
        model=chat,
        tools=host or Host(),
        system="sistema",
        on_event=lambda kind, data: events.append((kind, data)),
        gate=gate,
        **kwargs,
    )
    return loop, events


def kinds(events):
    return [kind for kind, _ in events]


def words(*texts: str) -> list[tuple[str, str]]:
    return [("answer", text) for text in texts]


# ---------- fluxo ----------


def test_the_streaming_engines_are_told_apart_from_the_whole_reply_ones():
    assert isinstance(FlowChat(), StreamingChat) and not isinstance(OnlyChat(), StreamingChat)


def test_the_answer_arrives_in_grouped_pieces_then_as_the_final_event():
    chat = FlowChat(Turn(chunks=words(*[f"p{i} " for i in range(500)])))
    loop, events = make_loop(chat)

    answer = loop.ask("oi")

    pieces = [data["text"] for kind, data in events if kind == "answer_delta"]
    assert answer == "".join(f"p{i} " for i in range(500))
    assert "".join(pieces) == answer
    assert 1 <= len(pieces) <= 4  # 500 trechos chegaram de uma vez: viram poucos eventos, nunca um por trecho
    assert events[-1] == ("answer", {"text": answer})  # o evento final continua, para quem não usa o fluxo


def test_the_reasoning_comes_apart_from_the_answer_and_keeps_its_own_event():
    chat = FlowChat(Turn(chunks=[("thinking", "Vou pensar. "), ("answer", "Pronto.")]))
    loop, events = make_loop(chat)

    loop.ask("oi")

    assert [d["text"] for k, d in events if k == "thinking_delta"] == ["Vou pensar. "]
    assert [d["text"] for k, d in events if k == "answer_delta"] == ["Pronto."]
    assert ("thinking", {"text": "Vou pensar. "}) in events
    order = [k for k in kinds(events) if k in ("thinking_delta", "answer_delta", "model_reply", "answer")]
    assert order == ["thinking_delta", "answer_delta", "model_reply", "answer"]


def test_the_status_follows_the_stages_of_one_answer():
    chat = FlowChat(Turn(chunks=[("thinking", "hmm "), ("answer", "ok")]))
    loop, events = make_loop(chat)

    loop.ask("oi")

    assert [d["stage"] for k, d in events if k == "status"] == ["reading", "thinking", "writing"]
    labels = [d["label"] for k, d in events if k == "status"]
    assert labels == ["Lendo o pedido", "Pensando", "Escrevendo a resposta"]


def test_a_cold_model_says_it_is_loading_until_the_first_piece():
    chat = FlowChat(Turn(chunks=words("oi")))
    loop, events = make_loop(chat)

    loop.ask("oi", control=TurnControl(model_cold=True))

    assert [d["stage"] for k, d in events if k == "status"] == ["loading_model", "writing"]


def test_a_tool_call_announces_the_tool_and_the_next_round_reads_again():
    chat = FlowChat(
        Turn(tool_calls=[ToolCall("presets", {})]),
        Turn(chunks=words("Os formatos são Reels.")),
    )
    host = Host(result="lista")
    loop, events = make_loop(chat, host)

    loop.ask("quais formatos?")

    statuses = [(d["stage"], d.get("tool")) for k, d in events if k == "status"]
    assert statuses == [("reading", None), ("tool", "presets"), ("reading", None), ("writing", None)]
    tool_status = next(d for k, d in events if k == "status" and d["stage"] == "tool")
    assert tool_status["label"] == "Chamando a ferramenta presets"
    assert host.calls == [("presets", {})]


def test_an_engine_without_streaming_produces_none_of_the_new_events():
    chat = OnlyChat(Reply("", [ToolCall("presets", {})]), Reply("pronto", thinking="pensei"))
    loop, events = make_loop(chat)

    loop.ask("oi", control=TurnControl(model_cold=True))

    assert kinds(events) == ["model_reply", "tool_call", "tool_result", "model_reply", "thinking", "answer"]


# ---------- Parar ----------


def test_stopping_in_the_middle_keeps_the_partial_text_marked_in_history_and_event():
    chat = FlowChat(Turn(chunks=words("Os formatos ", "são ", "Reels")))
    consulted = {"times": 0}

    def should_stop():  # o laço consulta uma vez ao começar e o falso, a cada trecho: a pessoa para no segundo trecho
        consulted["times"] += 1
        return consulted["times"] >= 3

    loop, events = make_loop(chat)

    answer = loop.ask("oi", control=TurnControl(should_stop=should_stop))

    assert loop.interrupted is True and answer == "Os formatos são "
    assert ("answer", {"text": "Os formatos são ", "interrupted": True}) in events
    assert loop.history[-1] == {"role": "assistant", "content": f"Os formatos são\n\n{INTERRUPTED_MARK}"}


def test_stopping_before_the_first_piece_closes_the_connection_and_keeps_only_the_mark():
    chat = FlowChat(Turn(chunks=words("nunca chega"), hang_after=0))
    stopped = threading.Event()
    loop, events = make_loop(chat)

    def run():
        loop.ask("oi", control=TurnControl(should_stop=stopped.is_set))

    worker = threading.Thread(target=run)
    worker.start()
    assert chat.waiting.wait(timeout=5)  # o modelo ainda lê o pedido
    stopped.set()  # primeiro o sinal...
    chat.abort()  # ...depois a conexão, nesta ordem
    worker.join(timeout=5)

    assert not worker.is_alive() and loop.interrupted is True
    assert ("answer", {"text": "", "interrupted": True}) in events
    assert loop.history[-1] == {"role": "assistant", "content": INTERRUPTED_MARK}


def test_no_tool_runs_after_the_stop_and_every_requested_call_still_gets_a_result():
    stop = {"now": False}

    class StopWhileReading(FlowChat):
        def stream(self, messages, tools, on_delta, should_stop=None):
            reply = super().stream(messages, tools, on_delta, should_stop)
            stop["now"] = True  # a pessoa para logo depois de o modelo pedir as duas ferramentas
            return reply

    chat = StopWhileReading(
        Turn(tool_calls=[ToolCall("presets", {}), ToolCall("render_project", {"name_or_path": "x"})])
    )
    host = Host()
    loop, events = make_loop(chat, host)

    loop.ask("faz as duas coisas", control=TurnControl(should_stop=lambda: stop["now"]))

    assert host.calls == []  # nenhuma ferramenta rodou
    history = loop.history
    results = [m for m in history if m["role"] == "tool"]
    assert [m["content"] for m in results] == [STOPPED_TOOL_RESULT, STOPPED_TOOL_RESULT]
    assert [m["tool_name"] for m in results] == ["presets", "render_project"]  # o par nunca se separa
    assert history[-1]["content"] == INTERRUPTED_MARK
    assert kinds(events).count("tool_blocked") == 2 and loop.interrupted


def test_a_stop_during_a_tool_ends_the_turn_before_the_next_model_call():
    stop = {"now": False}

    class StoppingHost(Host):
        def call(self, name, arguments):
            stop["now"] = True  # a pessoa para enquanto a ferramenta roda (ela não é interrompível)
            return super().call(name, arguments)

    chat = FlowChat(Turn(tool_calls=[ToolCall("presets", {})]))
    host = StoppingHost()
    loop, events = make_loop(chat, host)

    loop.ask("lista", control=TurnControl(should_stop=lambda: stop["now"]))

    assert (
        host.calls == [("presets", {})] and len(chat.requests) == 1
    )  # a segunda volta ao modelo não aconteceu
    assert loop.interrupted and loop.history[-1]["content"] == INTERRUPTED_MARK


def test_the_next_message_after_a_stop_runs_normally():
    chat = FlowChat(Turn(chunks=words("parcial"), hang_after=1), Turn(chunks=words("Tudo certo.")))
    stopped = threading.Event()
    loop, _ = make_loop(chat)
    worker = threading.Thread(
        target=lambda: loop.ask("primeira", control=TurnControl(should_stop=stopped.is_set))
    )
    worker.start()
    assert chat.waiting.wait(timeout=5)
    stopped.set()
    chat.abort()
    worker.join(timeout=5)

    answer = loop.ask("segunda")

    assert answer == "Tudo certo." and loop.interrupted is False
    sent = chat.requests[-1][0]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert INTERRUPTED_MARK in sent[2]["content"]  # o modelo sabe que a fala anterior ficou pela metade


def test_a_stop_asked_before_the_turn_even_starts_never_calls_the_model():
    chat = FlowChat()
    loop, events = make_loop(chat)

    loop.ask("oi", control=TurnControl(should_stop=lambda: True))

    assert chat.requests == [] and loop.interrupted is True
    assert ("answer", {"text": "", "interrupted": True}) in events


# ---------- histórico guardado e aparo ----------


def test_the_history_is_readable_without_the_system_prompt_and_can_be_loaded_back():
    first = FlowChat(Turn(chunks=words("Olá.")))
    loop, _ = make_loop(first)
    loop.ask("oi")
    saved = loop.history

    assert saved == [{"role": "user", "content": "oi"}, {"role": "assistant", "content": "Olá."}]

    second = FlowChat(Turn(chunks=words("Lembro.")))
    resumed, _ = make_loop(second)
    resumed.load_history(saved)
    resumed.ask("e agora?")

    sent = second.requests[0][0]
    assert [(m["role"], m["content"]) for m in sent] == [
        ("system", "sistema"),
        ("user", "oi"),
        ("assistant", "Olá."),
        ("user", "e agora?"),
    ]


def test_the_returned_history_is_a_copy():
    loop, _ = make_loop(FlowChat(Turn(chunks=words("a"))))
    loop.ask("oi")

    loop.history[0]["content"] = "mexi"
    loop.history.append({"role": "user", "content": "x"})

    assert loop.history[0]["content"] == "oi" and len(loop.history) == 2


def test_loading_a_history_makes_the_paths_it_mentioned_known_again():
    gate = ToolGate(schemas={})
    loop, _ = make_loop(FlowChat(), gate=gate)

    loop.load_history(
        [
            {"role": "user", "content": "usa o vídeo C:/Videos/viagem.mp4"},
            {"role": "tool", "tool_name": "probe_media", "content": "arquivo C:/Videos/outro.mp4 com 10 s"},
        ]
    )

    assert gate.known_paths.contains("C:/Videos/viagem.mp4") and gate.known_paths.contains(
        "C:/Videos/outro.mp4"
    )
    assert not gate.known_paths.contains("C:/Videos/inventado.mp4")


def test_a_long_conversation_is_trimmed_before_the_call_and_the_screen_is_told():
    chat = FlowChat(Turn(chunks=words("ok")))
    loop, events = make_loop(chat)
    loop.load_history(
        [
            m
            for i in range(8)
            for m in (
                {"role": "user", "content": f"q{i} " + "x" * 3000},
                {"role": "assistant", "content": f"r{i} " + "y" * 3000},
            )
        ]
    )

    loop.ask("pergunta nova", control=TurnControl(num_ctx=4096))

    trimmed = next(data for kind, data in events if kind == "history_trimmed")
    sent = chat.requests[0][0]
    assert trimmed["turns"] >= 6 and "saíram da memória do modelo" in trimmed["text"]
    assert sent[0]["role"] == "system" and sent[-1] == {"role": "user", "content": "pergunta nova"}
    assert len(sent) < 17  # o que o modelo leu é menor que a conversa inteira
    assert len(loop.history) == len(
        sent
    )  # o aparo vale também para o que fica guardado (sem o sistema, com a resposta)


def test_without_a_context_the_history_is_never_trimmed():
    chat = FlowChat(Turn(chunks=words("ok")))
    loop, events = make_loop(chat)
    loop.load_history([{"role": "user", "content": "x" * 50000}, {"role": "assistant", "content": "y"}])

    loop.ask("oi")

    assert "history_trimmed" not in kinds(events) and len(chat.requests[0][0]) == 4


def test_the_density_the_server_measures_makes_the_next_trim_more_careful():
    chat = FlowChat(Turn(chunks=words("a"), prompt_tokens=6000), Turn(chunks=words("b")))
    loop, events = make_loop(chat)
    loop.ask(
        "x" * 6000, control=TurnControl(num_ctx=16384)
    )  # 6000 caracteres que o servidor contou como 6000 tokens

    assert loop._chars_per_token < 3.0  # texto mais denso que o padrão: a próxima conta passa a aparar antes


# ---------- triagem interrompível ----------


def test_the_model_triage_can_be_stopped_when_the_engine_streams():
    chat = FlowChat(Turn(chunks=words("editing"), hang_after=0))
    stopped = threading.Event()
    outcome = []

    def run():
        outcome.append(triage("oi, tudo bem?", chat, should_stop=stopped.is_set))

    worker = threading.Thread(target=run)
    worker.start()
    assert chat.waiting.wait(timeout=5)
    stopped.set()
    chat.abort()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert outcome[0].method == "default"  # parou: nenhum kit veio do modelo


def test_without_a_stop_signal_the_short_call_stays_a_plain_chat():
    chat = OnlyChat(Reply("editing"), Reply("editing"))

    assert reply_stoppable(chat, [], [], None).content == "editing"
    assert triage("oi, tudo bem?", chat).kits == ("editing",)


# ---------- conversa livre ----------


def test_the_free_conversation_offers_no_tools_and_has_a_short_assistant_prompt():
    chat = FlowChat(Turn(chunks=words("Bom dia!")))
    events = []
    session = FreeSession(chat, on_event=lambda kind, data: events.append((kind, data)))

    answer = session.ask("bom dia")

    messages, tools = chat.requests[0]
    assert answer == "Bom dia!" and tools == []
    assert messages[0] == {"role": "system", "content": FREE_SYSTEM_PROMPT}
    assert "triage" not in kinds(events) and session.current_kits == ()
    assert "—" not in FREE_SYSTEM_PROMPT and "–" not in FREE_SYSTEM_PROMPT


def test_a_tool_the_free_model_invents_is_answered_without_running_anything():
    chat = FlowChat(
        Turn(tool_calls=[ToolCall("render_project", {"name_or_path": "x"})]), Turn(chunks=words("Ok."))
    )
    session = FreeSession(chat)

    session.ask("renderiza")

    tool_message = next(m for m in session.history if m["role"] == "tool")
    assert tool_message["content"] == NO_TOOLS_ANSWER


def test_the_free_session_keeps_stops_and_resumes_like_the_other_mode():
    chat = FlowChat(Turn(chunks=words("a")), Turn(chunks=words("b")))
    session = FreeSession(chat)
    session.ask("um")
    saved = session.history

    again = FreeSession(FlowChat(Turn(chunks=words("c"))))
    again.load_history(saved, kits=["ignorado"])
    again.ask("dois")
    session.abort()

    assert [m["content"] for m in again.history] == ["um", "a", "dois", "c"]
    assert chat.aborts == 1 and session.interrupted is False
    session.reset()
    assert session.history == []


def test_confirmation_policy_is_untouched_by_the_flow():
    """O fluxo não pula o portão: uma ferramenta que pede confirmação continua perguntando e respeitando o "não"."""
    asked = []

    class Refuse:
        def confirm(self, request: ConfirmationRequest) -> bool:
            asked.append(request.tool)
            return False

    gate = ToolGate(schemas={}, policy=Refuse())
    chat = FlowChat(
        Turn(tool_calls=[ToolCall("render_project", {"name_or_path": "x"})]),
        Turn(chunks=words("Não renderizei.")),
    )
    host = Host()
    loop, events = make_loop(chat, host, gate=gate)

    loop.ask("renderiza o projeto x", control=TurnControl(should_stop=lambda: False))

    assert asked == ["render_project"] and host.calls == []
    assert "tool_blocked" in kinds(events)
