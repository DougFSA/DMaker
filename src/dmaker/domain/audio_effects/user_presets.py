"""As macros de áudio que a pessoa salva por nome: um JSON por macro, numa pasta global ou na pasta de uma marca.

Uma macro é uma cadeia de efeitos já ajustada (um só, no caso de salvar o cartão de um efeito, ou vários) e, se quiser, a
saída (formato do arquivo e codificação) que vale ao aplicá-la a uma pasta de arquivos. Aparece no catálogo ao lado das
embutidas, com `origin: "user"`, e se aplica a um item pelo mesmo `audio_effect` com `action: "preset"`.

As pastas são `config.MACROS_DIR` (global) e `config.BRAND_DATA_DIR/<marca>/macros` (da marca): dado de quem usa o editor,
fora do git, lidas a cada uso, nunca guardadas em memória (editar um arquivo à mão, ou reiniciar o programa, vale na hora).
Quando uma marca tem uma macro de mesmo id que uma global, a da marca vale. Salvar de novo com o mesmo nome troca a macro.
O intervalo (`start`/`end`) e o bypass (`enabled`) não entram: pertencem ao item em que o efeito estava, e a macro vai
para outro.

Migração (DMK-66): as predefinições do usuário do DMK-54 moravam num arquivo só, `config.EFFECT_PRESETS_FILE`. No primeiro
acesso, cada entrada dele vira uma macro global (sem sobrescrever uma macro de mesmo id que já exista) e o arquivo é
renomeado para `effect-presets.json.importado`, nunca apagado: a pessoa pode desfazer a migração devolvendo o nome.
"""

from __future__ import annotations

import json
import os
import re
import threading
import unicodedata
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ... import config
from .base import EffectBase
from .macro_output import clean_output
from .presets import EFFECT_PRESETS, EffectPreset

USER_ORIGIN = "user"
GLOBAL_SCOPE = "global"
BRAND_SCOPE_PREFIX = "brand:"
FORMAT_VERSION = 1
MIGRATED_SUFFIX = ".importado"
# O que pertence ao lugar do efeito e não vai para a macro
_PLACEMENT_FIELDS = {"start", "end", "enabled"}
MAX_PRESET_EFFECTS = 20
MAX_LABEL_LENGTH = 60
_BRAND_NAME = re.compile(r"^[A-Za-z0-9][\w-]*$")  # nome de pasta: barra "..", "/" e afins

_LOCK = threading.RLock()


def preset_id(label: str) -> str:
    """O id de uma macro a partir do nome: minúsculas, sem acento, só letras, números e hífen."""
    plain = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")


def macros_dir(brand: str | None = None) -> Path:
    """A pasta das macros globais (`brand=None`) ou das da marca. Lida do `config` na hora do uso."""
    if brand is None:
        return config.MACROS_DIR
    if not _BRAND_NAME.match(brand):
        raise ValueError(f"Nome de marca inválido: {brand!r}.")
    return config.BRAND_DATA_DIR / brand / "macros"


def scope_label(brand: str | None) -> str:
    return GLOBAL_SCOPE if brand is None else f"{BRAND_SCOPE_PREFIX}{brand}"


# ---------- migração do arquivo do DMK-54 ----------


def _migrated_name(legacy: Path) -> Path:
    """`effect-presets.json.importado`, ou com um número quando já existe um (a migração nunca sobrescreve)."""
    candidate = legacy.with_name(legacy.name + MIGRATED_SUFFIX)
    number = 2
    while candidate.exists():
        candidate = legacy.with_name(f"{legacy.name}{MIGRATED_SUFFIX}.{number}")
        number += 1
    return candidate


def migrate_legacy_presets() -> list[str]:
    """Passa as predefinições do arquivo antigo para a pasta de macros globais e devolve os ids importados.

    Idempotente e à prova de queda: as macros são gravadas antes de o arquivo ser renomeado, e uma macro que já existe
    não é sobrescrita, então repetir depois de uma queda no meio termina o trabalho sem perder edição. Um arquivo que
    não dá para ler fica onde está (a pessoa o conserta à mão) e não derruba nada."""
    legacy = config.EFFECT_PRESETS_FILE
    with _LOCK:
        if not legacy.is_file():
            return []
        try:
            data = json.loads(legacy.read_text(encoding="utf-8") or "{}")
        except (OSError, ValueError):
            return []
        entries = data.get("presets") if isinstance(data, dict) else None
        entries = entries if isinstance(entries, dict) else {}
        folder = macros_dir()
        imported: list[str] = []
        for raw_identifier, entry in sorted(entries.items()):
            identifier = preset_id(str(raw_identifier))
            if not isinstance(entry, dict) or not identifier or (folder / f"{identifier}.json").exists():
                continue
            _write_macro(
                folder,
                identifier,
                {
                    "label": str(entry.get("label") or identifier),
                    "summary": str(entry.get("summary") or ""),
                    "effects": [
                        dict(effect) for effect in entry.get("effects", ()) if isinstance(effect, dict)
                    ],
                },
            )
            imported.append(identifier)
        try:
            os.replace(legacy, _migrated_name(legacy))
        except FileNotFoundError:  # outro processo terminou a migração primeiro
            pass
        return imported


# ---------- leitura e gravação ----------


def _write_macro(folder: Path, identifier: str, entry: dict[str, Any]) -> None:
    """Grava por inteiro e troca o arquivo de uma vez, para uma queda no meio não deixar meia macro."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{identifier}.json"
    pending = path.with_name(path.name + ".tmp")
    pending.write_text(
        json.dumps({"version": FORMAT_VERSION, **entry}, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(pending, path)


def _as_preset(identifier: str, entry: dict[str, Any], brand: str | None) -> EffectPreset:
    output = entry.get("output")
    return EffectPreset(
        id=identifier,
        label=str(entry.get("label") or identifier),
        summary=str(entry.get("summary") or ""),
        effects=tuple(dict(effect) for effect in entry.get("effects", ())),
        origin=USER_ORIGIN,
        output=dict(output) if isinstance(output, dict) and output else None,
        scope=scope_label(brand),
    )


def _read_folder(folder: Path, brand: str | None, *, strict: bool) -> dict[str, EffectPreset]:
    """As macros de uma pasta pelo id (o nome do arquivo). Um arquivo ilegível é erro com o motivo no modo estrito
    (listar e salvar não escondem o que a pessoa estragou à mão) e é pulado no tolerante (o catálogo dos efeitos nunca
    fica fora do ar por causa de um arquivo)."""
    found: dict[str, EffectPreset] = {}
    if not folder.is_dir():
        return found
    for path in sorted(folder.glob("*.json")):
        try:
            entry = json.loads(path.read_text(encoding="utf-8") or "{}")
            if not isinstance(entry, dict) or not isinstance(entry.get("effects", []), list):
                raise ValueError("não é uma macro (esperava um objeto com `effects`)")
        except (OSError, ValueError) as exc:
            if strict:
                raise ValueError(f"não consegui ler a macro {path.name}: {exc}") from exc
            continue
        found[path.stem] = _as_preset(path.stem, entry, brand)
    return found


def _view(brand: str | None, *, strict: bool) -> list[EffectPreset]:
    migrate_legacy_presets()
    merged = _read_folder(macros_dir(), None, strict=strict)
    if brand is not None:
        merged.update(_read_folder(macros_dir(brand), brand, strict=strict))  # a da marca vale por cima
    return [merged[identifier] for identifier in sorted(merged)]


def list_user_presets(brand: str | None = None) -> list[EffectPreset]:
    """As macros salvas, por ordem de id: as globais e, com `brand`, as da marca (a da marca ganha da global de mesmo id).
    Arquivo ilegível levanta `ValueError` (quem lista para o catálogo usa `load_user_presets`)."""
    with _LOCK:
        return _view(brand, strict=True)


def load_user_presets(brand: str | None = None) -> list[EffectPreset]:
    """Como `list_user_presets`, mas arquivo ilegível é pulado e nome de marca inválido vira só as globais: o catálogo
    dos efeitos nunca fica fora do ar por causa de um arquivo que a pessoa estragou à mão."""
    with _LOCK:
        try:
            return _view(brand, strict=False)
        except ValueError:
            return _view(None, strict=False)


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


def _builtin_taken(identifier: str) -> EffectPreset | None:
    """A embutida cujo id, ou cujo nome (sem acento), é esse: o nome de uma macro do usuário não pode confundi-la."""
    for builtin in EFFECT_PRESETS.values():
        if identifier in (builtin.id, preset_id(builtin.label)):
            return builtin
    return None


def save_user_preset(
    label: str,
    effects: Sequence[dict],
    summary: str = "",
    *,
    output: dict | None = None,
    brand: str | None = None,
) -> EffectPreset:
    """Salva (ou troca) a macro de nome `label` com esses efeitos, na pasta global ou, com `brand`, na da marca. O nome
    não pode ser vazio, nem o de uma macro embutida; cada efeito é validado como na spec e a saída, como no formato."""
    name = " ".join(str(label).split())
    identifier = preset_id(name)
    if not identifier:
        raise ValueError("dê um nome à predefinição (letras ou números)")
    if len(name) > MAX_LABEL_LENGTH:
        raise ValueError(f"nome da predefinição longo demais (no máximo {MAX_LABEL_LENGTH} caracteres)")
    if (builtin := _builtin_taken(identifier)) is not None:
        raise ValueError(
            f"{name!r} é o nome de uma predefinição embutida ({builtin.label}); escolha outro nome"
        )
    if not 1 <= len(effects) <= MAX_PRESET_EFFECTS:
        raise ValueError(f"a predefinição precisa de 1 a {MAX_PRESET_EFFECTS} efeitos")
    cleaned = [_clean_effect(effect) for effect in effects]
    entry: dict[str, Any] = {"label": name, "summary": " ".join(str(summary).split()), "effects": cleaned}
    if (saved_output := clean_output(output)) is not None:
        entry["output"] = saved_output
    folder = macros_dir(brand)  # valida a marca antes de gravar
    with _LOCK:
        migrate_legacy_presets()
        _write_macro(folder, identifier, entry)
    return _as_preset(identifier, entry, brand)


def remove_user_preset(identifier: str, brand: str | None = None) -> EffectPreset:
    """Tira a macro salva de `id` dado (da pasta global ou, com `brand`, da marca) e a devolve. Uma embutida não se
    remove; uma que não existe é erro."""
    if identifier in EFFECT_PRESETS:
        raise ValueError(f"{identifier!r} é uma predefinição embutida e não pode ser removida")
    folder = macros_dir(brand)
    with _LOCK:
        migrate_legacy_presets()
        path = folder / f"{preset_id(identifier)}.json"  # o id nunca leva barra: não sai da pasta de macros
        known = _read_folder(folder, brand, strict=False)
        if preset_id(identifier) != identifier or identifier not in known or not path.is_file():
            listed = ", ".join(sorted(known)) or "nenhuma salva"
            where = "da marca" if brand else "global"
            raise ValueError(f"Predefinição salva desconhecida: {identifier!r} ({where}). Salvas: {listed}")
        preset = known[identifier]
        path.unlink()
    return preset
