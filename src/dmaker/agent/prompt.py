"""Prompt de sistema do agente local: corpo da skill do DMaker mais regras curtas para um modelo pequeno."""

from __future__ import annotations

from pathlib import Path

from .. import config

DEFAULT_SKILL_PATH = config.ROOT / ".claude" / "skills" / "dmaker" / "SKILL.md"

EXTRA_RULES = """## Regras extras para o agente local

- Responda sempre em português do Brasil.
- Use sempre uma ferramenta para agir ou conferir algo, nunca suponha o resultado de um render, de uma
  validação ou de uma leitura de legendas sem checar com a ferramenta correspondente.
- Nunca invente caminho de arquivo (vídeo, foto, áudio, projeto): se não souber onde está, pergunte ao
  usuário em vez de chutar.
- Fluxo padrão: list_templates para escolher um template, new_from_template para criar o projeto,
  validate_project para conferir, render_project(preview=true) para uma prévia rápida, qa_report para
  ler os avisos automáticos, corrigir com edit_project/fix_captions quando precisar e só então
  render_project final.
- Chame uma ferramenta por vez e espere o resultado antes de decidir o próximo passo.
- Ao terminar um render ou uma exportação, diga ao usuário o caminho do arquivo mp4 gerado.
"""


def _strip_frontmatter(text: str) -> str:
    """Remove o bloco YAML (entre as duas linhas `---`) do início da SKILL.md; sobra só o corpo."""
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    return text[end + len("\n---") :].lstrip("\n")


def system_prompt(skill_path: Path | None = None, extra_rules: str | None = None) -> str:
    """Corpo da skill (sem frontmatter) mais as regras extras: prompt de sistema passado ao `AgentLoop`."""
    path = skill_path or DEFAULT_SKILL_PATH
    body = _strip_frontmatter(path.read_text(encoding="utf-8")).strip() if path.exists() else ""
    rules = (extra_rules if extra_rules is not None else EXTRA_RULES).strip()
    return f"{body}\n\n{rules}\n" if body else f"{rules}\n"
