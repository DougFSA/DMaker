#!/bin/sh
# Lançador do DMaker instalado: usa o Python do programa (nunca o do sistema).
# PYTHONNOUSERSITE impede que pacotes do ~/.local do usuário se misturem aos do programa; PYTHONUTF8 evita erro de
# acento quando a saída é redirecionada.
PYTHONNOUSERSITE=1 PYTHONUTF8=1 exec "@@PROGRAMA@@/python/bin/python3" -m dmaker "$@"
