"""Servidor MCP do DMaker: expõe o editor como ferramentas para qualquer IA (Claude, Cursor, etc.).

Sobe por stdio (`dmaker mcp`). Ferramentas devolvem JSON; as de conferência devolvem imagens, para a IA
ver o resultado. Renders longos rodam em segundo plano com `job_id` (ver `job_status`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Image, MCPServer

from . import __version__, config
from .domain.brand import available_brands, load_theme
from .domain.presets import get_preset, list_presets
from .domain.spec import Project
from .pipeline.jobs import Job, JobManager

GUIDE_PATH = config.ROOT / ".claude" / "skills" / "dmaker" / "SKILL.md"

server = MCPServer(
    name="dmaker",
    version=__version__,
    instructions=(
        "DMaker edita vídeos curtos para Instagram, Facebook, YouTube, TikTok e WhatsApp a partir de uma spec JSON. "
        "Comece por `dmaker_guide` (manual e regras) e `spec_schema`. Fluxo: probe_media -> save_project -> "
        "validate_project -> render_project(preview=true) -> contact_sheet/frames para conferir -> render_project."
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
    return _result_dict(pipeline.run())


@server.tool(
    description=(
        "Renderiza o projeto. preview=true gera uma versão rápida em baixa resolução para conferir. "
        "Espera até wait_seconds; se ainda estiver rodando devolve job_id para consultar com job_status."
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
) -> dict:
    """`segments` = "12-20" renderiza só esses trechos (sem sobreposições/legendas), para revisar vídeos longos."""
    if preset:
        get_preset(preset)
    job = jobs.start(
        f"render {name_or_path} ({'preview' if preview else preset or 'final'})",
        lambda job: _render(job, name_or_path, preview, preset, force, guides, no_captions, segments),
    )
    jobs.wait(job, wait_seconds)
    return {**job.snapshot(), "result": job.result}


@server.tool(
    description="Exporta o projeto para vários presets (ex.: instagram/reels, youtube/shorts). Devolve um job."
)
def export_project(name_or_path: str, presets: list[str], wait_seconds: float = 900) -> dict:
    for p in presets:
        get_preset(p)

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
    if job is None:
        return {"error": f"job desconhecido: {job_id}"}
    return {**job.snapshot(), "result": job.result}


@server.tool(description="Jobs de render desta sessão.")
def list_jobs() -> list[dict]:
    return jobs.list()


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
    description="Transcreve um vídeo/áudio (Whisper local) e devolve as cues com tempo por palavra; salva .srt e .json."
)
def transcribe_media(path: str, language: str = "pt", model: str = "small", device: str = "cpu") -> dict:
    from .media.ffmpeg import SubprocessRunner
    from .text.captions import regroup, save_captions
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
    return {
        "json": str(json_path),
        "srt": str(srt_path),
        "meta": transcript.meta,
        "cues": [{"start": c.start, "end": c.end, "text": c.text} for c in transcript.cues],
    }


@server.tool(
    description="Lê as legendas automáticas geradas para um projeto (captions.auto.json), com tempo por palavra."
)
def read_captions(name_or_path: str) -> dict:
    from .pipeline.projects import project_path

    store = project_path(name_or_path).parent / "captions.auto.json"
    if not store.exists():
        return {"error": "sem legendas automáticas ainda; renderize o projeto com captions.source = auto"}
    return json.loads(store.read_text(encoding="utf-8"))


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
    description="Grade de quadros do vídeo inteiro numa única imagem, para revisar composição e texto.",
    structured_output=False,
)
def contact_sheet(video: str, cols: int = 3, rows: int = 3, width: int = 320) -> list:
    from .pipeline.qa import contact_sheet as _sheet

    src = Path(video)
    out = _sheet(src, src.with_name(f"{src.stem}_sheet.png"), cols, rows, width)
    return [{"image": str(out), "cols": cols, "rows": rows}, Image(path=out)]


@server.tool(
    description="Quadros em instantes específicos do vídeo (segundos), devolvidos como imagens.",
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
        "`save_project`, confira com `validate_project`, renderize com `render_project(preview=true)`, olhe o "
        "resultado com `contact_sheet`/`frames`, ajuste, e só então faça o render final. Entregue o caminho do mp4."
    )


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
