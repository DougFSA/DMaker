"""Camada da pessoa: o recorte da pessoa sobre a linha do tempo final, para um texto poder passar atrás dela.

Diferente do `matte` (que troca o fundo da fonte bruta), este recorte é feito sobre o que o vídeo final mostra
(enquadramento, velocidade, look e transições já aplicados), para a pessoa cair pixel a pixel sobre o quadro. Só
os intervalos de texto `behind-person` são recortados, e cada um fica em cache por conteúdo, como o mezanino."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..domain.spec import Transition
from ..domain.timeline import TimelineWindow, timeline_window
from ..filtergraph.behind_person import ResolvedPersonLayer
from ..filtergraph.person_layer import person_layer_command, window_command
from ..media.ffmpeg import FFmpegCommand
from ..media.matting import DEFAULT_MODEL, PREVIEW_MODEL, PersonRequest
from .context import RenderContext
from .segments import PreparedSegment, cache_key

# Muda quando a receita da camada muda (ajuste do alfa, cor do primeiro plano, codec, aquecimento): invalida o
# cache só dela. Não é o MATTE_VERSION nem o MEZZ_VERSION, cujas receitas continuam as mesmas.
PERSON_LAYER_VERSION = "p1"
# O RVM é recorrente e os primeiros quadros, sem memória, erram o cabelo e os dedos. 12 quadros (0,4 s a 30 fps) de
# cena que ele vê e descarta são o aquecimento: custa uns 10 s de CPU por intervalo em 1080p (0,8 s por quadro, medido),
# e o ajuste fino com uma pessoa de verdade fica para o teste manual.
WARMUP_FRAMES = 12


@dataclass
class PreparedPersonLayer:
    """Uma camada da pessoa pronta para a montagem: o vídeo com alfa e os comandos que o geram (nenhum, se já
    estava em cache). O vídeo só ganha o nome final ao terminar inteiro, para um render interrompido não deixar
    no cache um arquivo pela metade."""

    layer: ResolvedPersonLayer
    window: TimelineWindow
    partial: Path
    scratch: Path  # a janela sem perdas que o recortador lê; some assim que a camada fica pronta
    commands: tuple[FFmpegCommand, ...] = ()


def _needs_render(out: Path, ctx: RenderContext) -> bool:
    return ctx.options.dry_run or ctx.options.force or not out.exists()


class PersonLayerBuilder:
    """Prepara e gera (quando não está em cache) a camada da pessoa de cada intervalo atrás da pessoa.

    No `--preview` o modelo é o leve (`preview_model`, 2,5x mais rápido): o rascunho serve para conferir a posição
    do texto, e o modelo entra na chave do cache, então rascunho e render final não se misturam."""

    def __init__(self, model: str = DEFAULT_MODEL, preview_model: str = PREVIEW_MODEL):
        self.model = model
        self.preview_model = preview_model

    def model_for(self, ctx: RenderContext) -> str:
        return self.preview_model if ctx.options.preview else self.model

    def prepare(
        self,
        ctx: RenderContext,
        prepared: list[PreparedSegment],
        transitions: list[Transition | None],
        intervals: list[tuple[float, float]],
    ) -> list[PreparedPersonLayer]:
        if not intervals:
            return []
        if ctx.matter is None:
            raise RuntimeError("overlays: texto `behind-person` precisa de um recortador (ctx.matter)")
        durations = [item.duration for item in prepared]
        model = self.model_for(ctx)
        layers: list[PreparedPersonLayer] = []
        for start, end in intervals:
            window = timeline_window(durations, transitions, start, end, ctx.fps, WARMUP_FRAMES)
            if window is None:
                continue
            mezzanines = [prepared[i].mezzanine for i in range(window.first, window.last + 1)]
            # o nome de cada mezanino já carrega a chave do conteúdo dele (spec, fonte, tamanho, look)
            key = cache_key(
                PERSON_LAYER_VERSION,
                [path.name for path in mezzanines],
                window.durations,
                # a transição do primeiro trecho é sempre vazia e não conta; a duração que cada uma tem de fato
                # depende do que veio antes dela no vídeo (o teto de metade do que já existe), então entra também
                [tr.model_dump(mode="json") if tr is not None else None for tr in window.transitions[1:]],
                window.overlaps,
                window.seek,
                window.warmup_frames,
                window.frame_count,
                ctx.width,
                ctx.height,
                ctx.fps,
                model,
            )
            out = ctx.cache_dir / f"{key}_person.mov"
            partial = ctx.cache_dir / f"{key}_person.part.mov"
            scratch = ctx.cache_dir / f"{key}_window.mkv"
            resolved = ResolvedPersonLayer(
                out, window.first_frame / ctx.fps, (window.first_frame + window.frame_count) / ctx.fps
            )
            commands: tuple[FFmpegCommand, ...] = ()
            if _needs_render(out, ctx):
                request = PersonRequest(
                    scratch,
                    window.rendered_frames / ctx.fps,
                    ctx.width,
                    ctx.height,
                    ctx.fps,
                    model,
                    warmup_frames=window.warmup_frames,
                )
                # no dry-run o comando é só registrado; os quadros nunca são pedidos ao modelo
                frames = iter(()) if ctx.options.dry_run else ctx.matter.person_frames(request)
                label = f"{start:.1f}s a {end:.1f}s"
                commands = (
                    window_command(
                        mezzanines,
                        window,
                        ctx.fps,
                        (ctx.width, ctx.height),
                        scratch,
                        label=f"janela da pessoa ({label})",
                    ),
                    person_layer_command(
                        frames,
                        ctx.width,
                        ctx.height,
                        ctx.fps,
                        window.frame_count,
                        partial,
                        label=f"recorte da pessoa ({label})",
                    ),
                )
            layers.append(PreparedPersonLayer(resolved, window, partial, scratch, commands))
        return layers

    def build(self, ctx: RenderContext, layers: list[PreparedPersonLayer]) -> None:
        for item in layers:
            if not item.commands:
                continue
            try:
                for command in item.commands:
                    ctx.runner.run(command)
                if item.partial.exists():
                    item.partial.replace(item.layer.path)
            finally:
                item.partial.unlink(missing_ok=True)
                item.scratch.unlink(missing_ok=True)
