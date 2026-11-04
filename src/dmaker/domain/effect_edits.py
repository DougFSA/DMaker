"""Edição da cadeia de efeitos de áudio de um item: adicionar, remover, mover, ligar, desligar e mudar os
parâmetros de um efeito. Tudo puro: devolve um Project novo, como o resto de `domain/edits.py`, e levanta
`EditError` em português quando o pedido não faz sentido.

O item vem de um alvo escrito como o caminho dele na spec: `timeline.2` (o som do clipe), `audio.voiceover.0`,
`audio.narration.1`, `audio.music`, `audio.tracks.0`, `overlays.3` (um PiP) e `audio.master` (a mistura inteira).
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from .audio_effects import check_preset_fits, get_effect_preset, parse_effect
from .edits import EditError, _check_index, _clone
from .spec import Project

ACTIONS = ("add", "remove", "move", "enable", "disable", "set", "preset")

# alvos que são uma lista de itens (precisam de um número) e alvos que são um item só
_LISTS = {
    "audio.voiceover": "voz gravada",
    "audio.narration": "narração",
    "audio.tracks": "faixa externa",
    "audio.generated": "som gerado",
}
_SINGLE = {"audio.music": "música", "audio.master": "áudio mestre", "audio.master_effects": "áudio mestre"}


def _indexed(target: str, data: dict) -> tuple[dict, str]:
    """O item da spec (dicionário) e o nome do campo da lista de efeitos dele, para um alvo com número."""
    prefix, _, raw = target.rpartition(".")
    try:
        index = int(raw)
    except ValueError:
        raise EditError(
            f"alvo de efeito inválido: {target!r}. Use timeline.N, overlays.N, audio.voiceover.N, "
            "audio.narration.N, audio.tracks.N, audio.generated.N, audio.music ou audio.master"
        ) from None
    if prefix == "timeline":
        _check_index(len(data["timeline"]), index, "trecho")
        item = data["timeline"][index]
        if item.get("type") != "clip":
            raise EditError(f"timeline.{index}: só o trecho de vídeo (clipe) tem som para receber efeitos")
        return item, "effects"
    if prefix == "overlays":
        _check_index(len(data.get("overlays", [])), index, "sobreposição")
        item = data["overlays"][index]
        if item.get("type") != "video":
            raise EditError(
                f"overlays.{index}: só a sobreposição de vídeo (PiP) tem som para receber efeitos"
            )
        return item, "effects"
    if prefix in _LISTS:
        kind = prefix.split(".")[1]
        _check_index(len(data["audio"].get(kind, [])), index, _LISTS[prefix])
        return data["audio"][kind][index], "effects"
    raise EditError(
        f"alvo de efeito inválido: {target!r}. Use timeline.N, overlays.N, audio.voiceover.N, "
        "audio.narration.N, audio.tracks.N, audio.generated.N, audio.music ou audio.master"
    )


def _effect_list(data: dict, target: str) -> list[dict]:
    """A lista de efeitos (criada vazia se ainda não existe) do item que `target` aponta."""
    if target in _SINGLE:
        if target == "audio.music":
            music = data["audio"].get("music")
            if music is None:
                raise EditError("o projeto não tem música (audio.music) para receber efeitos")
            return music.setdefault("effects", [])
        return data["audio"].setdefault("master_effects", [])
    item, field = _indexed(target, data)
    return item.setdefault(field, [])


def apply_effect_op(project: Project, op: dict[str, Any]) -> Project:
    """Aplica `op` (`{"action": "add", "target": "audio.voiceover.0", "effect": {...}}`) à cadeia de efeitos."""
    action = op.get("action")
    if action not in ACTIONS:
        raise EditError(f"ação de efeito desconhecida: {action!r}. Use uma de: {', '.join(ACTIONS)}")
    target = op.get("target")
    if not isinstance(target, str) or not target:
        raise EditError("informe o `target` do efeito (por exemplo audio.voiceover.0 ou audio.master)")

    def mutate(data: dict) -> None:
        chain = _effect_list(data, target)
        if action == "preset":
            _add_preset(chain, op, target)
            return
        if action == "add":
            effect = _parsed(op.get("effect"))
            position = op.get("index", len(chain))
            if not isinstance(position, int) or not 0 <= position <= len(chain):
                raise EditError(f"posição fora da cadeia: {position!r} (0 a {len(chain)})")
            chain.insert(position, effect)
            return
        index = op.get("index")
        if not isinstance(index, int):
            raise EditError(f"informe o `index` do efeito na cadeia (0 a {len(chain) - 1})")
        _check_index(len(chain), index, "efeito")
        if action == "remove":
            del chain[index]
        elif action == "move":
            to = op.get("to")
            if not isinstance(to, int):
                raise EditError("informe `to`, a nova posição do efeito na cadeia")
            _check_index(len(chain), to, "efeito")
            chain.insert(to, chain.pop(index))
        elif action in ("enable", "disable"):
            chain[index]["enabled"] = action == "enable"
        else:  # set
            params = op.get("params")
            if not isinstance(params, dict) or not params:
                raise EditError('informe `params`, os parâmetros a mudar (por exemplo {"gain_db": 3})')
            chain[index] = _parsed({**chain[index], **params})

    try:
        return _clone(project, mutate)
    except EditError as exc:
        raise EditError(_readable(str(exc))) from exc


def _add_preset(chain: list[dict], op: dict[str, Any], target: str) -> None:
    """Acrescenta à cadeia, um a um, os efeitos da predefinição `op["preset"]` (ver `domain.audio_effects.presets`): cada
    um é um efeito comum, que a pessoa liga, desliga, ajusta ou tira depois. Entram no fim da cadeia, ou em `index`. No áudio
    mestre, a predefinição que tem um efeito de amostras (o Noise Gate) é recusada com o motivo."""
    try:
        preset = get_effect_preset(str(op.get("preset") or ""))
        check_preset_fits(
            preset, target not in _SINGLE or target == "audio.music", _SINGLE.get(target, target)
        )
    except ValueError as exc:
        raise EditError(str(exc)) from exc
    position = op.get("index", len(chain))
    if not isinstance(position, int) or not 0 <= position <= len(chain):
        raise EditError(f"posição fora da cadeia: {position!r} (0 a {len(chain)})")
    for offset, effect in enumerate(preset.effects):
        chain.insert(position + offset, _parsed(dict(effect)))


_VALUE_ERROR = re.compile(r"Value error, (.*?) \[type=value_error", re.DOTALL)


def _readable(message: str) -> str:
    """A recusa da spec sem o ruído do Pydantic: só o que a regra de negócio disse (ex.: onde o Repetir não vale)."""
    reasons = [" ".join(found.split()) for found in _VALUE_ERROR.findall(message)]
    return "; ".join(dict.fromkeys(reasons)) or message


def _parsed(effect: Any) -> dict:
    """O efeito validado e de volta como dicionário (a spec é revalidada inteira depois)."""
    if not isinstance(effect, dict):
        raise EditError('informe o `effect` (por exemplo {"type": "amplify", "gain_db": 6})')
    try:
        return parse_effect(effect).model_dump()
    except (ValidationError, ValueError) as exc:
        raise EditError(str(exc)) from exc
