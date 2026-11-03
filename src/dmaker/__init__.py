"""DMaker: editor de vídeos curtos orientado a comandos.

O fluxo é: spec JSON (projeto) -> normalização de cada trecho (mezanino em cache)
-> montagem (transições, sobreposições, legendas, áudio) -> codificação no preset
da plataforma. Tudo roda sobre FFmpeg; texto e legendas usam libass (ASS).
"""

# Fonte única da versão do pacote, no formato X.Y.Z (o release da vN sobe para N.0.0): o pyproject.toml a lê
# daqui, para o `dmaker --version`, o servidor MCP e a interface nunca divergirem do que foi lançado.
__version__ = "2.0.0"
