"""Peças compartilhadas pelos testes do manual: um manual pequeno, uma CLI falsa e ferramentas falsas."""

from __future__ import annotations

import typer

from dmaker.manual.reference_mcp import ToolDoc

SAMPLE_MANUAL = """# Manual de teste

Introdução.

## Quero fazer X, onde está?

<!-- dmaker:gerado indice -->

<!-- dmaker:fim-gerado indice -->

## Instalação passo a passo

Rode o instalador e confira com o doctor.

## Tarefas de vídeo

### Fazer um Reel
<!-- tarefa: reel -->
Transforma uma gravação em um Reel legendado.

#### Quando usar

Você tem um vídeo falado e quer um Reel.

**Pedidos que levam a esta tarefa:**
- "Faz um reel desse vídeo"

#### Antes de começar

- O arquivo de vídeo.

#### Pela IA

Peça em português.

#### Chamadas das ferramentas

```json
[
  {"tool": "probe_media", "arguments": {"paths": ["C:/videos/a.mp4"]}, "para": "ver a duração"},
  {"tool": "quick_edit", "arguments": {"src": "C:/videos/a.mp4", "captions": true}}
]
```

#### Pela interface

Novo projeto.

#### Pela CLI

```powershell
dmaker quick a.mp4 --captions --hook "Olá"
```

#### Como conferir

Abra o arquivo.

#### Se der errado

- **Erro**: tente de novo.

### Dublar um vídeo
<!-- tarefa: dublar -->
Troca a fala por outro idioma.

#### Quando usar

Você quer a versão em inglês.

#### Antes de começar

- O idioma alvo.

#### Pela IA

Peça a dublagem.

#### Chamadas das ferramentas

```json
[{"tool": "probe_media", "arguments": {"paths": ["a.mp4"]}}]
```

#### Pela interface

Aba Voz.

#### Pela CLI

```powershell
dmaker dub a.mp4 --to en
```

#### Como conferir

Ouça.

#### Se der errado

- **Erro**: veja o Ollama.

## Referência gerada

<!-- dmaker:gerado cli -->

<!-- dmaker:fim-gerado cli -->

<!-- dmaker:gerado mcp -->

<!-- dmaker:fim-gerado mcp -->

<!-- dmaker:gerado spec -->

<!-- dmaker:fim-gerado spec -->

<!-- dmaker:gerado infograficos -->

<!-- dmaker:fim-gerado infograficos -->
"""


def fake_cli_root(extra: bool = False):
    """Uma CLI pequena com grupo, argumento, opção, bandeira e um grupo que manda o resto para `run`."""
    app = typer.Typer(help="CLI de teste.")

    @app.command()
    def quick(
        src: str = typer.Argument(..., help="Vídeo fonte."),
        captions: bool = typer.Option(False, "--captions/--no-captions", help="Legendas automáticas."),
        hook: str = typer.Option("", help="Texto de gancho."),
    ) -> None:
        """Edição rápida de um vídeo."""

    group = typer.Typer(help="Dublagem de teste.")
    app.add_typer(group, name="dub")

    @group.command("run")
    def dub_run(
        file: str = typer.Argument(..., help="Arquivo."),
        to: str = typer.Option(..., "--to", help="Idioma alvo."),
    ) -> None:
        """Dubla tudo."""

    if extra:

        @app.command()
        def comando_falso(nome: str = typer.Argument(..., help="Nome.")) -> None:
            """Um comando que o manual ainda não conhece."""

    return typer.main.get_command(app)


def fake_tools() -> tuple[ToolDoc, ...]:
    return (
        ToolDoc(
            "probe_media",
            "Duração e tamanho de arquivos. Segunda frase.",
            {
                "type": "object",
                "properties": {"paths": {"type": "array", "items": {"type": "string"}}},
                "required": ["paths"],
            },
        ),
        ToolDoc(
            "quick_edit",
            "Edição rápida de um vídeo.",
            {
                "type": "object",
                "properties": {
                    "src": {"type": "string"},
                    "captions": {"type": "boolean", "default": False},
                    "end": {"anyOf": [{"type": "number"}, {"type": "null"}], "default": None},
                },
                "required": ["src"],
            },
        ),
    )
