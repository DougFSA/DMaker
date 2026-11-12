"""Personas: cadastro, boca em português (visemas) e os motores que desenham cada tipo.

Um motor novo entra importando o módulo dele aqui: o módulo chama `register_engine` ao ser importado.
"""

from . import (
    engine2d,  # noqa: F401 - registra o motor do tipo 2d
    engine3d,  # noqa: F401 - registra o motor do tipo 3d
)
