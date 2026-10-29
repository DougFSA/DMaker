"""Servidor MCP do DMaker: expõe o editor como ferramentas para qualquer IA (Claude, Cursor, etc.).

Sobe por stdio (`dmaker mcp`). Ferramentas devolvem JSON; as de conferência devolvem imagens, para a IA
ver o resultado. Renders longos rodam em segundo plano com `job_id` (ver `job_status`).
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import Image, MCPServer

from . import __version__, config
from .domain.brand import available_brands, load_theme
from .domain.presets import get_preset, list_presets
from .domain.spec import Project
from .pipeline.jobs import Job, JobManager
from .pipeline.recipes import preview_notice
from .pipeline.remote import RenderDispatcher, UIClient

GUIDE_PATH = config.PACKAGE_DIR / "resources" / "guide.md"

server = MCPServer(
    name="dmaker",
    version=__version__,
    instructions=(
        "DMaker edita vídeos curtos para Instagram, Facebook, YouTube, TikTok e WhatsApp a partir de uma spec JSON. "
        "Comece por `dmaker_guide` (manual e regras) e `spec_schema`. Fluxo: probe_media -> save_project -> "
        "validate_project -> render_project(preview=true) -> qa_report para conferir (só olhe imagem com "
        "contact_sheet/frames se o relatório apontar algo) -> render_project."
    ),
)
jobs = JobManager()


def _result_dict(result: Any) -> dict:
    return {
        "output": str(result.output),
        "thumbnail": str(result.thumbnail) if result.thumbnail else None,
        "duration_s": round(result.duration, 2),
        "size_mb": round(result.size_bytes / 1e6, 2),
        "preset": result.preset.id,
        "resolution": f"{result.preset.width}x{result.preset.height}",
        "captions_file": str(result.captions_file) if result.captions_file else None,
        "warnings": result.warnings,
        "job_dir": str(result.job_dir) if result.job_dir else None,
    }


def _format_mmss(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def _summary_dict(summary: Any) -> dict:
    return {
        "name": summary.name,
        "preset": summary.preset.id,
        "resolution": f"{summary.preset.width}x{summary.preset.height}",
        "theme": summary.theme.name,
        "total_s": round(summary.total, 2),
        "segments": [
            {"index": s.index, "type": s.type, "duration_s": round(s.duration, 2), "label": s.label}
            for s in summary.segments
        ],
        "warnings": summary.warnings,
    }


# ---------- conhecimento ----------


@server.tool(
    description="Manual de operação do DMaker: fluxo, referência da spec e regras da marca. Leia primeiro."
)
def dmaker_guide() -> str:
    return GUIDE_PATH.read_text(encoding="utf-8") if GUIDE_PATH.exists() else "Manual não encontrado."


@server.tool(description="JSON Schema da spec de projeto (validação Pydantic).")
def spec_schema() -> dict:
    return Project.model_json_schema()


@server.tool(
    description=(
        "Busca no manual do DMaker, sem internet e por palavras: devolve os trechos que mais combinam com a "
        "pergunta, cada um com a seção, a nota e o texto, e a tarefa do manual que mais combina (o arquivo "
        "docs/ia dela traz o passo a passo). Use antes de adivinhar como se faz algo."
    )
)
def search_manual(question: str, limit: int = 5) -> dict:
    from .manual.service import search_manual as run_search

    return run_search(question, limit)


@server.tool(description="Formatos de saída por plataforma, com tamanho, limite de duração e zonas seguras.")
def presets(platform: str | None = None) -> list[dict]:
    return [
        {
            "id": p.id,
            "platform": p.platform,
            "name": p.name,
            "width": p.width,
            "height": p.height,
            "fps": p.fps,
            "max_duration_s": p.max_duration,
            "safe_zone": p.safe.__dict__,
            "notes": p.notes,
        }
        for p in list_presets(platform)
    ]


@server.tool(description="Marcas (temas) disponíveis e suas cores, fontes e logos.")
def brands() -> list[dict]:
    out = []
    for name in available_brands():
        t = load_theme(name)
        out.append(
            {
                "key": name,
                "name": t.name,
                "colors": t.colors,
                "font": t.font_family,
                "logos": {k: str(v) for k, v in t.logos.items()},
                "rules": t.rules,
                "cta": t.cta,
            }
        )
    return out


@server.tool(description="Duração, tamanho, fps, áudio e orientação de vídeos, imagens e áudios.")
def probe_media(paths: list[str]) -> list[dict]:
    from .media.probe import probe

    out = []
    for raw in paths:
        p = Path(raw)
        try:
            i = probe(p)
            out.append(
                {
                    "path": str(p),
                    "kind": "image" if i.is_image else ("video" if i.has_video else "audio"),
                    "width": i.width,
                    "height": i.height,
                    "duration_s": round(i.duration, 3),
                    "fps": i.fps,
                    "has_audio": i.has_audio,
                    "orientation": i.orientation,
                    "rotation": i.rotation,
                }
            )
        except Exception as exc:  # noqa: BLE001 - erro por arquivo, não derruba a lista
            out.append({"path": str(p), "error": str(exc)})
    return out


# ---------- projetos ----------


@server.tool(
    description="Valida e salva uma spec em projects/<name>/spec.json. Devolve o resumo (duração, avisos)."
)
def save_project(name: str, spec: dict) -> dict:
    from .pipeline.projects import save_project as _save
    from .pipeline.projects import summarize

    spec = dict(spec)
    spec["name"] = name
    project = Project.model_validate(spec)
    path = _save(project)
    summary = summarize(project)
    return {"spec_path": str(path), **_summary_dict(summary)}


@server.tool(
    description=(
        "Templates disponíveis (produto, depoimento, stories, vlog, tutorial, explicativo, casamento...) com os "
        "parâmetros de cada um. Caminho preferido para criar projetos: em vez de escrever a spec "
        "inteira, veja aqui os parâmetros e chame `new_from_template`."
    )
)
def list_templates() -> list[dict]:
    from .pipeline.projects import describe_templates

    return describe_templates()


@server.tool(
    description=(
        "Cria um projeto a partir de um template (ver `list_templates`) e parâmetros, sem escrever a "
        "spec inteira. Salva em projects/<name>/spec.json e devolve o mesmo resumo que "
        "`validate_project` (duração, avisos)."
    )
)
def new_from_template(template: str, name: str, params: dict) -> dict:
    from mcp.server.mcpserver.exceptions import ToolError

    from .domain.templates import TemplateError
    from .pipeline.projects import project_from_template, project_path, summarize

    try:
        project = project_from_template(template, name, params)
    except (TemplateError, FileNotFoundError) as exc:
        # anticipada: mensagem chega ao cliente (nome do template, parâmetros faltando ou arquivo de mídia ausente)
        raise ToolError(str(exc)) from exc
    return {"spec_path": str(project_path(name)), **_summary_dict(summarize(project))}


@server.tool(description="Lê a spec de um projeto (nome em projects/ ou caminho de spec.json).")
def get_project(name_or_path: str) -> dict:
    from .pipeline.projects import load_project, project_path

    project = load_project(name_or_path)
    return {
        "spec_path": str(project_path(name_or_path)),
        "spec": json.loads(project.model_dump_json(exclude_none=True)),
    }


@server.tool(
    description="Confere arquivos, calcula a duração final e lista avisos (limites da plataforma, marca)."
)
def validate_project(name_or_path: str) -> dict:
    from .pipeline.projects import load_project, summarize

    return _summary_dict(summarize(load_project(name_or_path)))


@server.tool(
    description=(
        "Aplica uma edição pontual na linha do tempo e salva: split (cortar no cursor), remove, move, "
        "trim (aparar entrada/saída), duplicate, insert, overlay_span/overlay_remove/overlay_duplicate "
        'e set_field (muda um campo pelo caminho, ex.: "timeline.2.speed"). `op` é um dict com '
        '"type" e os parâmetros da operação, ex.: {"type": "split", "index": 1, "at": 2.5}.'
    )
)
def edit_project(name: str, op: dict) -> dict:
    from .pipeline.edits import apply_edit
    from .pipeline.projects import load_project, summarize
    from .pipeline.projects import save_project as _save

    project = load_project(name)
    new_project = apply_edit(project, op)
    path = _save(new_project)
    summary = summarize(new_project)
    return {"spec_path": str(path), **_summary_dict(summary)}


@server.tool(
    description=(
        "Vista da linha do tempo multitrilha do projeto (V2/V3... picture-in-picture, TX texto, "
        "GR imagem/barra de progresso, V1 trechos, A1 áudio dos clipes, A2... faixas externas, "
        "NAR narrações (duração real quando já sintetizadas, senão estimada), "
        "MUS música, CC legendas), com o intervalo de cada item já calculado."
    )
)
def timeline_view(name: str) -> dict:
    from .pipeline.layout import project_layout
    from .pipeline.projects import load_project
    from .pipeline.timeline_view import build_timeline_view
    from .pipeline.voiceover import view_narration_durations

    project = load_project(name)
    layout = project_layout(project)
    durations = view_narration_durations(project)
    return build_timeline_view(project, layout, narration_durations=durations).to_dict()


@server.tool(
    description=(
        "Planeja o corte automático de um bloco `multicam` da spec: transcreve a câmera de áudio, "
        "reconhece as fases da cerimônia pela fala (termos ditos, ex.: consentimento, votos, alianças) "
        "e substitui o bloco pelos clipes concretos, alternando as câmeras pela cadência e atraindo "
        "os cortes para pausas da fala. Salva o projeto já expandido; devolve quantos clipes saíram, "
        "as fases reconhecidas (com o instante em que abriram) e os avisos (buracos de cobertura etc.)."
    )
)
def plan_multicam(name_or_path: str) -> dict:
    from .pipeline.multicam_plan import plan_multicam as _plan_multicam

    result = _plan_multicam(name_or_path)
    return {
        "clips": result.clips,
        "warnings": result.warnings,
        "phases": [
            {"name": name, "at_s": round(at, 2), "at": _format_mmss(at)} for name, at in result.phases
        ],
        "speech_seconds": round(result.speech_seconds, 1),
        "start_s": round(result.start, 2),
        "end_s": round(result.end, 2),
    }


# ---------- cortar pausas, vícios e repetições de uma gravação falada ----------


def _autocut_service(job: Job | None = None) -> Any:
    """O serviço de corte com as peças de verdade; com `job`, o ffmpeg e as etapas viram progresso dele."""
    from .media.ffmpeg import SubprocessRunner
    from .pipeline.autocut import AutoCutService

    if job is None:
        return AutoCutService()
    return AutoCutService(runner=SubprocessRunner(sink=job.sink()), log=job.log)


def _autocut_work(job: Job, request: Any) -> dict:
    """O corte ligado ao job: a transcrição é lenta na CPU, então cada etapa vira progresso."""
    from .pipeline.jobs import stage_progress

    result = _autocut_service(job).cut(request, stage_progress(job))
    return {
        "project": result.project.name,
        "spec_path": str(result.spec_path),
        "report": result.report.to_dict(),
        "warnings": result.warnings,
    }


@server.tool(
    description=(
        "Corta as pausas, os vícios de fala e as frases repetidas de uma gravação falada (use no lugar de "
        "transcrever e cortar clipe a clipe à mão). Cria o projeto `name` com os clipes já cortados, as "
        "legendas seguindo a fala cortada, e devolve a lista do que saiu (cada corte com id, tempo na "
        "gravação original, motivo e as palavras tiradas) para conferir ANTES de renderizar. "
        "intensity: suave (só pausas), normal (pausas e vícios: hã, é isolado, tipo isolado, né no fim da "
        "frase; o 'né' de 'não é' no meio da frase fica) ou agressiva (inclui falsos começos e frases "
        "repetidas, ficando com a última tomada). min_pause: pausa em segundos acima da qual vira corte; "
        "breath: silêncio mantido de cada lado. Cada borda cai no vale de energia, com fade de áudio de "
        "10 ms. Roda em segundo plano (transcreve com o Whisper; ~1 min por minuto de gravação na CPU): "
        "devolve job_id, consulte com job_status; a segunda chamada na mesma gravação reaproveita a "
        "transcrição. Corrija o resultado com undo_cut (devolve um corte) e confira com list_cuts."
    )
)
def autocut(
    source: str,
    name: str,
    intensity: Literal["suave", "normal", "agressiva"] = "normal",
    min_pause: float = 0.5,
    breath: float = 0.15,
    preset: str = "instagram/reels",
    brand: str | None = None,
    captions: bool = True,
    language: str = "pt",
    model: str = "small",
    overwrite: bool = False,
    wait_seconds: float = 0,
) -> dict:
    from .pipeline.autocut import AutoCutRequest
    from .voice.cut_plan import CutOptions

    request = AutoCutRequest(
        source=Path(source),
        name=name,
        options=CutOptions(intensity=intensity, min_pause=min_pause, breath=breath),
        preset=preset,
        brand=brand,
        captions=captions,
        language=language,
        model=model,
        overwrite=overwrite,
    )
    _autocut_service().validate(request)  # o erro de nome, arquivo ou formato aparece já, não só no job
    job = jobs.start(f"autocut {name}", lambda job: _autocut_work(job, request))
    jobs.wait(job, wait_seconds)
    return {**job.snapshot(), "result": job.result}


@server.tool(
    description=(
        "Lista o que o `autocut` removeu de um projeto: para cada corte, id, início e fim na gravação original, "
        "duração, motivo (silence, filler, repetition), as palavras tiradas e se já foi desfeito, mais a "
        "duração antes e depois."
    )
)
def list_cuts(name_or_path: str) -> dict:
    from .pipeline.autocut import load_cut_report
    from .pipeline.projects import project_path

    report = load_cut_report(project_path(name_or_path).parent)
    if report is None:
        raise ValueError(f"{name_or_path} não tem lista de cortes (só projetos criados por autocut têm)")
    return report.to_dict()


@server.tool(
    description=(
        "Desfaz um corte do `autocut` (id de list_cuts): o trecho removido volta ao projeto, juntando os "
        "clipes vizinhos, e as legendas voltam a incluir as palavras dele. Devolve a lista atualizada."
    )
)
def undo_cut(name_or_path: str, cut_id: int) -> dict:
    from .pipeline.autocut import undo_cut as _undo_cut

    return _undo_cut(name_or_path, cut_id).to_dict()


# ---------- lote: vários vídeos de uma planilha ----------


def _batch_service() -> Any:
    from .pipeline.batch import BatchService

    return BatchService()


def _batch_job(name: str, rows: list[int] | None, force: bool, wait_seconds: float) -> dict:
    """Roda (ou retoma) o lote num job: o andamento sai por `job_status` e pausar para depois do vídeo atual."""
    from .pipeline.batch import run_in_job

    service = _batch_service()
    if service.active(name):
        raise ValueError(f"O lote {name} já está rodando; acompanhe com batch_status.")
    job = jobs.start(
        f"lote {name}",
        lambda job: run_in_job(service, name, job, rows, force),
        meta={"kind": "batch", "batch": name, "cancellable": True},
    )
    jobs.wait(job, wait_seconds)
    return {**job.snapshot(), "batch": name, "result": job.result}


@server.tool(
    description=(
        "Confere uma planilha de lote contra um modelo (template) SEM renderizar nada: campo obrigatório "
        "vazio, arquivo inexistente, número ou lista ilegível, texto que não cabe no espaço, travessão (regra "
        "da marca). Cada problema vem com linha, coluna e motivo. A planilha é .csv (UTF-8, separador , ou ;), "
        ".xlsx (precisa do extra `lote`) ou .json (lista de objetos), uma linha por vídeo; o nome de cada "
        "coluna casa com o parâmetro do modelo sem diferenciar maiúscula, acento ou espaço; caminhos relativos "
        "partem da pasta da planilha. name_column é a coluna cujo texto dá nome ao arquivo de cada vídeo."
    )
)
def validate_batch(template: str, sheet: str, name_column: str | None = None) -> dict:
    validation = _batch_service().validate(template, sheet, name_column)
    return {**validation.to_dict(), "text": validation.to_text()}


@server.tool(
    description=(
        "Gera vários vídeos de uma vez: um por linha da planilha, sobre o modelo. Valida tudo antes (como "
        "validate_batch); se alguma linha tem problema, NÃO começa e devolve a validação, a não ser com "
        "skip_invalid=true, que segue sem as linhas inválidas. Cria um projeto por linha (projects/<lote>-<nome>) "
        "e renderiza em output/<lote>/<nome>.mp4 (preview=true gera prévias rápidas). Roda em segundo plano: "
        "devolve job_id; acompanhe com job_status ou batch_status. O que já saiu não é refeito na retomada "
        "(resume_batch). name é o nome do lote (padrão: o da planilha); replace=true refaz um lote de mesmo nome."
    )
)
def run_batch(
    template: str,
    sheet: str,
    name: str | None = None,
    name_column: str | None = None,
    skip_invalid: bool = False,
    preview: bool = False,
    preset: str | None = None,
    replace: bool = False,
    wait_seconds: float = 0,
) -> dict:
    from .pipeline.batch import BatchInvalidError

    try:
        batch = _batch_service().create(
            template,
            sheet,
            name=name,
            name_column=name_column,
            preview=preview,
            preset=preset,
            skip_invalid=skip_invalid,
            replace=replace,
        )
    except BatchInvalidError as exc:
        return {
            "started": False,
            "reason": str(exc),
            "validation": exc.validation.to_dict(),
            "text": exc.validation.to_text(),
        }
    return {"started": True, **_batch_job(batch.name, None, False, wait_seconds)}


@server.tool(
    description=(
        "Retoma um lote pausado, interrompido ou com falhas: renderiza o que falta, o que falhou e o projeto "
        "que você corrigiu depois; o que já saiu com a mesma spec não é refeito. rows (números da tabela de "
        "batch_status) limita a certos vídeos e force=true refaz também os prontos. Roda em segundo plano."
    )
)
def resume_batch(
    name: str, rows: list[int] | None = None, force: bool = False, wait_seconds: float = 0
) -> dict:
    return _batch_job(name, rows, force, wait_seconds)


@server.tool(
    description=(
        "Pede a um lote em andamento que pare depois do vídeo que está renderizando; nada é perdido e "
        "resume_batch continua de onde parou."
    )
)
def pause_batch(name: str) -> dict:
    _batch_service().pause(name)
    return {"batch": name, "pause_requested": True}


@server.tool(
    description=(
        "Relatório de um lote: para cada vídeo o estado (Pendente, Renderizando, Pronto, Falhou, Pulada), o "
        "arquivo de saída, o tempo e o motivo da falha; mais o resumo e a pasta de saída. Sem name, lista todos "
        "os lotes."
    )
)
def batch_status(name: str | None = None) -> dict:
    service = _batch_service()
    if name:
        report = service.report(name)
        return {**report.to_dict(), "text": report.to_text()}
    return {"batches": [{**report.to_dict(), "rows": len(report.rows)} for report in service.reports()]}


@server.tool(description="Projetos existentes em projects/.")
def list_projects() -> list[dict]:
    out = []
    for spec in sorted(config.PROJECTS_DIR.glob("*/spec.json")):
        try:
            data = json.loads(spec.read_text(encoding="utf-8"))
            out.append(
                {
                    "name": spec.parent.name,
                    "spec_path": str(spec),
                    "preset": data.get("output", {}).get("preset"),
                }
            )
        except (OSError, json.JSONDecodeError):
            out.append({"name": spec.parent.name, "spec_path": str(spec), "error": "spec ilegível"})
    return out


# ---------- render (jobs) ----------


def _dispatcher() -> RenderDispatcher:
    return RenderDispatcher(UIClient())


def _ui_job_url(client: UIClient, name_or_path: str, job_id: str) -> str:
    return f"{client.base_url}/#project={name_or_path}&job={job_id}"


def _wait_ui_job(client: UIClient, job_id: str, timeout: float) -> dict:
    """Espera até `timeout`, como `JobManager.wait`, mas consultando o snapshot na interface."""
    deadline = time.time() + timeout
    snapshot = client.job(job_id)
    while snapshot.get("status") == "running" and time.time() < deadline:
        time.sleep(0.25)
        snapshot = client.job(job_id)
    return snapshot


def _render_via_ui(name_or_path: str, options: dict, wait_seconds: float) -> dict | None:
    """Sobe a interface se preciso e dispara o render nela; None se a interface não puder ser usada,
    para quem chamou cair no job local de sempre."""
    dispatcher = _dispatcher()
    try:
        dispatcher.ensure_ui()
    except RuntimeError:
        return None
    started = dispatcher.client.render(name_or_path, options)
    job_id = started["job_id"]
    dispatcher.open_browser_if_needed(name_or_path, job_id)
    snapshot = _wait_ui_job(dispatcher.client, job_id, wait_seconds)
    return {**snapshot, "where": "ui", "url": _ui_job_url(dispatcher.client, name_or_path, job_id)}


def _export_via_ui(name_or_path: str, presets: list[str], wait_seconds: float) -> dict | None:
    dispatcher = _dispatcher()
    try:
        dispatcher.ensure_ui()
    except RuntimeError:
        return None
    started = dispatcher.client.export(name_or_path, presets)
    job_id = started["job_id"]
    dispatcher.open_browser_if_needed(name_or_path, job_id)
    snapshot = _wait_ui_job(dispatcher.client, job_id, wait_seconds)
    return {**snapshot, "where": "ui", "url": _ui_job_url(dispatcher.client, name_or_path, job_id)}


def _render(
    job: Job,
    name_or_path: str,
    preview: bool,
    preset: str | None,
    force: bool = False,
    guides: bool = False,
    no_captions: bool = False,
    segments: str | None = None,
) -> dict:
    """Roda um render ligado ao job (progresso e etapas viram eventos)."""
    from .media.ffmpeg import SubprocessRunner
    from .pipeline import RenderOptions, RenderPipeline
    from .pipeline.projects import load_project, parse_segments

    project = load_project(name_or_path)
    options = RenderOptions(
        preview=preview,
        preset=preset,
        force=force,
        guides=guides or None,
        no_captions=no_captions,
        quiet=True,
        segments=parse_segments(segments),
    )
    pipeline = RenderPipeline(project, options, runner=SubprocessRunner(sink=job.sink()), log=job.log)
    result = pipeline.run()
    payload = preview_notice(_result_dict(result), preview and not segments)
    if not preview and not segments:
        payload["qa"] = _qa_text_for_output(project, preset, result.output)
    return payload


def _qa_text_for_output(project: Project, preset: str | None, output: Path) -> str:
    """Relatório de QA completo (com a saída) para embutir no resultado de um render/export bem-sucedido.

    `preset` é o override usado no render (None = preset da spec); a comparação de resolução/fps precisa
    do preset que foi de fato renderizado, não do padrão do projeto."""
    from .media.ffmpeg import SubprocessRunner
    from .pipeline.report import build_report

    report_project = project
    if preset:
        report_project = project.model_copy(
            update={"output": project.output.model_copy(update={"preset": preset})}
        )
    try:
        report = build_report(report_project, output=output, runner=SubprocessRunner(quiet=True))
        return report.to_text()
    except Exception as exc:  # noqa: BLE001 - QA é um extra; não deve derrubar o render
        return f"QA não pôde ser gerado: {exc}"


@server.tool(
    description=(
        "Renderiza o projeto. preview=true gera uma versão rápida em baixa resolução para conferir. "
        "show_ui=true (padrão) abre a interface gráfica para o usuário acompanhar o andamento; use "
        "show_ui=false só se ele pedir para não abrir. Espera até wait_seconds; se ainda estiver "
        "rodando devolve job_id para consultar com job_status."
    )
)
def render_project(
    name_or_path: str,
    preview: bool = False,
    preset: str | None = None,
    force: bool = False,
    guides: bool = False,
    no_captions: bool = False,
    segments: str | None = None,
    wait_seconds: float = 600,
    show_ui: bool = True,
) -> dict:
    """`segments` = "12-20" renderiza só esses trechos (sem sobreposições/legendas), para revisar vídeos longos."""
    if preset:
        get_preset(preset)
    if show_ui:
        via_ui = _render_via_ui(
            name_or_path,
            {
                "preview": preview,
                "preset": preset,
                "force": force,
                "guides": guides,
                "no_captions": no_captions,
                "segments": segments,
            },
            wait_seconds,
        )
        if via_ui is not None:
            return via_ui
    job = jobs.start(
        f"render {name_or_path} ({'preview' if preview else preset or 'final'})",
        lambda job: _render(job, name_or_path, preview, preset, force, guides, no_captions, segments),
    )
    jobs.wait(job, wait_seconds)
    return {**job.snapshot(), "result": job.result}


@server.tool(
    description=(
        "Exporta o projeto para vários presets (ex.: instagram/reels, youtube/shorts). Devolve um job. "
        "show_ui=true (padrão) abre a interface gráfica para acompanhar; show_ui=false só se pedido."
    )
)
def export_project(
    name_or_path: str, presets: list[str], wait_seconds: float = 900, show_ui: bool = True
) -> dict:
    for p in presets:
        get_preset(p)
    if show_ui:
        via_ui = _export_via_ui(name_or_path, presets, wait_seconds)
        if via_ui is not None:
            return via_ui

    def work(job: Job) -> list[dict]:
        return [_render(job, name_or_path, False, p) for p in presets]

    job = jobs.start(f"export {name_or_path} -> {', '.join(presets)}", work)
    jobs.wait(job, wait_seconds)
    return {**job.snapshot(), "result": job.result}


@server.tool(
    description="Situação de um render em segundo plano (running | done | error | cancelled) e o resultado quando pronto."
)
def job_status(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is not None:
        return {**job.snapshot(), "result": job.result}
    try:
        return {**UIClient().job(job_id), "where": "ui"}
    except (OSError, ValueError):
        return {"error": f"job desconhecido: {job_id}"}


@server.tool(description="Jobs de render desta sessão e, se a interface estiver aberta, os dela também.")
def list_jobs() -> list[dict]:
    out = jobs.list()
    try:
        out += [{**j, "where": "ui"} for j in UIClient().jobs()]
    except (OSError, ValueError):
        pass
    return out


@server.tool(
    description="Edição rápida de um único vídeo: corte, formato e opcionais (legendas, logo, gancho, CTA, música)."
)
def quick_edit(
    src: str,
    preset: str = "instagram/reels",
    start: float = 0.0,
    end: float | None = None,
    reframe: str = "auto",
    brand: str | None = None,
    captions: bool = False,
    logo: bool = False,
    hook: str | None = None,
    cta: str | None = None,
    music: str | None = None,
    preview: bool = False,
    wait_seconds: float = 600,
) -> dict:
    from .pipeline import RenderOptions, RenderPipeline
    from .pipeline.projects import quick_project
    from .pipeline.projects import save_project as _save

    project = quick_project(
        Path(src),
        preset,
        start,
        end,
        reframe,
        brand,
        captions,
        logo,
        hook,
        cta,
        Path(music) if music else None,
    )
    spec_path = _save(project)

    def work(job: Job) -> dict:
        from .media.ffmpeg import SubprocessRunner

        pipeline = RenderPipeline(
            project,
            RenderOptions(preview=preview, quiet=True),
            runner=SubprocessRunner(sink=job.sink()),
            log=job.log,
        )
        return {"spec_path": str(spec_path), **preview_notice(_result_dict(pipeline.run()), preview)}

    job = jobs.start(f"quick {src}", work)
    jobs.wait(job, wait_seconds)
    return {**job.snapshot(), "result": job.result}


@server.tool(
    description=(
        "Sincroniza câmeras/gravadores do mesmo evento pelo áudio: devolve, para cada arquivo, o instante do "
        "relógio da fonte principal em que ele começa (para usar em sources.<nome>.sync)."
    )
)
def sync_sources(master: str, others: list[str], master_stream: int = 0, stream: int = 0) -> list[dict]:
    from .media.audiosync import sync_offset
    from .media.ffmpeg import SubprocessRunner

    runner = SubprocessRunner(quiet=True)
    out = []
    for other in others:
        result = sync_offset(
            runner, Path(master), Path(other), config.CACHE_DIR / "audio" / "sync", master_stream, stream
        )
        out.append(
            {
                "path": other,
                "offset_s": result.offset,
                "confidence": result.confidence,
                "reliable": result.reliable,
            }
        )
    return out


# ---------- legendas ----------


@server.tool(
    description=(
        "Transcreve um vídeo/áudio (Whisper local); salva .srt e .json. Por padrão devolve um resumo "
        "compacto (digest, cues suspeitas, texto corrido, sem tempo por palavra); full=true devolve o "
        "formato antigo, com todas as cues e tempos (gasta mais tokens)."
    )
)
def transcribe_media(
    path: str, language: str = "pt", model: str = "small", device: str = "cpu", full: bool = False
) -> dict:
    from .media.ffmpeg import SubprocessRunner
    from .text.captions import captions_digest, regroup, save_captions, suspicious_cues
    from .text.transcribe import WhisperTranscriber, extract_audio_wav

    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {src}")
    wav = extract_audio_wav(
        SubprocessRunner(quiet=True), src, config.CACHE_DIR / "audio" / f"{src.stem}.16k.wav"
    )
    transcript = WhisperTranscriber(model=model, device=device).transcribe(wav, language)
    json_path = save_captions(transcript.cues, src.with_suffix(".json"), language)
    srt_path = save_captions(regroup(transcript.cues), src.with_suffix(".srt"))
    if full:
        return {
            "json": str(json_path),
            "srt": str(srt_path),
            "meta": transcript.meta,
            "cues": [{"start": c.start, "end": c.end, "text": c.text} for c in transcript.cues],
        }
    return {
        "json": str(json_path),
        "srt": str(srt_path),
        "meta": transcript.meta,
        "digest": captions_digest(transcript.cues),
        "issues": [_issue_dict(i) for i in suspicious_cues(transcript.cues)],
        "text": " ".join(c.text for c in transcript.cues),
    }


def _issue_dict(issue: Any) -> dict:
    return {
        "index": issue.index,
        "start": issue.start,
        "end": issue.end,
        "text": issue.text,
        "reasons": issue.reasons,
    }


def _captions_vocabulary_and_replacements(project: Project) -> tuple[list[str], dict[str, str]]:
    """Vocabulário e substituições combinando o tema da marca (se houver) com a spec do projeto."""
    vocabulary: list[str] = []
    replacements: dict[str, str] = {}
    if project.brand:
        theme = load_theme(project.brand)
        vocabulary += list(theme.captions.get("vocabulary", []))
        replacements.update(theme.captions.get("replacements", {}))
    if project.captions:
        vocabulary += list(project.captions.vocabulary)
        replacements.update(project.captions.replacements)
    return vocabulary, replacements


@server.tool(
    description=(
        "Lê as legendas automáticas do projeto (captions.auto.json). mode=compact (padrão) devolve um "
        "resumo (digest) e só as cues suspeitas (baixa confiança, termo da marca, cue longa/curta, "
        "substituição pendente); mode=full devolve tudo, com tempo por palavra (gasta muito mais tokens "
        "num vídeo longo). Corrija o que aparecer com `fix_captions`."
    )
)
def read_captions(name_or_path: str, mode: Literal["compact", "full"] = "compact", limit: int = 40) -> dict:
    from .pipeline.projects import load_project, project_path
    from .text.captions import captions_digest, from_json, suspicious_cues

    store = project_path(name_or_path).parent / "captions.auto.json"
    if not store.exists():
        return {"error": "sem legendas automáticas ainda; renderize o projeto com captions.source = auto"}
    data = json.loads(store.read_text(encoding="utf-8"))
    if mode == "full":
        return data
    cues = from_json(json.dumps(data))
    try:
        vocabulary, replacements = _captions_vocabulary_and_replacements(load_project(name_or_path))
    except (FileNotFoundError, ValueError):
        vocabulary, replacements = [], {}
    issues = suspicious_cues(cues, vocabulary, replacements)[:limit]
    return {
        "digest": captions_digest(cues),
        "issues": [_issue_dict(i) for i in issues],
        "hint": "use fix_captions para corrigir; mode=full para tudo",
    }


@server.tool(
    description=(
        'Corrige o texto de palavras das legendas automáticas: pares {"errado": "certo"} aplicados a todas as '
        "cues do projeto (sem acento/caixa). O próximo render usa o texto corrigido."
    )
)
def fix_captions(name_or_path: str, replacements: dict[str, str]) -> dict:
    from .pipeline.projects import project_path
    from .text.captions import apply_replacements, from_json, to_json

    store = project_path(name_or_path).parent / "captions.auto.json"
    if not store.exists():
        raise FileNotFoundError(
            "captions.auto.json não existe; renderize com captions.source = auto primeiro"
        )
    data = json.loads(store.read_text(encoding="utf-8"))
    cues = apply_replacements(from_json(json.dumps(data)), replacements)
    payload = json.loads(to_json(cues, data.get("language", "pt")))
    payload.update({k: v for k, v in data.items() if k not in ("cues", "language")})
    store.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"file": str(store), "cues": len(cues), "replacements": replacements}


# ---------- conferência visual (devolve imagens) ----------


@server.tool(
    description=(
        "Grade de quadros do vídeo inteiro numa única imagem, para revisar composição e texto. Custa "
        "tokens de imagem: use só quando qa_report apontar algo ou o usuário pedir para olhar."
    ),
    structured_output=False,
)
def contact_sheet(video: str, cols: int = 3, rows: int = 3, width: int = 320) -> list:
    from .pipeline.qa import contact_sheet as _sheet

    src = Path(video)
    out = _sheet(src, src.with_name(f"{src.stem}_sheet.png"), cols, rows, width)
    return [{"image": str(out), "cols": cols, "rows": rows}, Image(path=out)]


@server.tool(
    description=(
        "Relatório de QA em texto: checagens automáticas que não precisam de olho humano (zona segura, "
        "ritmo de leitura, sobreposições, contraste, legendas e, com output=true, a saída renderizada: "
        "duração, resolução, quadros pretos, silêncio, loudness). Rode antes de contact_sheet/frames; "
        "essas duas só quando o relatório apontar algo ou o usuário pedir para olhar."
    )
)
def qa_report(name_or_path: str, output: bool = True) -> dict:
    from .media.ffmpeg import SubprocessRunner
    from .pipeline.projects import load_project
    from .pipeline.report import build_report

    project = load_project(name_or_path)
    out_path = _latest_final_output(project) if output else None
    runner = SubprocessRunner(quiet=True) if out_path else None
    report = build_report(project, output=out_path, runner=runner)
    return {"text": report.to_text(), **report.to_dict()}


def _latest_final_output(project: Project) -> Path | None:
    """A última saída final (não preview) já renderizada para o preset da spec, se houver."""
    if not config.OUTPUT_DIR.exists():
        return None
    preset_id = get_preset(project.output.preset).id.replace("/", "-")
    files = sorted(
        config.OUTPUT_DIR.glob(f"{project.name}__{preset_id}.mp4"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


@server.tool(
    description=(
        "Quadros em instantes específicos do vídeo (segundos), devolvidos como imagens. Custa tokens de "
        "imagem: use só quando qa_report apontar algo ou o usuário pedir para olhar."
    ),
    structured_output=False,
)
def frames(video: str, times: list[float], width: int = 540) -> list:
    from .pipeline.qa import frame_at

    src = Path(video)
    out_dir = src.parent / f"{src.stem}_frames"
    contents: list = []
    for t in times:
        path = frame_at(src, t, out_dir / f"{src.stem}_{t:06.2f}s.jpg", width)
        contents.append({"time_s": t, "image": str(path)})
        contents.append(Image(path=path))
    return contents


@server.tool(
    description=(
        "Renderiza um quadro de uma composição HTML (a animação que você escreveu em HTML, CSS e JavaScript, "
        "inclusive three.js e Lottie) no instante `at`, direto nele, e devolve a imagem. Use antes de pôr a "
        "composição no projeto, para conferir o desenho, o tamanho e os avisos (rede bloqueada, erro de "
        "JavaScript). `src` é o arquivo .html ou a pasta com index.html (relativo à pasta do projeto, se "
        "`project` vier); `size` é LARGURAxALTURA em px na base 1080 (a área onde a composição entra); `data` "
        "chega à página como dmaker.data; `background` é a cor por baixo, para ver o transparente. Custa tokens "
        "de imagem."
    ),
    structured_output=False,
)
def render_html_frame(
    src: str,
    at: float = 0.0,
    size: str = "1080x1920",
    duration: float = 5.0,
    data: dict | None = None,
    brand: str | None = None,
    project: str | None = None,
    background: str = "#808080",
) -> list:
    from .pipeline.html_frame import default_frame_path, parse_size
    from .pipeline.html_frame import render_html_frame as _render_frame
    from .pipeline.projects import load_project

    source = load_project(project).resolve(src) if project else Path(src)
    result = _render_frame(
        source,
        default_frame_path(config.OUTPUT_DIR, source, at),
        at=at,
        size=parse_size(size),
        duration=duration,
        data=data,
        brand=brand,
        background=background,
    )
    return [
        {
            "image": str(result.path),
            "at_s": at,
            "size": f"{result.size[0]}x{result.size[1]}",
            "warnings": result.warnings,
        },
        Image(path=result.path),
    ]


@server.tool(
    description=(
        "Põe uma composição HTML (type html) nas sobreposições do projeto e salva. `src` é o arquivo .html ou a "
        "pasta com index.html, relativo à pasta do projeto. O lugar é uma `region` do projeto ou o centro "
        "`x`/`y` com `width`/`height` (frações do quadro; sem nada, o quadro todo). `layer` é `front` ou "
        "`behind-person` (atrás da pessoa); `data` chega à página como dmaker.data; `motion_blur` liga o "
        "borrão de movimento. Confira o desenho com render_html_frame antes e rode validate_project depois."
    )
)
def add_html_overlay(
    name: str,
    src: str,
    start: float = 0.0,
    end: float | None = None,
    region: str | None = None,
    x: float | None = None,
    y: float | None = None,
    width: float | None = None,
    height: float | None = None,
    layer: Literal["front", "behind-person"] = "front",
    data: dict | None = None,
    motion_blur: bool = False,
) -> dict:
    from .pipeline.html_frame import insert_html_overlay
    from .pipeline.projects import load_project, summarize
    from .pipeline.projects import save_project as _save

    overlay: dict[str, Any] = {"src": src, "start": start, "layer": layer, "motion_blur": motion_blur}
    for field_name, value in (
        ("end", end),
        ("region", region),
        ("x", x),
        ("y", y),
        ("width", width),
        ("height", height),
        ("data", data),
    ):
        if value is not None:
            overlay[field_name] = value
    project = insert_html_overlay(load_project(name), overlay)
    path = _save(project)
    return {
        "spec_path": str(path),
        "overlay_index": len(project.overlays) - 1,
        **_summary_dict(summarize(project)),
    }


@server.tool(
    description=(
        "Os infográficos animados prontos (contador, barra, linha, imagem, etiqueta, grifo, emoji): para cada "
        "um, o nome, a descrição e o esquema dos parâmetros (nome, tipo, padrão, limites e rótulo em "
        "português), para você usar sem ler o HTML. Ponha um no projeto com `add_infographic`; confira o "
        "desenho com `render_infographic_frame`."
    )
)
def list_infographics() -> list[dict]:
    from .pipeline.infographics import describe_infographics

    return describe_infographics()


@server.tool(
    description=(
        "Põe um infográfico pronto (ver `list_infographics`) nas sobreposições do projeto e salva. `name` é o "
        'nome do modelo, como `contador`; `params` são os parâmetros dele (ex.: {"ate": 10000, "prefixo": '
        '"+ de R$"}); `start`/`end` em segundos (`end` vazio vai até o fim do vídeo); `region` é uma região '
        "do projeto (ex.: `topo`), ou `x`/`y` com `width`/`height` em fração do quadro; sem lugar dito o modelo "
        "entra na área própria dele. Valor fora do esquema falha dizendo qual. Rode validate_project depois."
    )
)
def add_infographic(
    project: str,
    name: str,
    params: dict | None = None,
    start: float = 0.0,
    end: float | None = None,
    region: str | None = None,
    x: float | None = None,
    y: float | None = None,
    width: float | None = None,
    height: float | None = None,
    layer: Literal["front", "behind-person"] = "front",
) -> dict:
    from .pipeline.infographics import add_infographic as _add
    from .pipeline.projects import load_project, summarize
    from .pipeline.projects import save_project as _save

    loaded = load_project(project)
    updated = _add(
        loaded,
        name,
        params,
        start=start,
        end=end,
        region=region,
        x=x,
        y=y,
        width=width,
        height=height,
        layer=layer,
    )
    path = _save(updated)
    return {
        "spec_path": str(path),
        "overlay_index": len(updated.overlays) - 1,
        **_summary_dict(summarize(updated)),
    }


@server.tool(
    description=(
        "Renderiza um quadro de um infográfico pronto com os parâmetros pedidos e devolve a imagem, para "
        "conferir antes de pôr no projeto. `at` é o instante (padrão: o modelo já desenhado), `size` é "
        "LARGURAxALTURA em px na base 1080 (padrão: o tamanho do modelo), `brand` a marca (cores, fonte e "
        "cantos), `background` a cor por baixo, para ver o transparente. Custa tokens de imagem."
    ),
    structured_output=False,
)
def render_infographic_frame(
    name: str,
    params: dict | None = None,
    at: float | None = None,
    size: str | None = None,
    brand: str | None = None,
    project: str | None = None,
    background: str = "#0F172A",
) -> list:
    from .pipeline.html_frame import default_frame_path, parse_size
    from .pipeline.infographics import infographic_frame
    from .pipeline.projects import load_project

    loaded = load_project(project) if project else None
    result = infographic_frame(
        name,
        default_frame_path(config.OUTPUT_DIR, Path(name), at or 0.0),
        params=params,
        at=at,
        size=parse_size(size) if size else None,
        brand=brand or (loaded.brand if loaded else None),
        background=background,
        project=loaded,
    )
    return [
        {
            "image": str(result.path),
            "size": f"{result.size[0]}x{result.size[1]}",
            "warnings": result.warnings,
        },
        Image(path=result.path),
    ]


@server.tool(
    description="Gera um cartão (PNG) com o visual da marca, para aprovar o design antes do render.",
    structured_output=False,
)
def render_card_preview(
    title: str,
    subtitle: str | None = None,
    brand: str = "medlycare",
    preset: str = "instagram/reels",
    variant: str | None = None,
) -> list:
    from .visuals.cards import render_card, save_card

    theme = load_theme(brand)
    p = get_preset(preset).preview(540)
    out = config.OUTPUT_DIR / f"card_{p.id.replace('/', '-')}_preview.png"
    save_card(render_card(theme, p.width, p.height, title, subtitle, variant, True, None, p.safe), out)
    return [{"image": str(out)}, Image(path=out)]


@server.tool(description="Limpa o cache de trechos intermediários (força regerar tudo no próximo render).")
def clean_cache() -> dict:
    import shutil

    n = sum(1 for _ in config.MEZ_DIR.iterdir()) if config.MEZ_DIR.exists() else 0
    shutil.rmtree(config.MEZ_DIR, ignore_errors=True)
    config.ensure_dirs()
    return {"removed": n}


# ---------- modelos de IA ----------


def _model_download_work(job: Job, model_id: str) -> dict:
    from .pipeline.models_service import job_progress_reporter, shared_service

    service = shared_service()
    report = job_progress_reporter(job, service.spec(model_id).name)
    return service.download(model_id, report).to_dict()


@server.tool(
    description=(
        "Gerencia os modelos de IA em cache/models (OmniVoice, Kokoro, Demucs, Whisper, recorte de pessoa). "
        "action=list: estado de cada modelo (baixado, parcial ou ausente), tamanho real em disco, licença, "
        "para que serve e quais funções dependem dele, mais as sobras (arquivos que nenhum modelo usa), o total "
        "ocupado e o espaço livre. action=download com model_id: baixa em segundo plano e confere o arquivo "
        "(devolve job_id, consulte com job_status; os de ~3 GB levam minutos). action=remove com model_id e "
        "action=prune (apaga as sobras) EXIGEM confirm=true: sem ele nada é apagado e o erro traz o aviso de "
        "quais funções deixam de funcionar. O disco costuma estar cheio: confira o espaço livre antes de baixar."
    )
)
def models(
    action: Literal["list", "download", "remove", "prune"] = "list",
    model_id: str | None = None,
    confirm: bool = False,
    wait_seconds: float = 0,
) -> dict:
    from .pipeline.models_service import ConfirmationRequired, shared_service

    service = shared_service()
    if action == "list":
        return service.inventory().to_dict()
    if action == "prune":
        try:
            return {"removed": service.prune(confirm=confirm).to_dict()}
        except ConfirmationRequired as exc:
            raise ValueError(f"{exc} Repita a chamada com confirm=true.") from exc
    if not model_id:
        raise ValueError(f"A ação {action} precisa de model_id (use action=list para ver os ids).")
    if action == "remove":
        try:
            return {"removed": service.remove(model_id, confirm=confirm).to_dict()}
        except ConfirmationRequired as exc:
            raise ValueError(f"{exc} Repita a chamada com confirm=true.") from exc
    spec = service.spec(model_id)
    job = jobs.start(f"baixar modelo ({spec.name})", lambda job: _model_download_work(job, model_id))
    jobs.wait(job, wait_seconds)
    return {**job.snapshot(), "result": job.result}


# ---------- voz e narração ----------


@server.tool(
    description=(
        "Vozes da biblioteca: as prontas (dora, alex, santa; motor kokoro, rápido) e as suas (clones e "
        "projetadas; motor omnivoice, lento). Com brand, as dessa marca mais as sem marca. Cada voz tem id, "
        "engine, kind (preset | clone | design), idioma e, nas projetadas, o instruct."
    )
)
def list_voices(brand: str | None = None) -> list[dict]:
    from .pipeline.voices import profile_dict

    return [profile_dict(p) for p in _voice_library().list(brand=brand)]


@server.tool(
    description=(
        "Clona uma voz a partir de uma gravação de 3 a 15 s de fala limpa (usa só o começo, sem silêncio). "
        "Sem reference_text, o Whisper transcreve a gravação. Devolve a voz cadastrada (use o id em "
        "synthesize_speech)."
    )
)
def clone_voice(
    name: str,
    reference_audio: str,
    reference_text: str | None = None,
    brand: str | None = None,
    language: str = "pt",
) -> dict:
    from .pipeline.voices import clone_voice as _clone
    from .pipeline.voices import profile_dict

    profile = _clone(
        name,
        Path(reference_audio),
        reference_text=reference_text,
        brand=brand,
        language=language,
        library=_voice_library(),
    )
    return profile_dict(profile)


@server.tool(
    description=(
        "Cria uma voz descrevendo como ela soa, sem gravação. Atributos aceitos: gender (male | female), "
        "age (child, teenager, young adult, middle-aged, elderly), pitch (very low pitch, low pitch, "
        "moderate pitch, high pitch, very high pitch), accent (por exemplo british accent, portuguese "
        "accent), whisper. Aceita apelidos em português (feminino, grave, idoso...) ou um instruct "
        "completo, como 'female, low pitch'."
    )
)
def design_voice(
    name: str,
    gender: str | None = None,
    age: str | None = None,
    pitch: str | None = None,
    accent: str | None = None,
    whisper: bool = False,
    instruct: str | None = None,
    brand: str | None = None,
    language: str = "pt",
) -> dict:
    from .pipeline.voices import design_voice as _design
    from .pipeline.voices import profile_dict

    profile = _design(
        name, gender, age, pitch, accent, whisper, instruct, brand, language, library=_voice_library()
    )
    return profile_dict(profile)


def _narration_work(job: Job, text: str, out: str | None, options: dict) -> dict:
    """Narração ligada ao job: cada fala vira progresso e evento."""
    from .pipeline.voices import speak

    def on_progress(done: int, total: int) -> None:
        job.progress = {
            "label": f"fala {done} de {total}",
            "done": done,
            "total": total,
            "percent": int(100 * (done - 1) / total),
        }

    result = speak(
        text,
        Path(out) if out else None,
        on_progress=on_progress,
        log=job.log,
        library=_voice_library(),
        synthesizer=_voice_synthesizer(),
        lexicons=_lexicon_store(),
        **options,
    )
    return {
        "output": str(result.path),
        "duration_s": round(result.duration, 2),
        "srt": str(result.srt_path) if result.srt_path else None,
        "cues": [{"start": round(s, 2), "end": round(e, 2), "text": t} for s, e, t in result.cues],
    }


@server.tool(
    description=(
        "Narra um texto com uma voz da biblioteca (voice = id; sem voice, o OmniVoice com voz automática, ou "
        "desenhada se houver instruct) e grava o áudio (.wav, .mp3 ou .m4a). Qualidade: OmniVoice com 16 "
        "passos; draft=true usa 8 (rascunho). Roda em segundo plano porque na CPU demora (OmniVoice: ~50 s "
        "por segundo de áudio, ~25 s no rascunho; vozes prontas dora/alex/santa do Kokoro: ~3 s por "
        "segundo; falas repetidas vêm do cache): devolve job_id, consulte com job_status. Pausas: linha em "
        "branco = pausa de parágrafo; [pausa 1.2] fixa uma pausa. "
        "Números, R$ e % são lidos por extenso. Pronúncia: o dicionário da ferramenta pronunciation vale "
        "(global mais o da marca brand; sem brand, o da marca da voz); [[termo|pronúncia]] no texto fixa "
        "uma só ocorrência. Legendas e SRT mantêm o texto escrito."
    )
)
def synthesize_speech(
    text: str,
    out: str | None = None,
    voice: str | None = None,
    language: str | None = None,
    speed: float = 1.0,
    instruct: str | None = None,
    seed: int | None = None,
    steps: int | None = None,
    srt: bool = False,
    draft: bool = False,
    wait_seconds: float = 0,
    brand: str | None = None,
) -> dict:
    from .voice.synth import DRAFT_STEPS

    if voice:
        _voice_library().get(voice)  # falha já na chamada (e não só no job) se a voz não existe
    options = {
        "voice_id": voice,
        "language": language,
        "speed": speed,
        "instruct": instruct,
        "seed": seed,
        "steps": DRAFT_STEPS if draft and steps is None else steps,
        "write_srt": srt,
        "brand": brand,
    }
    job = jobs.start(
        f"narração ({voice or 'voz automática'}, {len(text)} caracteres)",
        lambda job: _narration_work(job, text, out, options),
    )
    jobs.wait(job, wait_seconds)
    return {**job.snapshot(), "result": job.result}


def _voice_queue_service():
    from .pipeline.voice_queue_service import VoiceQueueService

    return VoiceQueueService(library=_voice_library())


@server.tool(
    description=(
        "Põe uma narração longa (audiobook, manual narrado, vários roteiros) na fila de narrações, que roda "
        "um item por vez e retoma de onde parou se o processo cair. Informe text (capítulos marcados com "
        "'# Título' ou 'Capítulo N' viram arquivos separados) ou file_path (.txt, .md ou .docx; títulos viram "
        "capítulos). Cada item gera output/narracoes/<título>/NN-<capítulo>.wav, o <título>-completo.wav "
        "com 1,5 s entre capítulos e o .srt do completo. voice = id da voz; draft=true usa 8 passos no "
        "OmniVoice (rascunho); format = wav | mp3. A ferramenta só enfileira: quem executa é o `dmaker ui` "
        "aberto ou o comando `dmaker voice queue run`. Acompanhe com voice_queue_list."
    )
)
def voice_queue_add(
    text: str | None = None,
    file_path: str | None = None,
    voice: str | None = None,
    title: str | None = None,
    draft: bool = False,
    format: Literal["wav", "mp3"] = "wav",
    language: str | None = None,
    speed: float = 1.0,
    brand: str | None = None,
) -> dict:
    from .pipeline.voice_queue import STATE_LABELS, QueueOptions

    if bool(text) == bool(file_path):
        raise ValueError("Informe text ou file_path, um dos dois.")
    options = QueueOptions(
        voice=voice, language=language, speed=speed, brand=brand, draft=draft, audio_format=format
    )
    service = _voice_queue_service()
    item = (
        service.add_text(text, options, title) if text else service.add_path(Path(file_path), options, title)
    )
    return {
        "id": item.id,
        "title": item.title,
        "chapters": item.chapters_total,
        "output_dir": item.output_dir,
        "state": STATE_LABELS[item.state],
        "runs_with": "dmaker ui aberto ou dmaker voice queue run",
    }


@server.tool(
    description=(
        "Lista a fila de narrações: estado de cada item (Pendente, Rodando, Pausado, Cancelado, Concluído, "
        "Falhou), capítulo e fala em andamento, porcentagem, tempo estimado restante (medido nesta máquina) "
        "e os arquivos prontos. eta_label no topo é o tempo para esvaziar a fila."
    )
)
def voice_queue_list() -> dict:
    view = _voice_queue_service().view()
    for item in view["items"]:
        item["files"] = [f["name"] for f in item["files"]]
    return view


@server.tool(
    description=(
        "Confere se um áudio ou vídeo (wav, mp3, m4a, mp4...) tem voz gerada por IA pelo DMaker. Lê primeiro "
        "a etiqueta de procedência que o DMaker grava nos arquivos com voz sintética (diz também os trechos); "
        "sem etiqueta, analisa a marca d'água inaudível do áudio (cerca de meio segundo por segundo de áudio, "
        "mais o carregamento do modelo na primeira vez). Devolve level (found = encontrada, indication = "
        "indício, inconclusivo: música e tons puros podem imitar a marca e só a assinatura de 16 bits confirma; "
        "absent = não encontrada), origin (label | audio), detected (só para found), probability (fração de "
        "quadros do áudio, 0 a 1), matched_bits (de 16), spans (trechos da etiqueta, em segundos) e verdict "
        "em português. check_audio=true analisa o áudio também quando há etiqueta (audio_level). A marca e a "
        "etiqueta estão ligadas por padrão e DMAKER_WATERMARK=0 desliga as duas; a verificação funciona sempre. "
        "Limite: um vídeo recodificado fora do DMaker perde a etiqueta, e uma fala curta num vídeo longo pode "
        "não ser achada pelo áudio."
    )
)
def verify_watermark(path: str, check_audio: bool = False) -> dict:
    from .pipeline.voices import verify_watermark as _verify
    from .pipeline.voices import watermark_verdict

    result = _verify(Path(path), check_audio=check_audio)
    return {
        "level": result.verdict,
        "origin": result.origin,
        "detected": result.detected,
        "probability": result.probability,
        "matched_bits": result.matched_bits,
        "spans": [list(span) for span in result.spans],
        "audio_level": result.audio_verdict,
        "verdict": watermark_verdict(result),
    }


@server.tool(
    description=(
        "Dicionário de pronúncia da narração: como a voz fala cada termo (ex.: DMaker -> Di-mêiker). "
        "action = list | add | remove. Cada entrada vale para um idioma (language, padrão pt; pt-BR e pt "
        "são o mesmo): a grafia feita para o português não vale na fala em inglês, onde o termo é lido "
        "como está. Sem brand é o global (todas as marcas); com brand, o da marca, que vale por cima do "
        "global. list devolve as entradas do escopo no idioma, 'effective' (o que a narração usa nesse "
        "idioma) e 'languages' (idiomas com entradas no escopo). add pede term e spoken. Só a fala muda, "
        "legendas mantêm o texto escrito. Para uma única ocorrência, em qualquer idioma, escreva "
        "[[termo|pronúncia]] direto no texto."
    )
)
def pronunciation(
    action: Literal["list", "add", "remove"],
    term: str | None = None,
    spoken: str | None = None,
    brand: str | None = None,
    language: str = "pt",
) -> dict:
    from .voice.pronunciation import language_code

    store = _lexicon_store()
    if action == "add":
        if not term or not spoken:
            raise ValueError("add pede term e spoken.")
        store.add(term, spoken, brand, language)
    elif action == "remove":
        if not term:
            raise ValueError("remove pede term.")
        store.remove(term, brand, language)
    return {
        "scope": brand or "global",
        "language": language_code(language),
        "entries": store.list(brand, language).as_dict(),
        "effective": store.for_brand(brand, language).as_dict(),
        "languages": list(store.by_language(brand)),
    }


def _lexicon_store():
    from .voice.lexicon_store import LexiconStore

    return LexiconStore()


def _voice_library():
    from .voice.library import VoiceLibrary

    return VoiceLibrary()


def _voice_synthesizer():
    from .pipeline.voices import shared_synthesizer

    return shared_synthesizer()


# ---------- receitas: várias ferramentas numa chamada só ----------


@contextmanager
def _recipe_errors() -> Iterator[None]:
    """Erro de pedido que a receita antecipou (assunto sem fim, texto vazio) chega ao cliente com a mensagem."""
    from mcp.server.mcpserver.exceptions import ToolError

    from .pipeline.recipes import RecipeError

    try:
        yield
    except RecipeError as exc:
        raise ToolError(str(exc)) from exc


@server.tool(
    description=(
        "Receita: narra um roteiro e já o põe no projeto, em uma chamada (no lugar de edit_project para "
        "audio.narration, edit_project para as legendas e validate_project). Soma a fala às narrações que o "
        "projeto já tinha, usa o texto falado como legenda (captions=true) e devolve o resumo com os avisos "
        "(voz inexistente, narração que passa do fim do vídeo). Nada é sintetizado agora: a voz sai no render "
        "e vai para o cache. voice = id de list_voices (dora, alex, santa ou uma sua); sem voice, a voz "
        "automática. start = segundo do vídeo em que a fala começa."
    )
)
def narrate_into_project(
    name_or_path: str,
    text: str,
    voice: str | None = None,
    start: float = 0.0,
    language: str = "pt",
    speed: float = 1.0,
    seed: int | None = None,
    captions: bool = True,
) -> dict:
    from .pipeline.projects import summarize
    from .pipeline.recipes import NarrationRequest
    from .pipeline.recipes import narrate_into_project as _narrate

    request = NarrationRequest(
        text=text, voice=voice, start=start, language=language, speed=speed, seed=seed, captions=captions
    )
    with _recipe_errors():
        project, path = _narrate(name_or_path, request, check_voice=_voice_library().get)
    return {
        "spec_path": str(path),
        "narrations": len(project.audio.narration),
        **_summary_dict(summarize(project)),
    }


@server.tool(
    description=(
        "Receita: corta as pausas, os vícios e as repetições de uma gravação falada E deixa a legenda "
        "pronta, em uma chamada que espera o fim (no lugar de autocut, job_status e list_cuts). Cria o projeto "
        "`name` com os clipes cortados e as legendas seguindo a fala cortada, e devolve o essencial: "
        "duração antes e depois, quanto saiu e os cortes por motivo. intensity: suave (só pausas), normal "
        "(pausas e vícios) ou agressiva (inclui falsos começos e frases repetidas). Transcreve com o "
        "Whisper: cerca de 1 minuto por minuto de gravação na CPU. Confira os cortes com list_cuts e "
        "desfaça um com undo_cut; gere a prévia com render_project."
    )
)
def cut_pauses_and_caption(
    source: str,
    name: str,
    intensity: Literal["suave", "normal", "agressiva"] = "normal",
    preset: str = "instagram/reels",
    brand: str | None = None,
    language: str = "pt",
    model: str = "small",
    overwrite: bool = False,
    wait_seconds: float = 1800,
) -> dict:
    from .pipeline.autocut import AutoCutRequest
    from .pipeline.recipes import cut_summary
    from .voice.cut_plan import CutOptions

    request = AutoCutRequest(
        source=Path(source),
        name=name,
        options=CutOptions(intensity=intensity),
        preset=preset,
        brand=brand,
        captions=True,
        language=language,
        model=model,
        overwrite=overwrite,
    )
    _autocut_service().validate(request)  # o erro de nome, arquivo ou formato aparece já, não só no job
    job = jobs.start(f"cortar pausas e legendar {name}", lambda job: _autocut_work(job, request))
    jobs.wait(job, wait_seconds)
    if job.status == "done":
        return cut_summary(job.result)
    return {**job.snapshot(), "result": job.result}


@server.tool(
    description=(
        "Receita: monta o vídeo explicativo (o rosto num quadro arredondado embaixo, a imagem de cada "
        "assunto em cima e o fundo trocando a cada assunto) em uma chamada, no lugar de probe_media, "
        "new_from_template e validate_project. subjects = lista de assuntos em ordem, cada um com 'fim' "
        "(segundo em que termina), 'fundo' (escuro, claro, bege, #RRGGBB ou caminho de imagem), 'imagem' "
        '(caminho) e \'infografico\' ({"nome": "contador", "parametros": {...}}, ver list_infographics): '
        "'fim' vale para todos os assuntos ou para nenhum (sem ele, a gravação é dividida em partes iguais) e os "
        "outros são opcionais. Devolve o resumo do projeto (duração e avisos). caption_mode: rounded, karaoke, "
        "classic ou boxed."
    )
)
def build_explainer_video(
    name: str,
    recording: str,
    subjects: list[dict],
    captions: bool = True,
    caption_mode: str | None = None,
    brand: str | None = None,
) -> dict:
    from .pipeline.projects import project_path, summarize
    from .pipeline.recipes import build_explainer

    options: dict[str, Any] = {"legendas": captions}
    if caption_mode:
        options["legenda_modo"] = caption_mode
    if brand:
        options["marca"] = brand
    with _recipe_errors():
        project = build_explainer(name, recording, subjects, options)
    return {"spec_path": str(project_path(name)), **_summary_dict(summarize(project))}


# ---------- isolamento vocal ----------


def _isolation_work(
    job: Job, path: str, start: float | None, end: float | None, out_dir: str | None, audio_format: str
) -> dict:
    """Isolamento ligado ao job: cada bloco do modelo vira progresso."""
    from .media.ffmpeg import SubprocessRunner
    from .pipeline.isolation import default_isolation_service

    def on_progress(done: int, total: int) -> None:
        job.progress = {
            "label": f"bloco {done} de {total}",
            "done": done,
            "total": total,
            "percent": int(100 * done / max(total, 1)),
        }

    service = default_isolation_service(SubprocessRunner(sink=job.sink()), job.log)
    stems = service.export(
        Path(path),
        Path(out_dir) if out_dir else config.OUTPUT_DIR / "isolamento",
        audio_format,  # type: ignore[arg-type]
        start,
        end,
        on_progress=on_progress,
    )
    return {"voice": str(stems.vocals), "background": str(stems.background)}


@server.tool(
    description=(
        "Isola a voz: separa a fala (voice) da música e do ruído de fundo (background) de um vídeo ou áudio, "
        "ou de um trecho dele (start/end em segundos no arquivo), com o Demucs local. Grava dois arquivos em "
        "out_dir (padrão output/isolamento; format wav ou mp3). Lento na CPU (~3x a 6x a duração do trecho, "
        "mais ~30 s para carregar o modelo na primeira vez; o resultado fica em cache): devolve job_id, "
        "consulte com job_status. Para usar no vídeo sem exportar, ponha audio_mode voice ou background "
        "no clipe."
    )
)
def isolate_vocals(
    path: str,
    start: float | None = None,
    end: float | None = None,
    out_dir: str | None = None,
    format: Literal["wav", "mp3"] = "wav",
    wait_seconds: float = 0,
) -> dict:
    if not Path(path).exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    job = jobs.start(
        f"isolamento vocal ({Path(path).name})",
        lambda job: _isolation_work(job, path, start, end, out_dir, format),
    )
    jobs.wait(job, wait_seconds)
    return {**job.snapshot(), "result": job.result}


# ---------- correção de fala ----------


def _speech_fix_service(job: Job):
    """Serviço de correção de fala ligado ao job (progresso do ffmpeg e do modelo viram eventos)."""
    from .media.ffmpeg import SubprocessRunner
    from .pipeline.speech_fix import default_speech_fix_service

    return default_speech_fix_service(
        SubprocessRunner(sink=job.sink()),
        job.log,
        library=_voice_library(),
        synthesizer=_voice_synthesizer(),
        lexicons=_lexicon_store(),
    )


def _stage_progress(job: Job):
    """Etapa e fração do serviço viram o progresso do job."""

    def report(label: str, fraction: float) -> None:
        job.progress = {
            "label": label,
            "done": round(fraction * 100),
            "total": 100,
            "percent": round(fraction * 100),
        }

    return report


def _speech_words_work(job: Job, path: str, start: float | None, end: float | None, language: str) -> dict:
    words = _speech_fix_service(job).transcribe_words(Path(path), start, end, language)
    return {
        "words": [[round(w.start, 2), round(w.end, 2), w.text] for w in words],
        "text": " ".join(w.text for w in words),
    }


@server.tool(
    description=(
        "Lista as palavras ditas num vídeo ou áudio com o tempo de cada uma (Whisper local), para escolher o "
        "trecho de fix_speech. start/end (segundos no arquivo) limitam a transcrição; em vídeos longos, "
        "sempre use. Roda em segundo plano: devolve job_id, consulte com job_status; o resultado traz "
        "words ([início, fim, palavra]) e text. Fica em cache."
    )
)
def speech_words(
    path: str,
    start: float | None = None,
    end: float | None = None,
    language: str = "pt",
    wait_seconds: float = 0,
) -> dict:
    if not Path(path).exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    job = jobs.start(
        f"palavras de {Path(path).name}",
        lambda job: _speech_words_work(job, path, start, end, language),
    )
    jobs.wait(job, wait_seconds)
    return {**job.snapshot(), "result": job.result}


def _fix_speech_work(job: Job, request: Any) -> dict:
    result = _speech_fix_service(job).fix(request, _stage_progress(job))
    return {
        "output": str(result.path),
        "old_text": result.old_text,
        "new_text": result.new_text,
        "spoken": result.spoken_context,
        "region": [round(result.region_start, 2), round(result.region_end, 2)],
        "duration_rule": result.rule,
        "squeezed": result.squeezed,
        "voice": result.voice,
    }


@server.tool(
    description=(
        "Corrige uma fala sem gravar de novo: regrava um trecho do vídeo ou áudio com a voz clonada do próprio "
        "falante (ou de voice, da biblioteca) e emenda no original, que mantém a duração e o resto intacto. "
        "Aponte o trecho com find (texto errado como foi dito; sem acento nem caixa; occurrence escolhe entre "
        "repetidas) ou com start e end em segundos; text é o que deve ser dito. Por padrão fala também as "
        "palavras vizinhas até o próximo fôlego, para a entonação ficar natural (expand=false fala só o "
        "trecho). Se o texto novo for bem maior ou menor, o trecho estica até as pausas vizinhas; a regra "
        "usada vem em duration_rule. Em vídeos longos use search_from/search_to para transcrever só uma "
        "parte. A saída vai para output/correcao/<nome>.corrigido.<ext> (out troca). save_voice guarda a "
        "voz clonada na biblioteca. Pronúncia: o dicionário vale ([[termo|pronúncia]] em text). Roda em "
        "segundo plano e é lento na CPU (~20 s por segundo de fala nova, mais a separação de voz, ~3x a 6x a "
        "janela de 60 s, em cache): devolve job_id, consulte com job_status."
    )
)
def fix_speech(
    path: str,
    text: str,
    find: str | None = None,
    occurrence: int | None = None,
    start: float | None = None,
    end: float | None = None,
    search_from: float | None = None,
    search_to: float | None = None,
    voice: str | None = None,
    expand: bool = True,
    save_voice: str | None = None,
    language: str = "pt",
    brand: str | None = None,
    steps: int | None = None,
    draft: bool = False,
    seed: int | None = None,
    out: str | None = None,
    wait_seconds: float = 0,
) -> dict:
    from .pipeline.speech_fix import FixRequest
    from .voice.synth import DRAFT_STEPS

    if not Path(path).exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    if voice:
        _voice_library().get(voice)  # falha já na chamada (e não só no job) se a voz não existe
    request = FixRequest(
        src=Path(path),
        text=text,
        find=find,
        occurrence=occurrence,
        start=start,
        end=end,
        search_from=search_from,
        search_to=search_to,
        voice=voice,
        expand=expand,
        save_voice=save_voice,
        language=language,
        brand=brand,
        steps=DRAFT_STEPS if draft and steps is None else steps,
        seed=seed,
        out=Path(out) if out else None,
    )
    job = jobs.start(f"corrigir fala ({Path(path).name})", lambda job: _fix_speech_work(job, request))
    jobs.wait(job, wait_seconds)
    return {**job.snapshot(), "result": job.result}


# ---------- troca de voz ----------


def _convert_voice_work(job: Job, request: Any) -> dict:
    from .media.ffmpeg import SubprocessRunner
    from .pipeline.voice_conversion import default_voice_conversion_service

    service = default_voice_conversion_service(
        SubprocessRunner(sink=job.sink()), job.log, library=_voice_library(), synthesizer=_voice_synthesizer()
    )
    result = service.convert(request, _stage_progress(job))
    return {
        "output": str(result.path),
        "voice": result.voice,
        "seconds": round(result.seconds, 2),
        "blocks": result.blocks,
        "gain_db": round(result.gain_db, 2),
        "engine": result.engine,
        "timings": result.timings,
    }


@server.tool(
    description=(
        "Troca a voz de uma gravação inteira pela de uma voz da biblioteca (clonada ou desenhada), mantendo "
        "as palavras, o ritmo, as pausas, a entonação e o fundo (música, ambiente). Diferente de dub (traduz e "
        "fala de novo) e de fix_speech (troca um trecho): aqui só o timbre muda. voice é o id da voz "
        "(list_voices). start/end (segundos no arquivo) convertem só um trecho; sem eles, o arquivo todo. A "
        "saída vai para output/troca-de-voz/<nome>.<voz>-<id>.<ext> (out troca); vídeo inteiro mantém a "
        "imagem sem recodificar. Roda em segundo plano e é lento na CPU (~1,5 a 2 s por segundo de fala, mais a "
        "separação de voz, ~3x a 6x a duração, em cache): devolve job_id, consulte com job_status."
    )
)
def convert_voice(
    path: str,
    voice: str,
    start: float | None = None,
    end: float | None = None,
    out: str | None = None,
    wait_seconds: float = 0,
) -> dict:
    from .pipeline.voice_conversion import ConversionRequest

    if not Path(path).exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    _voice_library().get(voice)  # falha já na chamada (e não só no job) se a voz não existe
    request = ConversionRequest(
        src=Path(path), voice=voice, start=start, end=end, out=Path(out) if out else None
    )
    job = jobs.start(f"trocar voz ({Path(path).name})", lambda job: _convert_voice_work(job, request))
    jobs.wait(job, wait_seconds)
    return {**job.snapshot(), "result": job.result}


# ---------- dublagem ----------


def _dubbing_service(job: Job):
    """Serviço de dublagem ligado ao job (progresso do ffmpeg e do modelo viram eventos)."""
    from .media.ffmpeg import SubprocessRunner
    from .pipeline.dubbing import default_dubbing_service

    return default_dubbing_service(
        SubprocessRunner(sink=job.sink()),
        job.log,
        library=_voice_library(),
        synthesizer=_voice_synthesizer(),
        lexicons=_lexicon_store(),
    )


def _dub_prepare_work(job: Job, source_path: str, target: str, project_path: Path, options: dict) -> dict:
    from .pipeline.dubbing import project_summary

    project = _dubbing_service(job).prepare(
        Path(source_path), target, project_path=project_path, on_progress=_stage_progress(job), **options
    )
    return {
        **project_summary(project, project_path),
        # o pedido "dubla este vídeo" só termina com o vídeo dublado; a revisão das falas é opcional
        "next": "Para entregar o vídeo dublado, chame dub_render com project igual ao campo project deste resultado.",
    }


@server.tool(
    description=(
        "Dublagem, passo 1: transcreve a fala de um vídeo ou áudio, parte em frases e traduz para "
        "target_language com o Ollama local (modelo em DMAKER_TRANSLATE_MODEL), e grava o projeto editável "
        "`.dub.json` (padrão output/dublagem/<nome>.<idioma>.dub.json). Revise as traduções com dub_get e "
        "corrija com dub_update_segment antes de dub_render. speaker_mode: per_speaker (o padrão: separa quem "
        "fala e usa um clone por pessoa, a partir dos melhores trechos dela; com um falante só vale como single), "
        "per_segment (clona a voz em volta de cada frase) ou single (um clone para o arquivo). num_speakers "
        "força a quantidade de pessoas na diarização (só no modo per_speaker). voice usa uma voz da "
        "biblioteca no lugar do clone. keep_original_db (ex.: -18) mantém a voz original por baixo. glossary: "
        "termos que não se traduzem (as marcas do dicionário de pronúncia já valem). fit_mode decide o que fazer "
        "quando a fala traduzida não cabe no tempo da original: voz (padrão: avança na pausa e acelera a voz até "
        "~1,44x), video (a voz fica natural e o vídeo estica até 1,3x naquele trecho) ou misto (a voz acelera "
        "até 1,15x e o vídeo estica no resto). Lento na CPU (separação de "
        "voz ~3x a 6x a duração, mais a tradução, minutos): devolve job_id, consulte com job_status."
    )
)
def dub_prepare(
    path: str,
    target_language: str,
    source_language: str = "pt",
    speaker_mode: Literal["per_speaker", "per_segment", "single"] | None = None,
    voice: str | None = None,
    keep_original_db: float | None = None,
    glossary: list[str] | None = None,
    brand: str | None = None,
    project: str | None = None,
    fit_mode: Literal["voz", "video", "misto"] = "voz",
    wait_seconds: float = 0,
    num_speakers: int | None = None,
) -> dict:
    from .pipeline.dubbing import default_project_path

    if not Path(path).exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    if source_language.split("-")[0] == target_language.split("-")[0]:
        raise ValueError("O idioma de destino precisa ser diferente do idioma de origem.")
    if voice:
        _voice_library().get(voice)  # falha já na chamada (e não só no job) se a voz não existe
    project_path = Path(project) if project else default_project_path(Path(path), target_language)
    options = {
        "source": source_language,
        "speaker_mode": speaker_mode,
        "num_speakers": num_speakers,
        "voice": voice,
        "keep_original_db": keep_original_db,
        "glossary": glossary or [],
        "brand": brand,
        "fit_mode": fit_mode,
    }
    job = jobs.start(
        f"dublagem: preparar ({Path(path).name})",
        lambda job: _dub_prepare_work(job, path, target_language, project_path, options),
    )
    jobs.wait(job, wait_seconds)
    return {**job.snapshot(), "result": job.result}


def _dub_render_work(
    job: Job, project_path: str, out: str | None, steps: int | None, fit_mode: str | None = None
) -> dict:
    from .domain.dub import load_dub_project
    from .pipeline.dubbing import report_dict, result_dict

    project = load_dub_project(Path(project_path))
    if fit_mode:  # vale só para esta geração; o arquivo do projeto não muda
        project = project.model_copy(update={"fit_mode": fit_mode})
    result = _dubbing_service(job).render(project, Path(out) if out else None, _stage_progress(job), steps)
    return {
        "output": str(result.path),
        "srt": str(result.srt_path),
        **result_dict(result),
        "segments": [report_dict(r) for r in result.report],
    }


@server.tool(
    description=(
        "Dublagem, passo 2: gera a dublagem de um projeto `.dub.json` (de dub_prepare): sintetiza cada tradução "
        "na voz do falante, na duração que cabe, e monta com a música e o ruído de fundo do original; grava o "
        "vídeo (output/dublagem/<nome>.<idioma>.<ext>, out troca) e a legenda .srt no idioma alvo. Cada fala "
        "sintetizada fica em cache: depois de editar uma tradução, rode de novo e só ela é refeita. O resultado "
        "traz warnings (falas que não couberam: encurte a tradução) e o relatório de cada fala. draft usa 8 "
        "passos (metade do tempo). Lento na CPU (~20 s por segundo de fala): devolve job_id, consulte com "
        "job_status. fit_mode (voz, video ou misto) troca, só nesta geração, o que fazer com a fala que não "
        "cabe: video e misto esticam o vídeo (até 1,3x) naquele trecho em vez de acelerar a voz, e o resultado "
        "traz output_seconds e a lista stretched (fala, fator e segundos a mais)."
    )
)
def dub_render(
    project: str,
    out: str | None = None,
    draft: bool = False,
    steps: int | None = None,
    fit_mode: Literal["voz", "video", "misto"] | None = None,
    wait_seconds: float = 0,
) -> dict:
    from .domain.dub import load_dub_project
    from .voice.synth import DRAFT_STEPS

    load_dub_project(Path(project))  # falha já na chamada se o projeto não existe ou está inválido
    job = jobs.start(
        f"dublagem: gerar ({Path(project).name})",
        lambda job: _dub_render_work(
            job, project, out, DRAFT_STEPS if draft and steps is None else steps, fit_mode
        ),
    )
    jobs.wait(job, wait_seconds)
    return {**job.snapshot(), "result": job.result}


def _dub_stems_work(
    job: Job, project_path: str, out_dir: str | None, make_zip: bool, steps: int | None
) -> dict:
    from .domain.dub import load_dub_project
    from .pipeline.dub_stems import StemsOptions

    stems = _dubbing_service(job).export_stems(
        load_dub_project(Path(project_path)),
        StemsOptions(Path(out_dir) if out_dir else None, make_zip),
        _stage_progress(job),
        steps,
    )
    return {
        "folder": str(stems.folder),
        "voice_dubbed": str(stems.outputs.voice_dubbed),
        "background": str(stems.outputs.background),
        "voice_original": str(stems.outputs.voice_original),
        "zip": str(stems.zip_path) if stems.zip_path else None,
        "duration": round(stems.duration, 3),
        "original_voice_db": stems.original_voice_db,
    }


@server.tool(
    description=(
        "Dublagem: exporta as trilhas separadas de um projeto `.dub.json` para remixar em outro editor "
        "(Premiere, DaVinci, CapCut): voz-dublada.wav (só as falas dubladas, posicionadas no tempo), fundo.wav "
        "(música e ruído) e voz-original.wav (a voz original isolada, sem atenuar). WAV 48 kHz estéreo, com a "
        "duração exata do vídeo e alinhados no zero, sem loudnorm nem limitador. Grava em "
        "output/dublagem/<nome>.<idioma>.trilhas (out_dir troca); make_zip=true junta as três num .zip ao lado. Usa as "
        "falas já sintetizadas do cache (só sintetiza o que falta). O resultado traz original_voice_db: o quanto o "
        "vídeo dublado atenua a voz original (null: ela não toca). Devolve job_id, consulte com job_status."
    )
)
def dub_stems(
    project: str,
    out_dir: str | None = None,
    make_zip: bool = False,
    draft: bool = False,
    steps: int | None = None,
    wait_seconds: float = 0,
) -> dict:
    from .domain.dub import load_dub_project
    from .voice.synth import DRAFT_STEPS

    load_dub_project(Path(project))  # falha já na chamada se o projeto não existe ou está inválido
    job = jobs.start(
        f"dublagem: trilhas ({Path(project).name})",
        lambda job: _dub_stems_work(
            job, project, out_dir, make_zip, DRAFT_STEPS if draft and steps is None else steps
        ),
    )
    jobs.wait(job, wait_seconds)
    return {**job.snapshot(), "result": job.result}


@server.tool(description="Lê um projeto de dublagem (.dub.json): as falas com tempo, original e tradução.")
def dub_get(project: str) -> dict:
    from .domain.dub import load_dub_project
    from .pipeline.dubbing import project_summary

    path = Path(project)
    return project_summary(load_dub_project(path), path)


@server.tool(
    description=(
        "Corrige uma fala de um projeto de dublagem: text troca a tradução (a pronúncia pode usar "
        "[[termo|pronúncia]]); locked=true impede que dub_retranslate a sobrescreva; speaker troca quem fala "
        '(um dos falantes do projeto, ex.: "Falante 2"; veja dub_get) e a fala passa a usar a voz dele. Grava o '
        ".dub.json. Depois rode dub_render: só a fala editada é sintetizada de novo."
    )
)
def dub_update_segment(
    project: str,
    segment_id: str,
    text: str | None = None,
    locked: bool | None = None,
    speaker: str | None = None,
) -> dict:
    from .domain.dub import load_dub_project, save_dub_project

    path = Path(project)
    updated = load_dub_project(path).edited(segment_id, text, locked, speaker)
    save_dub_project(updated, path)
    segment = updated.segment(segment_id)
    return {
        "project": str(path),
        "id": segment.id,
        "text": segment.text,
        "locked": segment.locked,
        "speaker": segment.speaker,
    }


def _dub_retranslate_work(job: Job, project_path: str) -> dict:
    from .domain.dub import load_dub_project, save_dub_project
    from .pipeline.dubbing import project_summary

    path = Path(project_path)
    project = _dubbing_service(job).retranslate(load_dub_project(path), _stage_progress(job))
    save_dub_project(project, path)
    return project_summary(project, path)


@server.tool(
    description=(
        "Traduz de novo, com o Ollama, as falas de um projeto de dublagem que não estão travadas (locked); as "
        "travadas, com a sua revisão, ficam como estão. Devolve job_id, consulte com job_status."
    )
)
def dub_retranslate(project: str, wait_seconds: float = 0) -> dict:
    from .domain.dub import load_dub_project

    load_dub_project(Path(project))
    job = jobs.start(
        f"dublagem: traduzir de novo ({Path(project).name})", lambda job: _dub_retranslate_work(job, project)
    )
    jobs.wait(job, wait_seconds)
    return {**job.snapshot(), "result": job.result}


# ---------- recursos e prompt ----------


@server.resource("dmaker://guide", name="Manual do DMaker", mime_type="text/markdown")
def guide_resource() -> str:
    return dmaker_guide()


@server.resource("dmaker://schema", name="Schema da spec", mime_type="application/json")
def schema_resource() -> str:
    return json.dumps(spec_schema(), ensure_ascii=False, indent=1)


@server.prompt(
    name="editar-video", description="Roteiro para transformar um pedido de edição em um render pronto."
)
def edit_video_prompt(pedido: str) -> str:
    return (
        f"Pedido do usuário: {pedido}\n\n"
        "Siga o manual (`dmaker_guide`): inspecione as fontes com `probe_media`, escreva a spec e salve com "
        "`save_project`, confira com `validate_project`, renderize com `render_project(preview=true)`, confira "
        "com `qa_report` (só olhe imagem com `contact_sheet`/`frames` se ele apontar algo), ajuste, e só então "
        "faça o render final. Entregue o caminho do mp4."
    )


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
