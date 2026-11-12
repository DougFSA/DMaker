"""Lê o cabeçalho de um avatar `.glb` e confere se serve à persona 3D (função pura sobre o arquivo, sem three.js).

O TalkingHead só anima um personagem com o esqueleto no padrão do Mixamo e com os blendshapes de visema do conjunto
Oculus. Conferir aqui, antes de abrir o navegador, troca um erro obscuro da página por uma mensagem que diz o que
falta no arquivo.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

from .visemes import VISEMES

GLB_MAGIC = b"glTF"
JSON_CHUNK = 0x4E4F534A  # "JSON" em little endian
MAX_JSON_BYTES = 64 << 20  # o cabeçalho de um avatar tem poucos MB; acima disso o arquivo não é um avatar

REQUIRED_VISEMES = tuple(
    f"viseme_{name}" for name in VISEMES if name != "sil"
)  # `sil` é a boca fechada, sem forma
REQUIRED_BONES = ("Hips", "Spine", "Neck", "Head", "LeftEye", "RightEye", "LeftArm", "RightArm", "LeftHand")


class GlbError(ValueError):
    """O arquivo não é um `.glb` legível."""


def read_glb_json(path: Path) -> dict[str, Any]:
    """O JSON do glTF (a descrição do modelo), lido sem carregar as malhas e texturas do arquivo."""
    try:
        with path.open("rb") as handle:
            header = handle.read(20)
            if len(header) < 20 or header[:4] != GLB_MAGIC:
                raise GlbError(f"{path.name} não é um arquivo .glb (glTF binário).")
            length, kind = struct.unpack("<II", header[12:20])
            if kind != JSON_CHUNK or length > MAX_JSON_BYTES:
                raise GlbError(f"{path.name} tem um cabeçalho de glTF que não consegui ler.")
            return json.loads(handle.read(length))
    except OSError as exc:
        raise GlbError(f"Não consegui abrir {path}: {exc}") from exc
    except GlbError:
        raise
    except ValueError as exc:
        raise GlbError(f"{path.name} tem um cabeçalho de glTF inválido.") from exc


def morph_target_names(description: dict[str, Any]) -> set[str]:
    """Os nomes de todos os blendshapes das malhas (o Blender grava em `extras.targetNames`)."""
    names: set[str] = set()
    for mesh in description.get("meshes", []):
        names.update(mesh.get("extras", {}).get("targetNames", []))
        for primitive in mesh.get("primitives", []):
            names.update(primitive.get("extras", {}).get("targetNames", []))
    return names


def bone_names(description: dict[str, Any]) -> set[str]:
    """Os nomes dos nós, sem o prefixo `mixamorig` que o Mixamo põe (o TalkingHead o tira também)."""
    return {node.get("name", "").replace("mixamorig", "") for node in description.get("nodes", [])}


def avatar_problems(path: Path) -> list[str]:
    """Mensagens (PT-BR) do que falta no avatar para a persona 3D; lista vazia quando ele serve."""
    try:
        description = read_glb_json(path)
    except GlbError as exc:
        return [str(exc)]
    problems: list[str] = []
    targets = morph_target_names(description)
    missing_visemes = [name for name in REQUIRED_VISEMES if name not in targets]
    if missing_visemes:
        problems.append(
            f"{path.name} não tem os blendshapes de visema da boca ({', '.join(missing_visemes)}); a persona "
            "3D precisa dos 14 visemas Oculus (viseme_aa, viseme_PP...) para a boca acompanhar a fala."
        )
    bones = bone_names(description)
    missing_bones = [name for name in REQUIRED_BONES if name not in bones]
    if missing_bones:
        problems.append(
            f"{path.name} não tem os ossos no padrão do Mixamo ({', '.join(missing_bones)}); sem eles o "
            "personagem não move a cabeça nem os braços."
        )
    return problems
