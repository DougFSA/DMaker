"""Infográficos prontos: o catálogo de `templates/html/` e o atalho `infographic: "<nome>"` da composição em HTML.

Um infográfico é uma pasta com `index.html` e `esquema.json` (ver `infographic_schema.py`). O atalho vale para
qualquer `HtmlOverlay` com `infographic` no lugar de `src`: `resolve_infographic` troca o nome pela pasta da
biblioteca e junta os padrões do esquema em `data`, e daí em diante o pipeline vê uma composição em HTML comum,
sem saber que existem modelos (nem `if` por modelo). A mesma conferência de parâmetros (`infographic_warnings`)
alimenta o `validate_project`, o lint e o QA, com o caminho do campo, para o erro aparecer antes do render.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .. import config
from .brand import Theme
from .infographic_schema import (
    InfographicSchema,
    SchemaError,
    parse_schema,
    validate_params,
    with_defaults,
)
from .spec import CaptionAnchor, HtmlOverlay, Project

SCHEMA_FILE = "esquema.json"
ENTRY_FILE = "index.html"
FILES_PREFIX = (
    "/_dmaker/files/"  # onde a página lê os arquivos de `HtmlOverlay.files` (ver media/html_site.py)
)
DASHES = ("—", "–")


class InfographicError(ValueError):
    """Nome de modelo que não existe, ou parâmetros que o esquema não aceita (a mensagem diz qual)."""


@dataclass(frozen=True)
class Infographic:
    """Um modelo pronto: o esquema e a pasta da composição."""

    schema: InfographicSchema
    folder: Path

    @property
    def name(self) -> str:
        return self.schema.name


def load_infographics(folder: Path | None = None) -> dict[str, Infographic]:
    """Os modelos da pasta (uma subpasta com `index.html` e `esquema.json` cada), em ordem de nome. Um esquema mal
    escrito levanta `SchemaError`: é erro de quem escreve o modelo e não deve passar calado."""
    base = Path(folder) if folder else config.INFOGRAPHICS_DIR
    found: dict[str, Infographic] = {}
    if not base.is_dir():
        return found
    for sub in sorted(base.iterdir()):
        schema_file = sub / SCHEMA_FILE
        if not (sub.is_dir() and (sub / ENTRY_FILE).is_file() and schema_file.is_file()):
            continue
        try:
            raw = json.loads(schema_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SchemaError(f"{sub.name}: {SCHEMA_FILE} não é um JSON válido ({exc})") from exc
        found[sub.name] = Infographic(parse_schema(sub.name, raw), sub)
    return found


def find_infographic(name: str, folder: Path | None = None) -> Infographic:
    models = load_infographics(folder)
    if name not in models:
        known = ", ".join(models) or "nenhum"
        raise InfographicError(f"modelo de infográfico desconhecido: {name!r} (modelos: {known})")
    return models[name]


def _served_name(param: str, path: Path) -> str:
    return f"{param}{path.suffix.lower()}"


def _project_path(project: Project | None, value: str) -> Path:
    """Um caminho dos parâmetros: relativo à pasta do projeto, ou ao diretório atual quando não há projeto."""
    return project.resolve(value) if project is not None else Path(value).expanduser().resolve()


def resolve_infographic(
    overlay: HtmlOverlay, project: Project | None = None, folder: Path | None = None
) -> HtmlOverlay:
    """A composição com `src` no lugar de `infographic`: a pasta do modelo, os parâmetros com os padrões do esquema,
    os arquivos do projeto em `files` e, se o modelo se prende à legenda, o `anchor`. Sem `infographic` devolve a
    própria composição. Levanta `InfographicError` com a primeira coisa que o esquema não aceita. `project` serve
    para achar os arquivos por caminho relativo (sem ele, vale o diretório atual)."""
    if overlay.infographic is None:
        return overlay
    model = find_infographic(overlay.infographic, folder)
    schema = model.schema
    issues = validate_params(schema, overlay.data)
    if issues:
        raise InfographicError(f"{schema.name}: {issues[0].message}")
    data = with_defaults(schema, overlay.data)
    files = dict(overlay.files)
    for name, param in schema.params.items():
        if param.type != "path" or name not in data:
            continue
        path = _project_path(project, data[name])
        if not path.is_file():
            raise InfographicError(f"{schema.name}: `{name}` aponta para um arquivo que não existe: {path}")
        files[_served_name(name, path)] = str(path)
        data[name] = FILES_PREFIX + _served_name(name, path)
    update: dict = {"src": str(model.folder), "infographic": None, "data": data, "files": files}
    keys = schema.caption_anchor
    if keys is not None and overlay.anchor is None and data.get(keys.word):
        update["anchor"] = CaptionAnchor(
            word=str(data[keys.word]),
            occurrence=int(data[keys.occurrence]),
            hold=data[keys.hold],
            margin=float(data[keys.margin]),
        )
    # o quadro todo (o padrão da spec, que o arquivo salvo repete) conta como "sem lugar": um modelo pronto é fluido
    # e o lugar natural dele é a área do esquema; quem o quer maior diz a região, ou o `width`/`height`
    explicit_place = bool(overlay.region) or overlay.x is not None or overlay.width < 1 or overlay.height < 1
    anchored = overlay.anchor is not None or "anchor" in update
    if not (explicit_place or anchored) and schema.area:
        area = schema.area
        update.update(x=area["x"], y=area["y"], width=area["width"], height=area["height"])
    return overlay.model_copy(update=update)


def infographic_warnings(project: Project, theme: Theme, folder: Path | None = None) -> list[str]:
    """Avisos, antes de renderizar, sobre os infográficos do projeto, com o caminho do campo
    (`overlays[2].data.ate: ...`): modelo que não existe, parâmetro fora do esquema, arquivo que falta e travessão
    em texto quando a marca proíbe."""
    warnings: list[str] = []
    models = load_infographics(folder)
    colors = tuple(theme.colors)
    for index, overlay in enumerate(project.overlays):
        if not isinstance(overlay, HtmlOverlay) or overlay.infographic is None:
            continue
        where = f"overlays[{index}]"
        model = models.get(overlay.infographic)
        if model is None:
            known = ", ".join(models) or "nenhum"
            warnings.append(
                f"{where}.infographic: modelo desconhecido {overlay.infographic!r} (modelos: {known})"
            )
            continue
        schema = model.schema
        for issue in validate_params(schema, overlay.data, colors):
            warnings.append(f"{where}.data.{issue.param}: {issue.detail}")
        for name, param in schema.params.items():
            value = overlay.data.get(name)
            if param.type == "path" and isinstance(value, str) and value.strip():
                if not project.resolve(value).is_file():
                    warnings.append(f"{where}.data.{name}: arquivo não encontrado: {project.resolve(value)}")
            if param.type == "text" and isinstance(value, str) and theme.no_dash:
                if any(dash in value for dash in DASHES):
                    warnings.append(
                        f"{where}.data.{name}: contém travessão/meia-risca. Regra da marca {theme.name}: "
                        "usar vírgula, ponto ou dois-pontos."
                    )
        if overlay.anchor is None and schema.caption_anchor and overlay.data.get(schema.caption_anchor.word):
            if not (project.captions and project.captions.enabled):
                warnings.append(f"{where}: presa a uma palavra da legenda, mas o projeto não tem legendas")
        if overlay.anchor is not None and not (project.captions and project.captions.enabled):
            warnings.append(f"{where}.anchor: presa a uma palavra da legenda, mas o projeto não tem legendas")
    return warnings
