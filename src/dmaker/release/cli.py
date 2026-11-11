"""`dmaker release build` e `dmaker release publish`: os adaptadores finos sobre o `ReleaseBuilder` e o `ReleasePublisher`."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape

from .. import __version__
from .build import BuildOptions, BuildResult, ReleaseBuilder, UrlDownloader
from .notes import human_size
from .platforms import PLATFORMS
from .publish import PublishOptions, ReleasePublisher
from .runner import ReleaseError, SubprocessCommandRunner

release_app = typer.Typer(
    help="Monta os instaladores do DMaker (Windows e Linux) e os publica na aba Releases do GitHub.",
    no_args_is_help=True,
)
console = Console()
ALL_PLATFORMS = "todas"


def _git_toplevel() -> Path:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True)
    return Path(out.stdout.strip())


def _platforms(choice: str) -> list[str]:
    if choice == ALL_PLATFORMS:
        return list(PLATFORMS)
    if choice not in PLATFORMS:
        raise ReleaseError(f"Plataforma desconhecida: {choice}. Use windows, linux ou {ALL_PLATFORMS}.")
    return [choice]


def _print_result(platform: str, result: BuildResult) -> None:
    console.print(f"[{platform}] pronto em {result.output_dir} ({result.seconds / 60:.1f} min)", markup=False)
    for name, seconds in result.steps:
        console.print(f"  {seconds / 60:6.1f} min  {name}", markup=False, highlight=False)
    for file in result.files:
        console.print(f"  {file.name}  {human_size(file.size)}  {file.sha256}", markup=False, highlight=False)
    for note in result.notes:
        console.print(f"  {note}", markup=False, highlight=False)
    if result.blocked:
        console.print(
            "[yellow]Atenção: modelos com licença restrita no pacote: "
            + ", ".join(result.blocked)
            + "[/yellow]"
        )


@release_app.command("build")
def build(
    platform: Annotated[
        str, typer.Option("--plataforma", help="Sistema do instalador: windows, linux ou todas.")
    ] = ALL_PLATFORMS,
    pasta: Annotated[
        Path | None,
        typer.Option(
            "--pasta",
            help="Raiz principal do DMaker: de lá vêm os binários, os modelos e a ferramenta do instalador, e nela "
            "ficam releases/v<versão> e os downloads. Padrão: o clone atual.",
        ),
    ] = None,
    without_models: Annotated[
        list[str] | None,
        typer.Option(
            "--sem-modelo",
            help="Não leva este modelo no pacote (ele baixa no primeiro uso). Repita para vários. Ex.: --sem-modelo omnivoice.",
        ),
    ] = None,
    keep_staging: Annotated[
        bool, typer.Option("--manter-trabalho", help="Não apaga a pasta de trabalho no fim.")
    ] = False,
) -> None:
    """Gera o instalador e as partes em releases/v<versão>, com o SHA-256 de cada arquivo e as notas da release."""
    repo = _git_toplevel()
    log = lambda line: console.print(line, markup=False, highlight=False)  # noqa: E731
    try:
        for chosen in _platforms(platform):
            options = BuildOptions(
                version=__version__,
                platform=chosen,
                repo_root=repo,
                main_root=(pasta or repo).resolve(),
                host_python=sys.executable,
                keep_staging=keep_staging,
                excluded_models=tuple(without_models or ()),
            )
            builder = ReleaseBuilder(options, SubprocessCommandRunner(on_line=log), UrlDownloader(log), log)
            _print_result(chosen, builder.build())
    except ReleaseError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc


@release_app.command("publish")
def publish(
    version: Annotated[
        str,
        typer.Option("--versao", help="O nome da versão, o mesmo da tag (2 para a tag v2, pacote 2.0.0)."),
    ],
    pasta: Annotated[
        Path | None,
        typer.Option(
            "--pasta", help="Raiz principal do DMaker, onde está releases/v<versão>. Padrão: o clone atual."
        ),
    ] = None,
) -> None:
    """Sobe os instaladores de releases/v<versão> para a release do GitHub (a tag precisa existir). Pode ser repetido."""
    repo = _git_toplevel()
    log = lambda line: console.print(line, markup=False, highlight=False)  # noqa: E731
    options = PublishOptions(version=version, main_root=(pasta or repo).resolve(), repo_root=repo)
    publisher = ReleasePublisher(options, SubprocessCommandRunner(on_line=log), log)
    try:
        result = publisher.publish()
    except ReleaseError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"Release {result.tag}: {result.url}", markup=False, highlight=False)
    console.print(f"  enviados agora: {len(result.uploaded)}; já estavam lá: {len(result.already_there)}")
    if result.published_draft:
        console.print("  a release estava como rascunho e foi publicada agora")
