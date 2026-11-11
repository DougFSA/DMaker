"""`dmaker release build`: o adaptador fino sobre o `ReleaseBuilder`."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape

from .. import __version__
from .build import BuildOptions, ReleaseBuilder, UrlDownloader
from .notes import human_size
from .runner import ReleaseError, SubprocessCommandRunner

release_app = typer.Typer(
    help="Monta o instalador do DMaker (Python portátil, binários e modelos).", no_args_is_help=True
)
console = Console()


def _git_toplevel() -> Path:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True)
    return Path(out.stdout.strip())


@release_app.command("build")
def build(
    platform: Annotated[
        str, typer.Option("--plataforma", help="Sistema do instalador (windows).")
    ] = "windows",
    pasta: Annotated[
        Path | None,
        typer.Option(
            "--pasta",
            help="Raiz principal do DMaker: de lá vêm os binários, os modelos e a ferramenta do instalador, e nela "
            "ficam releases/v<versão> e os downloads. Padrão: o clone atual.",
        ),
    ] = None,
    keep_staging: Annotated[
        bool, typer.Option("--manter-trabalho", help="Não apaga a pasta de trabalho no fim.")
    ] = False,
) -> None:
    """Gera o instalador e as fatias em releases/v<versão>, com o SHA-256 de cada arquivo e as notas da release."""
    repo = _git_toplevel()
    options = BuildOptions(
        version=__version__,
        platform=platform,
        repo_root=repo,
        main_root=(pasta or repo).resolve(),
        host_python=sys.executable,
        keep_staging=keep_staging,
    )
    log = lambda line: console.print(line, markup=False, highlight=False)  # noqa: E731
    builder = ReleaseBuilder(options, SubprocessCommandRunner(on_line=log), UrlDownloader(log), log)
    try:
        result = builder.build()
    except ReleaseError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"Pronto em {result.output_dir} ({result.seconds / 60:.1f} min)")
    for file in result.files:
        console.print(f"  {file.name}  {human_size(file.size)}  {file.sha256}", markup=False, highlight=False)
    if result.blocked:
        console.print(
            "[yellow]Atenção: modelos com licença restrita no pacote: "
            + ", ".join(result.blocked)
            + "[/yellow]"
        )
