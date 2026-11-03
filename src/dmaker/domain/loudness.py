"""Alvos de loudness da saída: os valores usuais para escolher pelo nome em vez de lembrar o número.

O alvo é o `audio.target_lufs` do projeto (a normalização do master, `loudnorm`); aqui ficam só os nomes dos
três valores que a prática pede e a leitura de um alvo escrito como nome ou como número.
"""

from __future__ import annotations

# nome -> LUFS integrado. -14 é o de plataformas de vídeo e música em fluxo; -16 o de podcast; -23 o de TV
# (EBU R128, o padrão de broadcast da Europa e do Brasil).
LOUDNESS_TARGETS: dict[str, float] = {"redes": -14.0, "podcast": -16.0, "broadcast": -23.0}

LOUDNESS_ALIASES: dict[str, str] = {
    "streaming": "redes",
    "social": "redes",
    "ebu": "broadcast",
    "r128": "broadcast",
    "tv": "broadcast",
}

# o intervalo que a spec aceita em `audio.target_lufs` (ver `AudioSettings`)
TARGET_LUFS_RANGE = (-30.0, -5.0)


def parse_loudness_target(value: str | float | int) -> float:
    """O alvo em LUFS a partir de um nome (`podcast`), de um número (`-16`) ou do número escrito (`"-16"`)."""
    if isinstance(value, bool):
        raise ValueError(f"alvo de loudness inválido: {value!r}")
    if isinstance(value, int | float):
        number = float(value)
    else:
        text = value.strip().lower().replace(",", ".").removesuffix("lufs").strip()
        text = LOUDNESS_ALIASES.get(text, text)
        if text in LOUDNESS_TARGETS:
            return LOUDNESS_TARGETS[text]
        try:
            number = float(text)
        except ValueError as exc:
            names = ", ".join(f"{name} ({lufs:g})" for name, lufs in LOUDNESS_TARGETS.items())
            raise ValueError(
                f"alvo de loudness desconhecido: {value!r}. Use um nome ({names}) ou um número"
            ) from exc
    low, high = TARGET_LUFS_RANGE
    if not low <= number <= high:
        raise ValueError(f"o alvo de loudness vai de {low:g} a {high:g} LUFS, veio {number:g}")
    return number
