"""Os efeitos espectrais, a família "Spectral Tools" do Audacity: agem num retângulo do espectrograma, entre dois
instantes (`start`, `end`) e duas frequências (`low_hz`, `high_hz`), para apagar um som pela frequência (um apito, o toque
de um celular, um "plim") sem cortar a fala em volta.

Os quatro valem na spec e no MCP com os mesmos campos que a seleção do painel Áudio preenche. As frequências são em Hz;
uma das duas pode faltar nos efeitos que aceitam uma borda só (a ausente é o fim do espectro). O Apagar Espectral roda no
estágio de amostras (STFT com máscara suavizada, `media/spectral.py`); os outros três são filtros do ffmpeg aplicados ao
trecho, com a emenda de 10 ms de qualquer efeito com intervalo.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import model_validator

from .base import EFFECT_SAMPLE_RATE, EffectBase, param, register_effect

NYQUIST_HZ = EFFECT_SAMPLE_RATE / 2


class SpectralEffect(EffectBase):
    """O que os quatro têm em comum: a faixa de frequência do retângulo. Não é registrado."""

    low_hz: float | None = param(
        None,
        label="Frequência inferior",
        unit="Hz",
        hint="Borda de baixo do retângulo no espectrograma. Vazio: do começo do espectro (0 Hz).",
        ge=0,
        le=NYQUIST_HZ,
    )
    high_hz: float | None = param(
        None,
        label="Frequência superior",
        unit="Hz",
        hint="Borda de cima do retângulo. Vazio: até o fim do espectro (24 kHz).",
        ge=0,
        le=NYQUIST_HZ,
    )

    # os efeitos espectrais são o retângulo da seleção: o menu genérico da interface não os oferece
    needs_selection: ClassVar[bool] = True
    # quantas bordas a seleção precisa ter: 2 exige as duas, 1 aceita uma só
    required_edges: ClassVar[int] = 1

    @model_validator(mode="after")
    def _band(self) -> SpectralEffect:
        edges = [edge for edge in (self.low_hz, self.high_hz) if edge is not None]
        if not edges:
            raise ValueError(f"efeito {self.type}: informe `low_hz` e/ou `high_hz`, a faixa de frequência")
        if self.required_edges == 2 and len(edges) < 2:
            raise ValueError(f"efeito {self.type}: informe `low_hz` e `high_hz`, as duas bordas da faixa")
        if self.low_hz is not None and self.high_hz is not None and self.high_hz <= self.low_hz:
            raise ValueError(
                f"efeito {self.type}: high_hz ({self.high_hz:g}) precisa ser maior que low_hz ({self.low_hz:g})"
            )
        return self

    def edges(self) -> tuple[float, float]:
        """A faixa em Hz, com a borda ausente trocada pelo fim do espectro."""
        return (
            0.0 if self.low_hz is None else self.low_hz,
            NYQUIST_HZ if self.high_hz is None else self.high_hz,
        )


@register_effect
class SpectralDelete(SpectralEffect):
    """Zera a energia dentro do retângulo (tempo e frequência); o som fora dele não muda."""

    type: Literal["spectral_delete"] = "spectral_delete"
    label: ClassVar[str] = "Apagar espectral"
    audacity_name: ClassVar[str] = "Spectral Delete"
    summary: ClassVar[str] = (
        "Apaga o som de uma faixa de frequência num trecho (um apito, um toque de celular) sem cortar o resto."
    )
    owns_interval: ClassVar[bool] = True
    sample_stage: ClassVar[bool] = True

    @model_validator(mode="after")
    def _interval_given(self) -> SpectralDelete:
        if self.start is None or self.end is None:
            raise ValueError("efeito spectral_delete: informe `start` e `end`, o trecho do retângulo")
        return self

    def rebased(self, origin: float, length: float) -> SpectralDelete | None:
        """Como o de todo efeito, mas as pontas do pedaço ficam escritas (0 e `length`): este efeito não aceita
        intervalo aberto."""
        moved = super().rebased(origin, length)
        if moved is None:
            return None
        return moved.model_copy(  # type: ignore[return-value]
            update={
                "start": 0.0 if moved.start is None else moved.start,
                "end": round(length, 6) if moved.end is None else moved.end,
            }
        )


@register_effect
class SpectralMultiTool(SpectralEffect):
    """Escolhe o filtro pela seleção: com as duas bordas, rejeita a banda; só com a de baixo, passa-alta; só com a de
    cima, passa-baixa."""

    type: Literal["spectral_multi_tool"] = "spectral_multi_tool"
    label: ClassVar[str] = "Multiferramenta espectral"
    audacity_name: ClassVar[str] = "Spectral Edit Multi Tool"
    summary: ClassVar[str] = (
        "Rejeita a faixa (as duas bordas), passa-alta (só a de baixo) ou passa-baixa (só a de cima) no trecho."
    )


@register_effect
class SpectralParametricEq(SpectralEffect):
    """Muda em `gain_db` o nível da faixa entre as duas frequências."""

    type: Literal["spectral_eq"] = "spectral_eq"
    label: ClassVar[str] = "EQ paramétrico espectral"
    audacity_name: ClassVar[str] = "Spectral Edit Parametric EQ"
    summary: ClassVar[str] = "Sobe ou desce, em dB, o nível de uma faixa de frequência no trecho."
    required_edges: ClassVar[int] = 2

    gain_db: float = param(
        -20.0, label="Ganho", unit="dB", hint="Negativo corta a faixa, positivo realça.", ge=-60.0, le=30.0
    )


@register_effect
class SpectralShelves(SpectralEffect):
    """Prateleira: o ganho vale acima da borda de baixo, abaixo da de cima, ou entre as duas."""

    type: Literal["spectral_shelves"] = "spectral_shelves"
    label: ClassVar[str] = "Prateleiras espectrais"
    audacity_name: ClassVar[str] = "Spectral Edit Shelves"
    summary: ClassVar[str] = (
        "Aplica um ganho em prateleira: acima da borda de baixo, abaixo da de cima, ou entre as duas bordas."
    )

    gain_db: float = param(
        -20.0, label="Ganho", unit="dB", hint="Negativo corta, positivo realça.", ge=-60.0, le=30.0
    )
