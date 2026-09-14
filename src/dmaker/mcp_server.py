"""Servidor MCP do DMaker: expõe o editor como ferramentas para qualquer IA (Claude, Cursor, etc.).

Sobe por stdio (`dmaker mcp`). Ferramentas devolvem JSON; as de conferência devolvem imagens, para a IA
ver o resultado. Renders longos rodam em segundo plano com `job_id` (ver `job_status`).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import Image, MCPServer

from . import __version__, config
from .domain.brand import available_brands, load_theme
from .domain.presets import get_preset, list_presets
from .domain.spec import Project
from .pipeline.jobs import Job, JobManager
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
        "Templates disponíveis (produto, depoimento, stories, vlog, tutorial, casamento...) com os "
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
    except TemplateError as exc:
        # anticipada: mensagem chega ao cliente (nome do template ou parâmetros faltando)
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
        "MUS música, CC legendas), com o intervalo de cada item já calculado."
    )
)
def timeline_view(name: str) -> dict:
    from .pipeline.layout import project_layout
    from .pipeline.projects import load_project
    from .pipeline.timeline_view import build_timeline_view

    project = load_project(name)
    layout = project_layout(project)
    return build_timeline_view(project, layout).to_dict()


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
    payload = _result_dict(result)
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
    description="Situação de um render em segundo plano (running | done | error) e o resultado quando pronto."
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
        return {"spec_path": str(spec_path), **_result_dict(pipeline.run())}

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
