"""Encadeamento das partes de uma fonte (`pipeline/partsync.py`): função pura, testada com um
`LinkFinder` fake (nenhum arquivo real é lido nem o ffmpeg é chamado)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmaker.media.audiosync import SyncResult
from dmaker.pipeline.partsync import CLOCK_TOLERANCE_S, PartInfo, chain_parts


def _path(name: str) -> Path:
    return Path(name)


def _fake_links(true_positions: dict[str, float], reliable: set[frozenset[str]], confidence: float = 9.0):
    """Liga `a` a `b` com o deslocamento verdadeiro quando o par está em `reliable` (como uma
    correlação cega que encontrou o trecho certo) ou quando `expected` foi informado a menos de
    `CLOCK_TOLERANCE_S` do deslocamento verdadeiro (como a correlação guiada faria); senão, devolve
    um resultado de baixa confiança."""

    def find(a: Path, b: Path, expected: float | None = None) -> SyncResult:
        fallback = SyncResult(expected if expected is not None else 0.0, 1.0)
        if a.name not in true_positions or b.name not in true_positions:
            return fallback
        true_offset = true_positions[b.name] - true_positions[a.name]
        if frozenset((a.name, b.name)) in reliable:
            return SyncResult(true_offset, confidence)
        if expected is not None and abs(expected - true_offset) <= CLOCK_TOLERANCE_S:
            return SyncResult(true_offset, confidence)
        return fallback

    return find


def test_chain_links_all_parts_by_audio_across_two_cameras():
    """3 partes da câmera principal + 2 de uma secundária, todas ligadas em cadeia pelo áudio."""
    true_positions = {"a0": 0.0, "a1": 100.0, "a2": 200.0, "b0": 20.0, "b1": 140.0}
    parts = {
        "camA": [PartInfo(_path("a0"), 100.0), PartInfo(_path("a1"), 100.0), PartInfo(_path("a2"), 50.0)],
        "camB": [PartInfo(_path("b0"), 80.0), PartInfo(_path("b1"), 80.0)],
    }
    reliable = {frozenset(p) for p in (("a0", "b0"), ("b0", "a1"), ("a1", "b1"), ("b1", "a2"))}
    links = _fake_links(true_positions, reliable)

    positions, warnings = chain_parts(parts, links, master="camA")

    assert positions == {"camA": [0.0, 100.0, 200.0], "camB": [20.0, 140.0]}
    assert warnings == []


def test_part_without_reliable_link_falls_back_to_clock():
    """Sem nenhum link de áudio confiável para a segunda parte, ela é posicionada pelo relógio de
    gravação (início do arquivo, hipótese padrão), com um aviso por parte e um resumo por fonte."""
    parts = {
        "camA": [
            PartInfo(_path("a0"), 100.0, clock=1000.0),
            PartInfo(_path("a1"), 100.0, clock=1105.0),  # 5s de intervalo real entre as gravações
        ],
        "camB": [PartInfo(_path("b0"), 200.0)],
    }
    reliable = {frozenset(("a0", "b0"))}  # liga a principal à secundária; a1 fica sem link nenhum
    links = _fake_links({"a0": 0.0, "b0": 50.0}, reliable)

    positions, warnings = chain_parts(parts, links, master="camA")

    assert positions["camA"] == pytest.approx([0.0, 105.0])
    assert positions["camB"] == pytest.approx([50.0])
    assert len(warnings) == 2
    assert "camA: parte 2 de 2 posicionada pelo relógio" in warnings[0]
    assert "camA: 1 de 2 parte(s) sem link de áudio confiável" in warnings[1]


def test_clock_end_of_recording_is_detected_and_applied():
    """Quando o `creation_time` marca o FIM da gravação (não o início), a votação por um par já
    ligado por áudio detecta isso e aplica a mesma hipótese à parte sem link."""
    parts = {
        "camA": [
            PartInfo(_path("a0"), 100.0, clock=5100.0),  # fim da gravação: 5000 (base) + 100
            PartInfo(_path("a1"), 80.0, clock=5180.0),  # encostada em a0 (fim = 5100 + 80)
            PartInfo(_path("a2"), 60.0, clock=5245.0),  # 5s de pausa antes de gravar de novo
        ],
        "camB": [PartInfo(_path("b0"), 40.0)],
    }
    true_positions = {"a0": 0.0, "b0": 20.0, "a1": 100.0}
    reliable = {frozenset(("a0", "b0")), frozenset(("b0", "a1"))}  # a2 fica sem link de áudio
    links = _fake_links(true_positions, reliable)

    positions, warnings = chain_parts(parts, links, master="camA")

    assert positions["camA"] == pytest.approx([0.0, 100.0, 185.0])
    assert len(warnings) == 2
    assert "camA: parte 3 de 3 posicionada pelo relógio" in warnings[0]
    assert "camA: 1 de 3 parte(s) sem link de áudio confiável" in warnings[1]


def test_reliable_link_incompatible_with_clock_is_rejected():
    """Um link de áudio "confiável" mas que discorda muito do relógio de gravação (câmera errada,
    trecho parecido por coincidência) é descartado; a parte cai para o relógio de gravação."""
    parts = {
        "camA": [
            PartInfo(_path("a0"), 100.0, clock=1000.0),
            PartInfo(_path("a1"), 100.0, clock=1105.0),  # relógio prevê ~105s (gap de 5s)
        ],
        "camB": [PartInfo(_path("b0"), 50.0, clock=1050.0)],  # relógio consistente com o de camA
    }

    def links(a: Path, b: Path, expected: float | None = None) -> SyncResult:
        if frozenset((a.name, b.name)) == frozenset(("a0", "b0")):
            return SyncResult(50.0, 9.0)  # b0 em 0 + 50 = 50, e bate com o relógio (1050 - 1000 = 50)
        if frozenset((a.name, b.name)) == frozenset(("b0", "a1")):
            return SyncResult(500.0, 9.0)  # "confiável", mas poria a1 em 550s: o relógio prevê ~105s
        return SyncResult(0.0, 1.0)

    positions, warnings = chain_parts(parts, links, master="camA")

    assert positions["camB"] == pytest.approx([50.0])
    assert positions["camA"] == pytest.approx([0.0, 105.0])  # caiu para o relógio, não para os 550s
    assert len(warnings) == 2
    assert "posicionada pelo relógio" in warnings[0]
    assert "camA: 1 de 2 parte(s) sem link de áudio confiável" in warnings[1]


def test_link_is_kept_when_one_camera_stamps_the_end_of_the_recording():
    """O celular grava em `creation_time` o FIM da gravação e a Canon o início: um link de áudio
    correto entre os dois discorda do relógio pela duração inteira do arquivo, e mesmo assim tem
    que ser aceito (a hipótese "fim" vale para cada lado)."""
    parts = {
        "canon": [PartInfo(_path("c0"), 1800.0, clock=10_000.0)],  # início: 10000
        "phone": [PartInfo(_path("p0"), 1200.0, clock=10_000.0 + 300.0 + 1200.0)],  # fim: começou em 10300
    }
    links = _fake_links({"c0": 0.0, "p0": 300.0}, {frozenset(("c0", "p0"))})

    positions, warnings = chain_parts(parts, links, master="canon")

    assert positions["phone"] == pytest.approx([300.0])
    assert warnings == []


def test_seed_fixes_the_first_part_of_a_non_master_source():
    """`seed` fixa a parte 0 de uma fonte com `sync` numérico: ela não precisa de link nenhum."""
    parts = {
        "camA": [PartInfo(_path("a0"), 100.0)],
        "camB": [PartInfo(_path("b0"), 50.0), PartInfo(_path("b1"), 50.0)],
    }
    reliable = {frozenset(("b0", "b1"))}
    # partes da mesma fonte não têm áudio em comum: mesmo com um link "confiável" entre b0 e b1,
    # ele nunca é considerado (a busca pula referências da própria fonte)
    links = _fake_links({"b0": 30.0, "b1": 900.0}, reliable)

    positions, warnings = chain_parts(parts, links, master="camA", seed={"camB": 30.0})

    assert positions["camB"][0] == 30.0
    # b1 não tem link possível (única outra parte é da própria fonte) nem relógio: encosta no fim de b0
    assert positions["camB"][1] == pytest.approx(80.0)
    assert any("sem link de áudio nem relógio" in w for w in warnings)
    assert any("camB: 1 de 2 parte(s) sem link de áudio confiável" in w for w in warnings)


def test_guided_link_recovers_when_blind_correlation_fails():
    """A correlação cega não acha esse par (nenhum link "confiável" no fake, como um par de
    arquivos longos com pouca sobreposição em comum); a guiada, sabendo o deslocamento que o
    relógio de gravação prevê, acha o link mesmo assim."""
    parts = {
        "camA": [PartInfo(_path("a0"), 1800.0, clock=10_000.0)],
        "camB": [PartInfo(_path("b0"), 1200.0, clock=10_090.0)],  # relógio prevê ~90s de deslocamento
    }
    links = _fake_links({"a0": 0.0, "b0": 90.0}, reliable=set())

    positions, warnings = chain_parts(parts, links, master="camA")

    assert positions["camB"] == pytest.approx([90.0])
    assert warnings == []


def test_guided_pass_uses_per_source_clock_hypothesis():
    """Canon marca o início da gravação no `creation_time`, celular marca o fim (como no caso
    real): a rodada cega liga o primeiro par de cada fonte, o que basta para votar a hipótese de
    relógio de cada uma; a guiada usa essas hipóteses, diferentes por fonte, para prever o
    deslocamento das partes seguintes e ligá-las, mesmo sem nenhum link cego para elas. `c1` só tem
    sobreposição real com `p0` (que já entrou por áudio), e `p1` só com `c1`, então a cadeia
    guiada precisa avançar em duas rodadas dentro do mesmo passe."""
    parts = {
        "canon": [
            PartInfo(_path("c0"), 1800.0, clock=10_000.0),  # início: 10000, cobre a sessão [0, 1800]
            PartInfo(_path("c1"), 1800.0, clock=11_850.0),  # início: 11850, cobre [1850, 3650]
        ],
        "phone": [
            PartInfo(_path("p0"), 2000.0, clock=12_300.0),  # fim: começou em 10300, cobre [300, 2300]
            PartInfo(_path("p1"), 600.0, clock=14_200.0),  # fim: começou em 13600, cobre [3600, 4200]
        ],
    }
    true_positions = {"c0": 0.0, "c1": 1850.0, "p0": 300.0, "p1": 3600.0}
    reliable = {frozenset(("c0", "p0"))}  # só esse par cego: basta para calibrar as duas hipóteses
    links = _fake_links(true_positions, reliable)

    positions, warnings = chain_parts(parts, links, master="canon")

    assert positions["canon"] == pytest.approx([0.0, 1850.0])
    assert positions["phone"] == pytest.approx([300.0, 3600.0])
    assert warnings == []


def test_part_with_no_predicted_overlap_falls_back_to_clock_with_summary_warning():
    """Uma parte cujo relógio de gravação não prevê sobreposição com nenhuma outra fonte nunca é
    sequer tentada por áudio (nem cega nem guiada, mesmo que o fake "acertasse" se fosse chamado);
    cai para o relógio, com aviso por parte e o resumo por fonte."""
    parts = {
        "camA": [PartInfo(_path("a0"), 100.0, clock=1000.0)],
        "camB": [PartInfo(_path("b0"), 100.0, clock=1_000_000.0)],  # muito distante no tempo: sem overlap
    }
    links = _fake_links({"a0": 0.0, "b0": 999_000.0}, reliable=set())

    positions, warnings = chain_parts(parts, links, master="camA")

    assert positions["camB"] == pytest.approx([0.0])  # sem posição anterior: encosta em 0s
    assert len(warnings) == 2
    assert "camB: parte 1 de 1 sem posição anterior" in warnings[0]
    assert "camB: 1 de 1 parte(s) sem link de áudio confiável" in warnings[1]
