"""Referência dos infográficos prontos, gerada dos esquemas (`templates/html/<nome>/esquema.json`).

Uma tabela de parâmetros por modelo, lida do mesmo esquema que a validação do projeto, o formulário da interface e a
ferramenta `list_infographics` usam: o manual nunca diverge do que o modelo aceita. Função pura: recebe a lista
`describe_infographics()` (dicionários) e devolve texto.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

TYPE_LABELS = {
    "number": "número",
    "integer": "inteiro",
    "text": "texto",
    "choice": "uma opção",
    "bool": "sim ou não",
    "color": "cor",
    "path": "arquivo",
}


def _plain(value: Any) -> str:
    if isinstance(value, bool):
        return "sim" if value else "não"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _default_label(param: Mapping[str, Any]) -> str:
    if param.get("required"):
        return "obrigatório"
    if "default" not in param:
        return "vazio"
    return f"`{_plain(param['default'])}`" if param["default"] != "" else "vazio"


def _limits_label(param: Mapping[str, Any]) -> str:
    if param.get("options"):
        return ", ".join(f"`{option}`" for option in param["options"])
    if "min" in param and "max" in param:
        return f"de {_plain(param['min'])} a {_plain(param['max'])}"
    if "max_length" in param:
        return f"até {param['max_length']} caracteres"
    if param["type"] == "color":
        return "`#RRGGBB` ou uma cor da marca"
    return ""


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def infographic_section(model: Mapping[str, Any]) -> str:
    """O bloco de um modelo: o nome, o que faz, o tamanho natural e a tabela dos parâmetros."""
    width, height = model["size"]
    lines = [
        f"#### `{model['name']}`: {model['title']}",
        "",
        model["description"],
        "",
        f"Tamanho natural da página: {width}x{height} px (base 1080); duração sugerida: {_plain(model['duration'])} s."
        + (" Prende-se a uma palavra da legenda (`palavra`)." if model.get("anchors_to_caption") else ""),
        "",
        "| Parâmetro | Tipo | Padrão | Valores aceitos | O que é |",
        "| --- | --- | --- | --- | --- |",
    ]
    for param in model["params"]:
        what = param["label"] + (f". {param['description']}" if param.get("description") else "")
        lines.append(
            f"| `{param['name']}` | {TYPE_LABELS.get(param['type'], param['type'])} | {_default_label(param)} "
            f"| {_cell(_limits_label(param))} | {_cell(what)} |"
        )
    return "\n".join(lines)


def infographics_reference(models: Sequence[Mapping[str, Any]]) -> str:
    """Todos os modelos, na ordem recebida, com a frase de como usá-los na spec."""
    if not models:
        return "Nenhum infográfico pronto nesta instalação."
    names = ", ".join(f"`{model['name']}`" for model in models)
    intro = (
        f'São {len(models)} modelos: {names}. Na spec, `{{"type": "html", "infographic": "contador", '
        f'"region": "topo", "start": 1, "end": 6, "data": {{"ate": 10000}}}}`: o nome troca o `src`, e `data` '
        "leva os parâmetros da tabela do modelo. Valor fora da tabela é apontado no `validate_project`, com o caminho "
        "do campo (`overlays[2].data.ate`)."
    )
    return "\n\n".join([intro, *(infographic_section(model) for model in models)])
