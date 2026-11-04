"""Os efeitos de volume e dinâmica: Compressor, Limitador, Noise Gate e Normalização de Loudness.

São a família "Volume and Compression" do Audacity, com os nomes e os parâmetros dele (o compressor e o limitador
do 3.6, o Noise Gate e a Normalização de Loudness). Onde a faixa do Audacity passa da do filtro do ffmpeg que faz o
trabalho, o catálogo usa a do filtro e a tabela do manual diz o limite (razão acima de 20:1: use o Limitador).
O comportamento é reproduzido pelo ffmpeg (compressor, limitador, ganho da normalização) e por contas em numpy (o
Noise Gate, que precisa de segurar e de abrir antes da palavra) em `filtergraph.audio_effects.dynamics`, não copiado
do código do Audacity.

O Auto Duck desta família não é um efeito: ele abaixa uma trilha sob OUTRA, então depende de duas trilhas e fica em
`audio.ducks` (`domain/auto_duck.py`).
"""

from __future__ import annotations

from typing import ClassVar, Literal

from .base import EffectAction, EffectBase, param, register_effect

LOUDNESS_MODES = ("lufs", "rms")


@register_effect
class Compressor(EffectBase):
    """Reduz a diferença entre o som forte e o fraco: o que passa do limiar é comprimido pela razão. Detecta o nível um
    pouco antes de ele chegar (lookahead), então o compressor já está atuando quando o pico passa."""

    type: Literal["compressor"] = "compressor"
    label: ClassVar[str] = "Compressor"
    audacity_name: ClassVar[str] = "Compressor"
    summary: ClassVar[str] = (
        "Comprime o que passa do limiar pela razão, para a fala ficar mais pareada; o ganho de compensação "
        "devolve o volume que a compressão tirou."
    )

    threshold_db: float = param(
        -10.0,
        label="Limiar",
        unit="dB",
        hint="Nível a partir do qual o som é comprimido.",
        ge=-60.0,
        le=0.0,
    )
    ratio: float = param(
        10.0,
        label="Razão",
        unit=":1",
        hint="Quanto o que passa do limiar é comprimido: 4 deixa 4 dB acima virar 1 dB. Acima de 20:1 "
        "use o Limitador.",
        ge=1.0,
        le=20.0,
    )
    knee_db: float = param(
        5.0,
        label="Joelho",
        unit="dB",
        hint="Largura da transição em volta do limiar: 0 comprime de uma vez; mais largo, a compressão entra "
        "aos poucos.",
        ge=0.0,
        le=18.0,
    )
    attack_ms: float = param(
        30.0,
        label="Ataque",
        unit="ms",
        hint="Tempo que o compressor leva para agir depois de o som passar do limiar.",
        ge=0.1,
        le=2000.0,
    )
    release_ms: float = param(
        150.0,
        label="Liberação",
        unit="ms",
        hint="Tempo que o compressor leva para soltar depois de o som voltar abaixo do limiar.",
        ge=1.0,
        le=9000.0,
    )
    makeup_db: float = param(
        0.0,
        label="Ganho de compensação",
        unit="dB",
        hint="Sobe o som depois de comprimir, para devolver o volume que a compressão tirou.",
        ge=0.0,
        le=36.0,
    )
    lookahead_ms: float = param(
        1.0,
        label="Lookahead",
        unit="ms",
        hint="Quanto antes o compressor enxerga o pico. A latência é compensada: o som não anda.",
        ge=0.0,
        le=200.0,
    )


@register_effect
class Limiter(EffectBase):
    """Segura os picos num teto: nada passa do teto em dBTP (pico verdadeiro, medido com sobreamostragem). O tipo
    suave começa a abaixar o som alguns dB antes do teto; o rígido corta os picos que passam dele."""

    type: Literal["limiter"] = "limiter"
    label: ClassVar[str] = "Limitador"
    audacity_name: ClassVar[str] = "Limiter"
    summary: ClassVar[str] = (
        "Segura os picos num teto em dBTP (pico verdadeiro). Use no fim da cadeia para o som não estourar."
    )

    limit_type: Literal["hard", "soft"] = param(
        "hard",
        label="Tipo",
        hint="hard (rígido): só o limitador, que segura os picos no teto. soft (suave): antes dele, um "
        "compressor de razão alta começa a abaixar o som uns 4 dB antes do teto.",
    )
    ceiling_db: float = param(
        -1.0,
        label="Teto",
        unit="dBTP",
        hint="O pico verdadeiro máximo da saída.",
        ge=-24.0,
        le=0.0,
    )
    input_gain_db: float = param(
        0.0,
        label="Ganho de entrada",
        unit="dB",
        hint="Sobe o som antes do limitador: o que passa do teto é segurado, então o som fica mais alto.",
        ge=0.0,
        le=36.0,
    )
    lookahead_ms: float = param(
        5.0,
        label="Lookahead",
        unit="ms",
        hint="Quanto antes o limitador enxerga o pico. Mais tempo, transição mais suave. A latência é "
        "compensada: o som não anda.",
        ge=0.1,
        le=80.0,
    )
    release_ms: float = param(
        50.0,
        label="Liberação",
        unit="ms",
        hint="Tempo que o limitador leva para soltar depois de um pico.",
        ge=1.0,
        le=8000.0,
    )


@register_effect
class NoiseGate(EffectBase):
    """Fecha o som quando ele fica abaixo do limiar (o chiado entre as frases) e o abre antes da palavra chegar: o
    ataque olha à frente, então o começo da palavra passa inteiro. O que fica fechado só é abaixado pela redução, não
    some."""

    type: Literal["noise_gate"] = "noise_gate"
    label: ClassVar[str] = "Noise Gate"
    audacity_name: ClassVar[str] = "Noise Gate"
    summary: ClassVar[str] = (
        "Abaixa o som quando ele fica abaixo do limiar (o chiado entre as frases) e o abre antes da palavra "
        "começar. Use Analisar ruído para sugerir o limiar."
    )
    sample_stage: ClassVar[bool] = True
    actions: ClassVar[tuple[EffectAction, ...]] = (
        EffectAction(
            id="analyze_noise",
            label="Analisar ruído",
            hint="Mede o ruído de um trecho em que ninguém fala (um perfil de ruído do projeto, ou o trecho mais "
            "quieto do item) e sugere o limiar: o nível do ruído mais 6 dB.",
            fills=("threshold_db",),
        ),
    )

    threshold_db: float = param(
        -40.0,
        label="Limiar",
        unit="dB",
        hint="Abaixo deste nível o gate fecha. Ponha uns 6 dB acima do ruído (Analisar ruído sugere o valor).",
        ge=-96.0,
        le=-6.0,
    )
    reduction_db: float = param(
        24.0,
        label="Redução",
        unit="dB",
        hint="Quanto o som cai quando o gate está fechado. Não precisa ir a zero: 12 a 24 dB soa mais natural.",
        ge=0.0,
        le=100.0,
    )
    attack_ms: float = param(
        10.0,
        label="Ataque",
        unit="ms",
        hint="Quanto tempo o gate leva para abrir. Ele começa a abrir esse tempo ANTES do som passar do "
        "limiar, então o começo da palavra não é cortado.",
        ge=1.0,
        le=1000.0,
    )
    hold_ms: float = param(
        50.0,
        label="Segurar",
        unit="ms",
        hint="Quanto tempo o gate fica aberto depois de o som cair abaixo do limiar (evita picotar as pausas "
        "curtas dentro de uma frase).",
        ge=0.0,
        le=5000.0,
    )
    release_ms: float = param(
        100.0,
        label="Liberação",
        unit="ms",
        hint="Quanto tempo o gate leva para fechar depois do tempo de segurar.",
        ge=10.0,
        le=4000.0,
    )
    stereo_link: bool = param(
        True,
        label="Canais ligados",
        hint="Os dois canais abrem e fecham juntos (pelo mais alto). Desligado, cada canal tem o seu gate.",
    )


@register_effect
class LoudnessNormalize(EffectBase):
    """Leva o item a um loudness alvo com um ganho linear único: o LUFS integrado (o que a TV e as plataformas medem)
    ou o RMS. Serve para igualar duas falas antes da mixagem. Não limita o pico, como no Audacity: se o ganho for alto,
    ponha o Limitador depois."""

    type: Literal["loudness_normalize"] = "loudness_normalize"
    label: ClassVar[str] = "Normalização de loudness"
    audacity_name: ClassVar[str] = "Loudness Normalization"
    summary: ClassVar[str] = (
        "Leva o item a um loudness alvo (LUFS integrado ou RMS) com um ganho único, para igualar falas antes "
        "da mixagem. Não limita o pico: ponha o Limitador depois."
    )

    mode: Literal["lufs", "rms"] = param(
        "lufs",
        label="Modo",
        hint="lufs: loudness percebido integrado (ITU-R BS.1770); rms: nível médio da mistura dos canais.",
    )
    target_db: float = param(
        -23.0,
        label="Alvo",
        unit="LUFS ou dB",
        hint="O loudness (modo lufs) ou o RMS (modo rms) que o item deve ter. O padrão do Audacity é -23 LUFS "
        "(e -20 dB no modo rms).",
        ge=-70.0,
        le=0.0,
    )
    dual_mono: bool = param(
        True,
        label="Tratar mono como dual-mono",
        hint="Ligado (padrão do Audacity): um arquivo mono conta como o mesmo som nos dois lados, que é como ele "
        "toca na mistura. Desligado, o mono mede 3 LU abaixo e o ganho sobe 3 dB. Só muda para arquivo mono.",
    )

    def needs_measure(self) -> bool:
        return True

    def measure_kind(self) -> str:
        return self.mode
