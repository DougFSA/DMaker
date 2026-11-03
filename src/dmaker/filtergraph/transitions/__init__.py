"""Construtores de transição de vídeo, registrados por nome.

Importar o pacote registra todos: os 48 tipos do xfade (`xfade.py`) e as de movimento, uma por módulo.
Para um tipo novo, escreva o construtor num módulo daqui, registre-o com `@register("nome")` e acrescente o
nome e a frase de descrição em `domain/transitions.py`.
"""

from . import burn, crosszoom, push, xfade  # noqa: F401  (o import registra os tipos)
from .registry import TransitionBuilder, TransitionRequest, build_transition, register, registered_names

__all__ = ["TransitionBuilder", "TransitionRequest", "build_transition", "register", "registered_names"]
