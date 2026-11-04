"""As predefinições de efeitos que a pessoa salva por nome, num arquivo da pasta de dados (`config.EFFECT_PRESETS_FILE`).

Uma predefinição do usuário é uma cadeia de efeitos já ajustada (um só, no caso de salvar o cartão de um efeito, ou vários).
Aparece no catálogo ao lado das embutidas, com `origin: "user"`, e se aplica pelo mesmo `audio_effect` com `action: "preset"`.
O arquivo é lido a cada uso, nunca guardado em memória: reiniciar o programa, ou editar o arquivo à mão, vale na hora.
Salvar de novo com o mesmo nome troca a predefinição. O intervalo (`start`/`end`) e o bypass (`enabled`) não entram: pertencem ao
item em que o efeito estava, e a predefinição vai para outro.
"""

from __future__ import annotations

import json
import os
import re
import threading
import unicodedata
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from ... import config
from .base import EffectBase
from .presets import EFFECT_PRESETS, EffectPreset

USER_ORIGIN = "user"
# O que pertence ao lugar do efeito e não vai para a predefinição
_PLACEMENT_FIELDS = {"start", "end", "enabled"}
MAX_PRESET_EFFECTS = 20
MAX_LABEL_LENGTH = 60

_LOCK = threading.Lock()


def preset_id(label: str) -> str:
    """O id de uma predefinição a partir do nome: minúsculas, sem acento, só letras, números e hífen."""
    plain = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")


def _read() -> dict[str, dict[str, Any]]:
    """O conteúdo do arquivo, `{id: {label, summary, effects}}`. Sem arquivo é vazio; arquivo ilegível é erro com o motivo,
    para salvar não apagar sem querer o que a pessoa tinha."""
    path = config.EFFECT_PRESETS_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError) as exc:
        raise ValueError(f"não consegui ler as predefinições salvas em {path.name}: {exc}") from exc
    presets = data.get("presets") if isinstance(data, dict) else None
    return presets if isinstance(presets, dict) else {}


def _write(presets: dict[str, dict[str, Any]]) -> None:
    """Grava por inteiro e troca o arquivo de uma vez, para uma queda no meio não deixar meia predefinição."""
    path = config.EFFECT_PRESETS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + ".tmp")
    pending.write_text(
        json.dumps({"version": 1, "presets": presets}, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(pending, path)


def _as_preset(identifier: str, entry: dict[str, Any]) -> EffectPreset:
    return EffectPreset(
        id=identifier,
        label=str(entry.get("label") or identifier),
        summary=str(entry.get("summary") or ""),
        effects=tuple(dict(effect) for effect in entry.get("effects", ())),
        origin=USER_ORIGIN,
    )


def list_user_presets() -> list[EffectPreset]:
    """As predefinições salvas, por ordem de nome. Arquivo ilegível levanta `ValueError` (quem lista para o catálogo usa
    `load_user_presets`, que prefere devolver só as embutidas a derrubar o painel)."""
    with _LOCK:
        entries = _read()
    return [_as_preset(identifier, entries[identifier]) for identifier in sorted(entries)]


def load_user_presets() -> list[EffectPreset]:
    """Como `list_user_presets`, mas um arquivo ilegível vira lista vazia: o catálogo dos efeitos nunca fica fora do ar por
    causa de um arquivo que a pessoa estragou à mão."""
    try:
        return list_user_presets()
    except ValueError:
        return []


def _clean_effect(raw: Any) -> dict[str, Any]:
    """O efeito validado, sem o que é do lugar onde estava (intervalo e bypass)."""
    from . import parse_effect

    if not isinstance(raw, dict):
        raise ValueError(
            'cada efeito da predefinição é um objeto, por exemplo {"type": "highpass", "frequency_hz": 80}'
        )
    try:
        effect = parse_effect({key: value for key, value in raw.items() if key not in _PLACEMENT_FIELDS})
    except (ValidationError, ValueError) as exc:
        raise ValueError(f"efeito inválido na predefinição: {exc}") from exc
    return _dump(effect)


def _dump(effect: EffectBase) -> dict[str, Any]:
    return effect.model_dump(mode="json", exclude=_PLACEMENT_FIELDS)


def save_user_preset(label: str, effects: Sequence[dict], summary: str = "") -> EffectPreset:
    """Salva (ou troca) a predefinição de nome `label` com esses efeitos. O nome não pode ser vazio, nem o de uma
    predefinição embutida; cada efeito é validado como na spec."""
    name = " ".join(str(label).split())
    identifier = preset_id(name)
    if not identifier:
        raise ValueError("dê um nome à predefinição (letras ou números)")
    if len(name) > MAX_LABEL_LENGTH:
        raise ValueError(f"nome da predefinição longo demais (no máximo {MAX_LABEL_LENGTH} caracteres)")
    if identifier in EFFECT_PRESETS:
        raise ValueError(
            f"{name!r} é o nome de uma predefinição embutida ({EFFECT_PRESETS[identifier].label}); escolha outro nome"
        )
    if not 1 <= len(effects) <= MAX_PRESET_EFFECTS:
        raise ValueError(f"a predefinição precisa de 1 a {MAX_PRESET_EFFECTS} efeitos")
    cleaned = [_clean_effect(effect) for effect in effects]
    entry = {"label": name, "summary": " ".join(str(summary).split()), "effects": cleaned}
    with _LOCK:
        presets = _read()
        presets[identifier] = entry
        _write(presets)
    return _as_preset(identifier, entry)


def remove_user_preset(identifier: str) -> EffectPreset:
    """Tira a predefinição salva de `id` dado e a devolve. Uma embutida não se remove; uma que não existe é erro."""
    if identifier in EFFECT_PRESETS:
        raise ValueError(f"{identifier!r} é uma predefinição embutida e não pode ser removida")
    with _LOCK:
        presets = _read()
        if identifier not in presets:
            known = ", ".join(sorted(presets)) or "nenhuma salva"
            raise ValueError(f"Predefinição salva desconhecida: {identifier!r}. Salvas: {known}")
        entry = presets.pop(identifier)
        _write(presets)
    return _as_preset(identifier, entry)
