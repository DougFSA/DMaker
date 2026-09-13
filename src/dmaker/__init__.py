"""DMaker: editor de vídeos curtos orientado a comandos.

O fluxo é: spec JSON (projeto) -> normalização de cada trecho (mezanino em cache)
-> montagem (transições, sobreposições, legendas, áudio) -> codificação no preset
da plataforma. Tudo roda sobre FFmpeg; texto e legendas usam libass (ASS).
"""

__version__ = "0.1.0"
