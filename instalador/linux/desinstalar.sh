#!/bin/sh
# Desinstalador do DMaker para Linux.
#
# Uso: <pasta do programa>/desinstalar.sh [--sim] [--apagar-dados]
#   --sim            não pergunta nada; os seus dados NÃO são apagados
#   --apagar-dados   apaga também a pasta dos dados (projetos, vozes, saídas, cache e modelos), sem perguntar
#
# Tira o programa, os lançadores e o atalho do menu. O Ollama e o serviço dele só saem se foi o instalador do DMaker
# que os pôs. Sem terminal e sem --apagar-dados, os dados ficam.

set -eu

SIM=0
APAGAR_DADOS=0

mensagem() { printf '%s\n' "$*"; }
falha() {
    printf 'ERRO: %s\n' "$*" >&2
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --sim) SIM=1 ;;
        --apagar-dados) APAGAR_DADOS=1 ;;
        -h | --ajuda | --help)
            sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) falha "Opção desconhecida: $1" ;;
    esac
    shift
done

PROGRAMA=$(cd "$(dirname "$0")" && pwd)
MARCADOR="$PROGRAMA/instalacao.json"
[ -f "$MARCADOR" ] || falha "Não achei o instalacao.json em $PROGRAMA: este não parece ser o programa instalado do DMaker."
[ -d "$PROGRAMA/python" ] || falha "Não achei o python/ em $PROGRAMA: recuso apagar uma pasta que não reconheço."

valor() {
    sed -n -e "s/^ *\"$1\": *\"\(.*\)\",\{0,1\} *\$/\1/p" -e "s/^ *\"$1\": *\(true\|false\),\{0,1\} *\$/\1/p" "$MARCADOR" | head -n 1
}

DADOS=$(valor dados)
DESKTOP=$(valor desktop)
OLLAMA_NOSSO=$(valor ollama_nosso)
SERVICO_OLLAMA=$(valor servico_ollama)
SERVICOS="$HOME/.config/systemd/user"

if [ -t 0 ] && [ "$SIM" -eq 0 ]; then
    INTERATIVO=1
else
    INTERATIVO=0
fi

if [ "$APAGAR_DADOS" -eq 0 ] && [ "$INTERATIVO" -eq 1 ] && [ -d "$DADOS" ]; then
    printf 'Apagar também os seus dados (projetos, vozes, saídas, cache e modelos) em %s? Isso não pode ser desfeito. [s/N]: ' "$DADOS"
    read -r resposta || resposta=""
    case "$resposta" in
        s | S | sim | SIM | Sim) APAGAR_DADOS=1 ;;
    esac
fi

# Os lançadores: só os que o instalador registrou e que ainda apontam para este programa.
for lancador in $(sed -n 's/^ *"lancadores": *\[\(.*\)\],\{0,1\} *$/\1/p' "$MARCADOR" | tr -d '",'); do
    if [ -f "$lancador" ] && grep -qF "$PROGRAMA" "$lancador" 2>/dev/null; then
        rm -f "$lancador"
        mensagem "Removido $lancador"
    fi
done
if [ -n "$DESKTOP" ] && [ -f "$DESKTOP" ]; then
    rm -f "$DESKTOP"
    mensagem "Removido $DESKTOP"
fi

if [ "$SERVICO_OLLAMA" = "true" ]; then
    if command -v systemctl >/dev/null 2>&1; then
        systemctl --user disable --now dmaker-ollama.service >/dev/null 2>&1 || true
    fi
    rm -f "$SERVICOS/dmaker-ollama.service"
    if command -v systemctl >/dev/null 2>&1; then
        systemctl --user daemon-reload >/dev/null 2>&1 || true
    fi
    mensagem "Serviço do Ollama removido"
fi
if [ "$OLLAMA_NOSSO" != "true" ] && [ -d "$PROGRAMA/ollama" ]; then
    # Não foi este instalador que pôs o Ollama: se a pasta existe, é de outra coisa, e fica.
    mensagem "O Ollama não foi instalado por este instalador: fica como está."
fi

# Os dados: só as pastas e os arquivos do DMaker, e a pasta some se ficar vazia (nunca um rm -rf do que o usuário pôs lá).
if [ "$APAGAR_DADOS" -eq 1 ] && [ -n "$DADOS" ] && [ -d "$DADOS" ]; then
    [ "$DADOS" != "/" ] && [ "$DADOS" != "$HOME" ] || falha "Recuso apagar $DADOS."
    for item in projects output cache assets conversations plugins layouts.json plugins.json; do
        rm -rf "${DADOS:?}/$item"
    done
    rmdir "$DADOS" 2>/dev/null || true
    mensagem "Dados apagados em $DADOS"
elif [ -n "$DADOS" ]; then
    mensagem "Os seus dados ficaram em $DADOS"
fi

# O programa por último: este script mora nele.
cd /
rm -rf "${PROGRAMA:?}"
mensagem "DMaker desinstalado."
exit 0
