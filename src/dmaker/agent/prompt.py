"""Prompt de sistema do agente local: regras essenciais curtas mais o manual do kit escolhido.

A skill inteira pesava o contexto de um modelo pequeno. Agora o prompt é só o que vale sempre (as regras
abaixo) e o manual curto de cada kit, gerado por `dmaker manual build` das mesmas tarefas do manual; o resto o
modelo consulta com a ferramenta `search_manual`. Montar o prompt é função pura: o carregador do manual entra
por parâmetro.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from .kits import Kit, kit_by_name

ESSENTIAL_RULES = """Você opera o DMaker, um editor de vídeos curtos, pelas ferramentas que recebeu.

## Regras

- Responda sempre em português do Brasil, curto e direto, sem travessão.
- Para agir ou conferir qualquer coisa, chame uma ferramenta. Nunca suponha o resultado de um render, de uma
  validação ou de uma leitura. Chame uma ferramenta por vez e espere o resultado.
- Nunca invente caminho de arquivo, nome de projeto, voz ou template: se não souber, pergunte ao usuário. Os
  caminhos do manual são só exemplos.
- Se uma ferramenta devolver erro, leia a mensagem, corrija o argumento e tente de novo. Se falhar outra vez,
  conte ao usuário o que aconteceu.
- Render final, exportação, apagar e sobrescrever exigem a confirmação do usuário: o sistema pergunta a ele. Se
  ele recusar, não faça de outro jeito; diga o que ficou sem fazer.
- Só clone uma voz se o usuário disser que o dono da voz autorizou.
- Fluxo padrão de um vídeo: criar o projeto, validar, gerar a prévia (preview), ler o relatório de QA e só
  então pedir o render final.
- Se o pedido não cabe nas ferramentas que você tem, diga isso em vez de improvisar. Dúvida sobre como fazer
  algo: use `search_manual`.
- Ao terminar um render ou uma exportação, diga ao usuário o caminho do arquivo gerado.
"""

ManualLoader = Callable[[str], "str | None"]


def kit_manual_id(kit: Kit) -> str:
    """O nome do arquivo de `docs/ia` do kit, sem a extensão (`agente-editing`)."""
    return f"agente-{kit.name}"


def default_manual_loader(name: str) -> str | None:
    """Lê o arquivo de `docs/ia` (ou a cópia empacotada, numa instalação comum), só na hora de montar o prompt."""
    from ..manual import files

    return files.read_ia_doc(name)


def system_prompt(
    kit_names: Sequence[str],
    manual_loader: ManualLoader | None = None,
    extra_rules: str | None = None,
) -> str:
    """As regras essenciais mais o manual de cada kit escolhido, na ordem dada."""
    load = manual_loader or default_manual_loader
    rules = (extra_rules if extra_rules is not None else ESSENTIAL_RULES).strip()
    parts = [rules]
    for name in kit_names:
        kit = kit_by_name(name)
        manual = load(kit_manual_id(kit))
        parts.append(manual.strip() if manual else f"# Kit {kit.title}\n\n{kit.description}")
    return "\n\n".join(parts) + "\n"


def task_prompt(task_manual: str, extra_rules: str | None = None) -> str:
    """O prompt para executar uma tarefa do manual escolhida de antemão (`dmaker ajuda` oferece): as regras mais o arquivo da tarefa."""
    rules = (extra_rules if extra_rules is not None else ESSENTIAL_RULES).strip()
    return f"{rules}\n\n## Manual da tarefa\n\n{task_manual.strip()}\n"
