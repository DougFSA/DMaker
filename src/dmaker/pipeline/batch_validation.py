"""Validação de uma planilha de lote ANTES de renderizar qualquer coisa.

Para cada linha monta o projeto pelo modelo EM MEMÓRIA e roda as conferências que o editor já tem: a spec
(`Project`), a existência dos arquivos, a regra da marca (sem travessão) e as checagens estáticas do QA, que
medem se o texto cabe no espaço. Cada problema sai com a linha, a coluna e o motivo, no nome em que a pessoa
escreveu a coluna. Nenhum render e nenhum arquivo gravado: só o probe das imagens, para medir o quadro.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from ..domain.batch_sheet import (
    ColumnMatch,
    Issue,
    Sheet,
    SheetRow,
    flatten_strings,
    match_columns,
    pick_name_column,
    row_params,
)
from ..domain.brand import load_theme
from ..domain.spec import ClipSegment, ImageOverlay, ImageSegment, Project, VideoOverlay
from ..domain.templates import Template, TemplateError, render_template
from ..media.probe import probe
from .context import Prober
from .layout import project_layout, to_presentation
from .lint import DASHES
from .report import STATIC_CHECKS, check_text_safe_zone
from .sync import OffsetFinder

PATH_TYPES = ("path", "paths", "dir")
SCRATCH_NAME = "validacao"  # nome do projeto em memória; só o QA o lê
BASELINE_TEXT = "Texto"  # texto curto que mede o espaço do modelo sem o texto da planilha


@dataclass
class RowCheck:
    """O que a validação achou numa linha: os parâmetros que ela preenche, a spec montada e os problemas."""

    index: int  # posição entre as linhas de dados, a partir de 1
    line: int  # linha na planilha
    title: str  # texto da coluna do nome do arquivo ("" se a célula está vazia)
    params: dict[str, Any]
    issues: list[Issue] = field(default_factory=list)
    spec: dict | None = None  # spec do projeto, só quando o modelo e o `Project` aceitaram a linha
    measured: bool = False  # as checagens de espaço do QA rodaram nesta linha

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.level == "erro"]

    @property
    def warnings(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.level == "aviso"]

    @property
    def valid(self) -> bool:
        return self.spec is not None and not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "line": self.line,
            "title": self.title,
            "valid": self.valid,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass
class BatchValidation:
    template: str
    name_column: str | None
    headers: list[str]
    columns: ColumnMatch
    rows: list[RowCheck]
    issues: list[Issue] = field(default_factory=list)  # da planilha inteira (coluna que falta, repetida)

    @property
    def valid_rows(self) -> list[RowCheck]:
        return [row for row in self.rows if row.valid]

    @property
    def invalid_rows(self) -> list[RowCheck]:
        return [row for row in self.rows if not row.valid]

    @property
    def sheet_errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.level == "erro"]

    @property
    def ok(self) -> bool:
        """Dá para rodar tudo: planilha inteira sem erro e nenhuma linha com problema."""
        return bool(self.rows) and not self.sheet_errors and not self.invalid_rows

    @property
    def runnable(self) -> bool:
        """Dá para rodar pelo menos as linhas válidas."""
        return not self.sheet_errors and bool(self.valid_rows)

    def to_dict(self) -> dict[str, Any]:
        return {
            "template": self.template,
            "name_column": self.name_column,
            "headers": self.headers,
            "columns": {
                "matched": self.columns.columns,
                "unused": self.columns.unused,
                "missing": self.columns.missing,
            },
            "issues": [issue.to_dict() for issue in self.issues],
            "rows": [row.to_dict() for row in self.rows],
            "total": len(self.rows),
            "valid": len(self.valid_rows),
            "invalid": len(self.invalid_rows),
            "ok": self.ok,
        }

    def to_text(self) -> str:
        """Resumo para o terminal: o que casou, e uma linha por problema, com linha e coluna."""
        lines = [
            f"Modelo {self.template}: {len(self.rows)} linha(s), {len(self.valid_rows)} válida(s), "
            f"{len(self.invalid_rows)} com problema."
        ]
        if self.columns.columns:
            lines.append(
                "Colunas usadas: "
                + ", ".join(f"{header} -> {param}" for param, header in self.columns.columns.items())
            )
        lines += [f"  {issue.level}: {issue.describe()}" for issue in self.issues]
        for row in self.rows:
            lines += [f"  {issue.level}: {issue.describe()}" for issue in row.issues]
        return "\n".join(lines)


def _first_line(message: object) -> str:
    return str(message).strip().splitlines()[0] if str(message).strip() else "erro sem mensagem"


def _validation_message(exc: ValidationError) -> str:
    """Os primeiros erros da spec numa frase, com o caminho do campo que o modelo montou errado."""
    parts = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:3]]
    return "o modelo não montou uma spec válida com estes valores (" + "; ".join(parts) + ")"


def _column_of(text: str, params: Mapping[str, Any], match: ColumnMatch, exact: bool) -> str | None:
    """Coluna de onde veio um texto: o parâmetro cujo valor é (ou está contido em) `text`, o mais longo
    primeiro. None quando o texto vem do próprio modelo."""
    best: tuple[int, str] | None = None
    for name, value in params.items():
        for piece in flatten_strings(value):
            hit = os.path.normcase(piece) == os.path.normcase(text) if exact else piece and piece in text
            if hit and (best is None or len(piece) > best[0]):
                best = (len(piece), name)
    return match.header_of(best[1]) if best else None


def _full_params(template: Template, params: Mapping[str, Any]) -> dict[str, Any]:
    """Os parâmetros da linha com o padrão do modelo onde a célula ficou vazia, para achar a origem de um valor."""
    return {name: params.get(name, param.default) for name, param in template.params.items()}


def _missing_param_files(
    template: Template, params: Mapping[str, Any], match: ColumnMatch, line: int
) -> list[Issue]:
    issues: list[Issue] = []
    for name, param in template.params.items():
        if param.type not in PATH_TYPES or name not in params:
            continue
        value = params[name]
        for path in [value] if isinstance(value, str) else value:
            if not os.path.exists(path):
                what = "pasta" if param.type == "dir" else "arquivo"
                issues.append(Issue(line, match.header_of(name), f"{what} não encontrado: {path}"))
    return issues


def media_references(project: Project) -> list[tuple[str, str]]:
    """Os arquivos que o projeto aponta (trechos, imagens e vídeos sobrepostos, trilha), com a origem de cada um."""
    refs: list[tuple[str, str]] = []
    for i, segment in enumerate(project.timeline):
        if isinstance(segment, (ClipSegment, ImageSegment)) and segment.src:
            refs.append((f"timeline[{i}].src", segment.src))
    for i, overlay in enumerate(project.overlays):
        if (
            isinstance(overlay, ImageOverlay)
            and overlay.src != "logo"
            and not overlay.src.startswith("logo:")
        ):
            refs.append((f"overlays[{i}].src", overlay.src))
        if isinstance(overlay, VideoOverlay) and overlay.src:
            refs.append((f"overlays[{i}].src", overlay.src))
    if project.audio.music:
        refs.append(("audio.music.src", project.audio.music.src))
    for i, clip in enumerate(project.audio.voiceover):
        refs.append((f"audio.voiceover[{i}].src", clip.src))
    return refs


def _missing_project_files(
    project: Project, full: Mapping[str, Any], match: ColumnMatch, line: int
) -> list[Issue]:
    """Arquivo que a spec montada aponta e não existe, mesmo vindo de dentro de uma lista ou do padrão do modelo."""
    issues: list[Issue] = []
    for _where, src in media_references(project):
        if not os.path.exists(project.resolve(src)):
            issues.append(
                Issue(line, _column_of(src, full, match, exact=True), f"arquivo não encontrado: {src}")
            )
    return issues


def _dash_issues(project: Project, full: Mapping[str, Any], match: ColumnMatch, line: int) -> list[Issue]:
    """Regra da marca: texto na tela sem travessão nem meia-risca quando a marca proíbe. Independe dos arquivos,
    então aparece junto com um arquivo faltando; o aviso do lint para o mesmo texto fica de fora do QA."""
    try:
        theme = load_theme(project.brand, project.theme)
    except (ValueError, FileNotFoundError, KeyError) as exc:
        return [Issue(line, None, f"marca ou tema não carregou: {_first_line(exc)}")]
    if not theme.no_dash:
        return []
    dashed = {
        name: value
        for name, value in full.items()
        if any(dash in piece for piece in flatten_strings(value) for dash in DASHES)
    }
    issues: list[Issue] = []
    for where, text in project.texts():
        if any(dash in text for dash in DASHES):
            column = _column_of(text, dashed, match, exact=False)
            place = "" if column else f" ({where})"
            message = (
                f"contém travessão ou meia-risca{place}. Regra da marca {theme.name}: "
                "use vírgula, ponto ou dois-pontos"
            )
            issues.append(Issue(line, column, message))
    return issues


def _measure(
    project: Project, prober: Prober, offset_finder: OffsetFinder | None
) -> list[tuple[Callable, Any]]:
    """Os achados das checagens estáticas do QA sobre a spec montada, com a checagem que os achou."""
    layout = to_presentation(project, project_layout(project, prober, offset_finder))
    return [(check, finding) for check in STATIC_CHECKS for finding in check(project, layout)]


def _short_text_variant(template: Template, project: Project, params: Mapping[str, Any]) -> dict[str, Any]:
    """Os mesmos parâmetros, com o texto de tela da planilha trocado por uma palavra curta, que nunca estoura."""
    shown = [text for _where, text in project.texts()]
    short = dict(params)
    for name, param in template.params.items():
        value = params.get(name)
        if param.type == "text" and isinstance(value, str) and any(value in text for text in shown):
            short[name] = BASELINE_TEXT
    return short


def _baseline_overflow(
    template: Template,
    project: Project,
    params: Mapping[str, Any],
    prober: Prober,
    offset_finder: OffsetFinder | None,
) -> set[tuple[str, str]] | None:
    """O que a checagem de espaço já acusa com textos curtos: é defeito do desenho do modelo (um texto fixo
    perto da borda, por exemplo), e nenhuma linha da planilha consegue consertá-lo. None se não deu para medir."""
    try:
        variant = Project.model_validate(
            {
                **render_template(template, _short_text_variant(template, project, params)),
                "name": SCRATCH_NAME,
            }
        )
        found = _measure(variant, prober, offset_finder)
    except (TemplateError, ValidationError, ValueError, KeyError, RuntimeError, FileNotFoundError):
        return None
    return {(finding.where, finding.message) for check, finding in found if check is check_text_safe_zone}


def _qa_issues(
    template: Template,
    project: Project,
    params: Mapping[str, Any],
    full: Mapping[str, Any],
    match: ColumnMatch,
    line: int,
    prober: Prober,
    offset_finder: OffsetFinder | None,
) -> list[Issue]:
    """As checagens estáticas do QA sobre a spec montada. O texto da planilha que não cabe no espaço (zona
    segura, palavra mais larga que a área, cartão alto demais) bloqueia a linha; ritmo, contraste e o resto
    ficam como aviso, e também o problema que já existe com textos curtos, por ser do modelo."""
    try:
        found = _measure(project, prober, offset_finder)
    except (FileNotFoundError, ValueError, KeyError, RuntimeError) as exc:
        return [Issue(line, None, f"não consegui medir o vídeo: {_first_line(exc)}")]
    baseline = _baseline_overflow(template, project, params, prober, offset_finder)
    texts = dict(project.texts())
    issues: list[Issue] = []
    for check, finding in found:
        if (
            finding.level == "info" or "travessão" in finding.message
        ):  # o travessão já saiu pela coluna de origem
            continue
        text = texts.get(finding.where, "")
        column = _column_of(text, full, match, exact=False) if text else None
        from_sheet = (
            column is not None if baseline is None else (finding.where, finding.message) not in baseline
        )
        blocks = finding.level == "erro" or (check is check_text_safe_zone and from_sheet)
        message = finding.message if column else f"{finding.message} ({finding.where})"
        issues.append(Issue(line, column, message, "erro" if blocks else "aviso"))
    return issues


def _title_of(row: SheetRow, name_header: str | None) -> str:
    value = row.cells.get(name_header) if name_header else None
    return "" if value is None else str(value).strip()


def check_row(
    template: Template,
    row: SheetRow,
    position: int,
    match: ColumnMatch,
    name_header: str | None,
    *,
    base_dir: str | None,
    prober: Prober,
    offset_finder: OffsetFinder | None,
) -> RowCheck:
    """Valida uma linha, da mais barata (campo vazio) à mais cara (medir o texto). Não adianta medir um
    quadro cujo arquivo não existe, então a medição só vem quando nada mais deu erro."""
    params, issues = row_params(row, match, template.params, base_dir)
    check = RowCheck(position, row.line, _title_of(row, name_header), params, issues)
    if check.errors:
        return check
    issues += _missing_param_files(template, params, match, row.line)
    missing_files = bool(
        check.errors
    )  # segue montando a spec: o travessão aparece junto com o arquivo faltando
    try:
        spec = {**render_template(template, params), "name": SCRATCH_NAME}
        project = Project.model_validate(spec)
    except ValidationError as exc:
        if not missing_files:
            issues.append(Issue(row.line, None, _validation_message(exc)))
        return check
    except (TemplateError, ValueError, FileNotFoundError) as exc:
        if not missing_files:
            issues.append(Issue(row.line, None, _first_line(exc)))
        return check
    full = _full_params(template, params)
    issues += _missing_project_files(project, full, match, row.line)
    issues += _dash_issues(project, full, match, row.line)
    issues[:] = list(dict.fromkeys(issues))  # o mesmo arquivo pode vir do parâmetro e da spec montada
    if not check.errors:
        issues += _qa_issues(template, project, params, full, match, row.line, prober, offset_finder)
        check.measured = True
    if not check.errors:
        check.spec = spec
    return check


def _hoist_common_warnings(rows: list[RowCheck]) -> list[Issue]:
    """Aviso que o próprio modelo dá em todas as linhas medidas (sem coluna de origem) sobe para a planilha,
    uma vez, em vez de repetir em cada linha."""
    measured = [row for row in rows if row.measured]
    if len(measured) < 2:
        return []
    per_row = [{i.message for i in row.warnings if i.field is None} for row in measured]
    common = set.intersection(*per_row)
    for row in measured:
        row.issues[:] = [
            i for i in row.issues if not (i.level == "aviso" and i.field is None and i.message in common)
        ]
    return [
        Issue(None, None, f"{message}. Vem do modelo, em todas as linhas", "aviso")
        for message in sorted(common)
    ]


def validate_sheet(
    template: Template,
    sheet: Sheet,
    *,
    base_dir: str | None = None,
    name_column: str | None = None,
    prober: Prober = probe,
    offset_finder: OffsetFinder | None = None,
) -> BatchValidation:
    """Confere a planilha inteira contra o modelo sem renderizar nada. `prober` entra por injeção
    para o teste não precisar do ffprobe."""
    match = match_columns(sheet.headers, template.params)
    name_header = pick_name_column(sheet.headers, name_column)
    rows = [
        check_row(
            template,
            row,
            position,
            match,
            name_header,
            base_dir=base_dir,
            prober=prober,
            offset_finder=offset_finder,
        )
        for position, row in enumerate(sheet.rows, start=1)
    ]
    issues = list(match.issues) + _hoist_common_warnings(rows)
    if not sheet.rows:
        issues.append(Issue(None, None, "a planilha não tem nenhuma linha de dados"))
    return BatchValidation(template.name, name_header, list(sheet.headers), match, rows, issues)
