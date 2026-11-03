"""O que a tela vê enquanto o modelo responde: trechos agrupados em poucos eventos e a etapa em que o agente está."""

from __future__ import annotations

from dmaker.agent.flow import DELTA_INTERVAL_S, DeltaBatcher, stage_label


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def collect() -> tuple[list[tuple[str, str]], DeltaBatcher, Clock]:
    sent: list[tuple[str, str]] = []
    clock = Clock()
    return sent, DeltaBatcher(lambda kind, text: sent.append((kind, text)), clock=clock), clock


def test_the_first_piece_goes_out_at_once_and_the_next_ones_wait_for_the_interval():
    sent, batcher, clock = collect()

    batcher.add("answer", "Olá")
    clock.now += 0.05
    batcher.add("answer", ", ")
    clock.now += 0.05
    batcher.add("answer", "mundo")

    assert sent == [("answer", "Olá")]  # o resto ainda está guardado

    clock.now += DELTA_INTERVAL_S
    batcher.add("answer", "!")

    assert sent == [("answer", "Olá"), ("answer", ", mundo!")]


def test_flush_sends_what_is_left_and_is_harmless_when_nothing_is():
    sent, batcher, clock = collect()
    batcher.add("answer", "a")
    clock.now += 0.01
    batcher.add("answer", "b")

    batcher.flush()
    batcher.flush()

    assert sent == [("answer", "a"), ("answer", "b")]


def test_reasoning_and_answer_never_mix_and_keep_their_order():
    sent, batcher, clock = collect()

    batcher.add("thinking", "Vou ")
    clock.now += 0.01
    batcher.add("thinking", "pensar.")
    clock.now += 0.01
    batcher.add("answer", "Resposta")  # a troca de tipo solta o raciocínio guardado antes
    batcher.flush()

    assert sent == [("thinking", "Vou "), ("thinking", "pensar."), ("answer", "Resposta")]


def test_a_flood_of_tiny_pieces_becomes_a_handful_of_events_with_the_same_text():
    sent, batcher, clock = collect()
    text = [f"t{i} " for i in range(1000)]

    for piece in text:
        batcher.add("answer", piece)
        clock.now += 0.01  # 100 trechos por segundo, como um modelo rápido
    batcher.flush()

    assert "".join(part for _, part in sent) == "".join(text)
    assert len(sent) <= 10 * 4 + 2  # 10 s de fluxo viram, no máximo, uns 4 eventos por segundo


def test_stage_labels_say_what_the_agent_is_doing_without_a_dash():
    assert stage_label("loading_model") == "Carregando o modelo"
    assert stage_label("reading") == "Lendo o pedido"
    assert stage_label("thinking") == "Pensando"
    assert stage_label("writing") == "Escrevendo a resposta"
    assert stage_label("tool", "render_project") == "Chamando a ferramenta render_project"
    assert stage_label("tool") == "Chamando uma ferramenta"
    assert all(
        "—" not in stage_label(s) and "–" not in stage_label(s) for s in ("reading", "writing", "tool")
    )
