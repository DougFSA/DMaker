"""Plano dos efeitos sonoros do projeto: os de `audio.sfx` e os que nascem da entrada de sobreposições e transições.

Contas puras sobre a spec e a linha do tempo; achar o arquivo de cada som e misturá-lo fica no pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

from .spec import EntrySound, Project, SoundSpec

# Som padrão de quem liga `sound: true`, por tipo de sobreposição (o `type` da spec) ou "transition".
# Tipo novo (infográfico, composição HTML) entra com uma linha aqui, sem `if`; sem linha, vale o geral.
ENTRY_SOUND_DEFAULTS: dict[str, str] = {
    "text": "pop",
    "image": "pop",
    "video": "whoosh",
    "transition": "whoosh",
}
FALLBACK_ENTRY_SOUND = "pop"


@dataclass(frozen=True)
class SfxItem:
    """Um efeito a tocar: o som (nome da biblioteca ou caminho), o instante e o volume da spec."""

    sound: str
    at: float  # segundos na linha do tempo final
    volume: float
    origin: str  # de onde veio, para as mensagens ("audio.sfx[0]", "overlays[2]", "timeline[3].transition")


def entry_sound(spec: SoundSpec | None, default: str) -> EntrySound | None:
    """Normaliza as três formas do campo `sound` (true, nome, objeto); `None` e `false` não tocam nada."""
    if spec is None or spec is False:
        return None
    if spec is True:
        return EntrySound(sound=default)
    if isinstance(spec, str):
        return EntrySound(sound=spec)
    return spec


def default_entry_sound(kind: str) -> str:
    return ENTRY_SOUND_DEFAULTS.get(kind, FALLBACK_ENTRY_SOUND)


def _entry_item(spec: SoundSpec | None, kind: str, at: float, origin: str) -> SfxItem | None:
    sound = entry_sound(spec, default_entry_sound(kind))
    if sound is None or sound.volume <= 0:
        return None
    return SfxItem(
        sound.sound or default_entry_sound(kind), max(at + sound.offset, 0.0), sound.volume, origin
    )


def plan_sfx(project: Project, spans: list[tuple[float, float]]) -> list[SfxItem]:
    """Todos os efeitos do projeto em ordem de instante: `audio.sfx`, o som de entrada de cada sobreposição
    (no `start` dela) e o de cada transição (no começo dela, que é o começo do trecho que entra, em `spans`).

    Qualquer sobreposição com `start` e `sound` entra, seja do tipo que for: é o ponto de extensão dos tipos
    novos, que só precisam declarar o campo. Efeito sem volume não toca e fica fora do plano.
    """
    items = [
        SfxItem(cue.sound, cue.at, cue.volume, f"audio.sfx[{index}]")
        for index, cue in enumerate(project.audio.sfx)
        if cue.volume > 0
    ]
    for index, overlay in enumerate(project.overlays):
        item = _entry_item(
            getattr(overlay, "sound", None),
            overlay.type,
            getattr(overlay, "start", 0.0),
            f"overlays[{index}]",
        )
        if item:
            items.append(item)
    for index, segment in enumerate(project.timeline):
        if index == 0 or segment.transition is None or index >= len(spans):
            continue  # a transição do primeiro trecho é ignorada: não há trecho anterior
        item = _entry_item(
            segment.transition.sound, "transition", spans[index][0], f"timeline[{index}].transition"
        )
        if item:
            items.append(item)
    return sorted(items, key=lambda item: item.at)
