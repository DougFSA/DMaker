#!/bin/sh
# Instalador do DMaker @@VERSAO@@ para Linux x64 (script POSIX, sem makeself).
#
# O programa vem em partes (@@NOME_BASE@@-1.part, -2.part...) na MESMA pasta deste script. Ele confere o SHA-256 de cada
# parte e extrai em fluxo (cat das partes | tar), sem precisar de espaço para uma cópia inteira. Não pede sudo e não
# toca em /usr: instala só na sua pasta pessoal.
#
# Uso: sh @@NOME_BASE@@.run [--sim] [--programa PASTA] [--dados PASTA]
#   --sim            aceita os padrões sem perguntar
#   --programa PASTA onde fica o programa (padrão ~/.local/opt/dmaker)
#   --dados PASTA    onde ficam projetos, vozes, saídas e modelos (padrão ~/.local/share/dmaker)

set -eu

VERSAO="@@VERSAO@@"
NOME_BASE="@@NOME_BASE@@"
BYTES_PROGRAMA=@@BYTES_PROGRAMA@@
BYTES_DADOS=@@BYTES_DADOS@@

# <sha256> <tamanho em bytes> <arquivo>, na ordem em que as partes se juntam.
lista_partes() {
    cat <<'FIM_PARTES'
@@PARTES@@
FIM_PARTES
}

# As bibliotecas que o Chromium do pacote pede (do ldd feito no build); falta alguma, o instalador avisa, não falha.
lista_bibliotecas() {
    cat <<'FIM_BIBLIOTECAS'
@@BIBLIOTECAS@@
FIM_BIBLIOTECAS
}

# O pacote apt de cada biblioteca, em Ubuntu 22.04 (sufixo vazio) e 24.04 em diante (t64 onde o nome mudou).
pacote_apt() {
    case "$1" in
@@PACOTES_APT@@
        *) echo "" ;;
    esac
}

SIM=0
PROGRAMA=""
DADOS=""

mensagem() { printf '%s\n' "$*"; }
aviso() { printf 'AVISO: %s\n' "$*" >&2; }
falha() {
    printf 'ERRO: %s\n' "$*" >&2
    exit 1
}

ajuda() {
    sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
    case "$1" in
        --sim) SIM=1 ;;
        --programa)
            [ $# -ge 2 ] || falha "--programa pede uma pasta."
            PROGRAMA="$2"
            shift
            ;;
        --dados)
            [ $# -ge 2 ] || falha "--dados pede uma pasta."
            DADOS="$2"
            shift
            ;;
        -h | --ajuda | --help)
            ajuda
            exit 0
            ;;
        *) falha "Opção desconhecida: $1 (veja --ajuda)." ;;
    esac
    shift
done

[ -n "${HOME:-}" ] || falha "A variável HOME não está definida."
[ "$(id -u)" -ne 0 ] || aviso "Você está rodando como root: o instalador é por usuário e vai usar a pasta pessoal do root."

PASTA_DAS_PARTES=$(cd "$(dirname "$0")" && pwd)
BIN="$HOME/.local/bin"
APLICATIVOS="$HOME/.local/share/applications"
SERVICOS="$HOME/.config/systemd/user"

if [ -t 0 ] && [ "$SIM" -eq 0 ]; then
    INTERATIVO=1
else
    INTERATIVO=0
fi

# Caminhos entram em lançadores, no marcador e num sed: recusa o que quebraria isso.
caminho_seguro() {
    case "$1" in
        /*) ;;
        *) falha "Use um caminho absoluto (começando por /): $1" ;;
    esac
    case "$1" in
        *'"'* | *'$'* | *'`'* | *'\'* | *'&'* | *'|'* | *"'"*)
            falha "O caminho não pode ter aspas, \$, crase, barra invertida, & nem |: $1"
            ;;
    esac
    if [ "$(printf '%s' "$1" | wc -l)" -ne 0 ]; then
        falha "O caminho não pode ter quebra de linha."
    fi
}

absoluto() {
    case "$1" in
        /*) printf '%s' "$1" ;;
        "~") printf '%s' "$HOME" ;;
        "~/"*) printf '%s' "$HOME/${1#"~/"}" ;;
        *) printf '%s' "$PWD/$1" ;;
    esac
}

# Lê um valor do instalacao.json (uma chave por linha, escrito por este instalador): texto entre aspas ou true/false.
marcador_valor() {
    sed -n -e "s/^ *\"$2\": *\"\(.*\)\",\{0,1\} *\$/\1/p" -e "s/^ *\"$2\": *\(true\|false\),\{0,1\} *\$/\1/p" "$1" | head -n 1
}

pasta_vazia() {
    [ ! -d "$1" ] || [ -z "$(ls -A "$1" 2>/dev/null)" ]
}

# O df da primeira pasta que existe acima de $1 (a de destino ainda pode não existir).
livre_em_kb() {
    alvo="$1"
    while [ ! -d "$alvo" ] && [ "$alvo" != "/" ]; do
        alvo=$(dirname "$alvo")
    done
    df -Pk "$alvo" | awk 'NR==2 {print $4}'
}

dispositivo_de() {
    alvo="$1"
    while [ ! -d "$alvo" ] && [ "$alvo" != "/" ]; do
        alvo=$(dirname "$alvo")
    done
    df -P "$alvo" | awk 'NR==2 {print $1}'
}

perguntar() {
    # perguntar "texto" "padrão" -> resposta no stdout
    printf '%s [%s]: ' "$1" "$2" >&2
    read -r resposta || resposta=""
    if [ -z "$resposta" ]; then
        printf '%s' "$2"
    else
        printf '%s' "$resposta"
    fi
}

# ---- a instalação anterior (atualizar por cima) ----
PROGRAMA_PADRAO="$HOME/.local/opt/dmaker"
DADOS_PADRAO="$HOME/.local/share/dmaker"
ANTERIOR_PROGRAMA="${PROGRAMA:-$PROGRAMA_PADRAO}"
ANTERIOR_PROGRAMA=$(absoluto "$ANTERIOR_PROGRAMA")
ATUALIZANDO=0
OLLAMA_NOSSO_ANTES=false
if [ -f "$ANTERIOR_PROGRAMA/instalacao.json" ]; then
    ATUALIZANDO=1
    ANTES_DADOS=$(marcador_valor "$ANTERIOR_PROGRAMA/instalacao.json" dados)
    [ -z "$ANTES_DADOS" ] || DADOS_PADRAO="$ANTES_DADOS"
    OLLAMA_NOSSO_ANTES=$(marcador_valor "$ANTERIOR_PROGRAMA/instalacao.json" ollama_nosso)
fi

mensagem "DMaker $VERSAO para Linux x64"
mensagem ""

if [ -z "$PROGRAMA" ]; then
    if [ "$INTERATIVO" -eq 1 ]; then
        PROGRAMA=$(perguntar "Pasta do programa" "$PROGRAMA_PADRAO")
    else
        PROGRAMA="$PROGRAMA_PADRAO"
    fi
fi
if [ -z "$DADOS" ]; then
    if [ "$INTERATIVO" -eq 1 ]; then
        DADOS=$(perguntar "Pasta dos dados (projetos, vozes, saídas, modelos)" "$DADOS_PADRAO")
    else
        DADOS="$DADOS_PADRAO"
    fi
fi
PROGRAMA=$(absoluto "$PROGRAMA")
DADOS=$(absoluto "$DADOS")
caminho_seguro "$PROGRAMA"
caminho_seguro "$DADOS"
caminho_seguro "$HOME"

# O programa de uma instalação anterior só vale se for a mesma pasta escolhida agora.
if [ "$PROGRAMA" != "$ANTERIOR_PROGRAMA" ]; then
    ATUALIZANDO=0
    OLLAMA_NOSSO_ANTES=false
    if [ -f "$PROGRAMA/instalacao.json" ]; then
        ATUALIZANDO=1
        OLLAMA_NOSSO_ANTES=$(marcador_valor "$PROGRAMA/instalacao.json" ollama_nosso)
    fi
fi

# ---- as pastas não podem se misturar nem apagar o que não é do DMaker ----
if [ "$PROGRAMA" = "/" ] || [ "$DADOS" = "/" ] || [ "$PROGRAMA" = "$HOME" ] || [ "$DADOS" = "$HOME" ]; then
    falha "Escolha uma subpasta (não a raiz nem a sua pasta pessoal)."
fi
case "$DADOS/" in
    "$PROGRAMA"/*) falha "A pasta dos dados não pode ficar dentro da pasta do programa ($PROGRAMA)." ;;
esac
case "$PROGRAMA/" in
    "$DADOS"/*) falha "A pasta do programa não pode ficar dentro da pasta dos dados ($DADOS)." ;;
esac
if [ "$ATUALIZANDO" -eq 0 ] && ! pasta_vazia "$PROGRAMA"; then
    falha "A pasta $PROGRAMA já tem arquivos e não é uma instalação do DMaker. Escolha uma pasta nova ou vazia (--programa)."
fi

# ---- as partes ----
mensagem "Conferindo as partes em $PASTA_DAS_PARTES"
TOTAL_PARTES=0
while read -r soma tamanho nome; do
    [ -n "$nome" ] || continue
    arquivo="$PASTA_DAS_PARTES/$nome"
    [ -f "$arquivo" ] || falha "Falta a parte $nome ao lado deste script. Baixe todos os arquivos da release para a mesma pasta."
    real=$(wc -c <"$arquivo" | tr -d ' ')
    [ "$real" = "$tamanho" ] || falha "A parte $nome tem $real bytes e deveria ter $tamanho (download incompleto?)."
    TOTAL_PARTES=$((TOTAL_PARTES + 1))
    set -- "$@" "$arquivo"
done <<FIM_LEITURA
$(lista_partes)
FIM_LEITURA
[ "$TOTAL_PARTES" -gt 0 ] || falha "Este script não lista nenhuma parte (arquivo corrompido)."

while read -r soma tamanho nome; do
    [ -n "$nome" ] || continue
    mensagem "  SHA-256 de $nome..."
    calculada=$(sha256sum "$PASTA_DAS_PARTES/$nome" | awk '{print $1}')
    [ "$calculada" = "$soma" ] || falha "O SHA-256 de $nome não confere (esperado $soma, calculado $calculada). Baixe a parte de novo."
done <<FIM_LEITURA
$(lista_partes)
FIM_LEITURA

# ---- o espaço ----
necessario_programa_kb=$(((BYTES_PROGRAMA + BYTES_PROGRAMA / 10) / 1024 + 1))
necessario_dados_kb=$(((BYTES_DADOS + BYTES_DADOS / 10) / 1024 + 1))
livre_programa_kb=$(livre_em_kb "$PROGRAMA")
livre_dados_kb=$(livre_em_kb "$DADOS")
if [ "$(dispositivo_de "$PROGRAMA")" = "$(dispositivo_de "$DADOS")" ]; then
    soma_kb=$((necessario_programa_kb + necessario_dados_kb))
    [ "$livre_programa_kb" -ge "$soma_kb" ] || falha "Espaço insuficiente: preciso de uns $((soma_kb / 1048576)) GB em $PROGRAMA e $DADOS (mesmo disco) e há $((livre_programa_kb / 1048576)) GB livres."
else
    [ "$livre_programa_kb" -ge "$necessario_programa_kb" ] || falha "Espaço insuficiente em $PROGRAMA: preciso de uns $((necessario_programa_kb / 1048576)) GB e há $((livre_programa_kb / 1048576)) GB livres."
    [ "$livre_dados_kb" -ge "$necessario_dados_kb" ] || falha "Espaço insuficiente em $DADOS: preciso de uns $((necessario_dados_kb / 1048576)) GB e há $((livre_dados_kb / 1048576)) GB livres."
fi

# ---- as bibliotecas do Chromium ----
procurar_ldconfig() {
    if command -v ldconfig >/dev/null 2>&1; then
        command -v ldconfig
    elif [ -x /sbin/ldconfig ]; then
        echo /sbin/ldconfig
    elif [ -x /usr/sbin/ldconfig ]; then
        echo /usr/sbin/ldconfig
    fi
}
LDCONFIG=$(procurar_ldconfig)
if [ -n "$LDCONFIG" ]; then
    FALTAM=""
    PACOTES=""
    SUFIXO=""
    if [ -r /etc/os-release ]; then
        VERSAO_SO=$(sed -n 's/^VERSION_ID="\{0,1\}\([0-9.]*\)"\{0,1\}$/\1/p' /etc/os-release | head -n 1)
        SO_MAIOR=${VERSAO_SO%%.*}
        if [ -n "$SO_MAIOR" ] && [ "$SO_MAIOR" -ge 24 ] 2>/dev/null; then
            SUFIXO="t64"
        fi
    fi
    SAIDA_LDCONFIG=$("$LDCONFIG" -p 2>/dev/null || true)
    while read -r biblioteca; do
        [ -n "$biblioteca" ] || continue
        if ! printf '%s\n' "$SAIDA_LDCONFIG" | grep -qF "$biblioteca "; then
            FALTAM="$FALTAM $biblioteca"
            pacote=$(pacote_apt "$biblioteca")
            if [ -n "$pacote" ]; then
                case "$pacote" in
                    *"@T64@") pacote="${pacote%@T64@}$SUFIXO" ;;
                esac
                case " $PACOTES " in
                    *" $pacote "*) ;;
                    *) PACOTES="$PACOTES $pacote" ;;
                esac
            fi
        fi
    done <<FIM_LEITURA
$(lista_bibliotecas)
FIM_LEITURA
    if [ -n "$FALTAM" ]; then
        aviso "Faltam bibliotecas que o Chromium (composição em HTML e PDF do manual) pede:$FALTAM"
        if [ -n "$PACOTES" ]; then
            aviso "Para instalá-las: sudo apt install$PACOTES"
        fi
        aviso "O resto do DMaker funciona sem elas. Vou seguir com a instalação."
    fi
fi

# ---- o Ollama ----
INSTALAR_OLLAMA=0
if [ "$OLLAMA_NOSSO_ANTES" = "true" ]; then
    INSTALAR_OLLAMA=1
elif ! command -v ollama >/dev/null 2>&1; then
    INSTALAR_OLLAMA=1
fi

# ---- extrair ----
if [ "$ATUALIZANDO" -eq 1 ]; then
    mensagem "Atualizando por cima de $PROGRAMA (os seus dados em $DADOS ficam)."
    # O Python é trocado inteiro, para não sobrar módulo da versão anterior.
    for antigo in python assets templates bin licencas lancadores; do
        rm -rf "${PROGRAMA:?}/$antigo"
    done
    if [ "$INSTALAR_OLLAMA" -eq 1 ]; then
        rm -rf "${PROGRAMA:?}/ollama"
    fi
fi
mkdir -p "$PROGRAMA" "$DADOS"

mensagem "Extraindo o programa em $PROGRAMA (alguns minutos)..."
if [ "$INSTALAR_OLLAMA" -eq 1 ]; then
    cat "$@" | tar -xzf - -C "$PROGRAMA" --strip-components=1 --wildcards 'programa/*'
else
    cat "$@" | tar -xzf - -C "$PROGRAMA" --strip-components=1 --wildcards --exclude='programa/ollama' 'programa/*'
fi
mensagem "Extraindo os modelos em $DADOS (só os que ainda não existem)..."
cat "$@" | tar -xzf - -C "$DADOS" --strip-components=1 --skip-old-files --wildcards 'dados/*'

# ---- lançadores ----
mkdir -p "$BIN" "$APLICATIVOS"
preencher() {
    # preencher modelo destino
    sed "s|@@PROGRAMA@@|$PROGRAMA|g; s|@@DADOS@@|$DADOS|g; s|@@BIN@@|$BIN|g" "$1" >"$2"
}
preencher "$PROGRAMA/lancadores/dmaker.sh" "$BIN/dmaker"
preencher "$PROGRAMA/lancadores/dmaker-mcp.sh" "$BIN/dmaker-mcp"
chmod 755 "$BIN/dmaker" "$BIN/dmaker-mcp"
preencher "$PROGRAMA/lancadores/dmaker.desktop" "$APLICATIVOS/dmaker.desktop"
chmod 644 "$APLICATIVOS/dmaker.desktop"
cp "$PROGRAMA/lancadores/desinstalar.sh" "$PROGRAMA/desinstalar.sh"
chmod 755 "$PROGRAMA/desinstalar.sh"
LANCADORES="\"$BIN/dmaker\", \"$BIN/dmaker-mcp\""

SERVICO_OLLAMA=false
OLLAMA_NOSSO=false
if [ "$INSTALAR_OLLAMA" -eq 1 ] && [ -x "$PROGRAMA/ollama/bin/ollama" ]; then
    OLLAMA_NOSSO=true
    preencher "$PROGRAMA/lancadores/ollama.sh" "$BIN/ollama"
    chmod 755 "$BIN/ollama"
    LANCADORES="$LANCADORES, \"$BIN/ollama\""
    if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
        mkdir -p "$SERVICOS"
        preencher "$PROGRAMA/lancadores/dmaker-ollama.service" "$SERVICOS/dmaker-ollama.service"
        if systemctl --user daemon-reload && systemctl --user enable --now dmaker-ollama.service >/dev/null 2>&1; then
            SERVICO_OLLAMA=true
            mensagem "Ollama instalado e ligado como serviço de usuário (dmaker-ollama)."
        else
            aviso "Não consegui ligar o serviço do Ollama. Suba-o à mão com: ollama serve"
        fi
    else
        mensagem "Ollama instalado. Este sistema não tem systemd de usuário: suba-o com: ollama serve"
    fi
elif [ "$INSTALAR_OLLAMA" -eq 0 ]; then
    mensagem "O Ollama já está neste computador: não instalei outro."
fi

# ---- o marcador (o mesmo do Windows, com o que o desinstalador precisa) ----
cat >"$PROGRAMA/instalacao.json" <<FIM_MARCADOR
{
  "versao": "$VERSAO",
  "dados": "$DADOS",
  "programa": "$PROGRAMA",
  "lancadores": [$LANCADORES],
  "desktop": "$APLICATIVOS/dmaker.desktop",
  "ollama_nosso": $OLLAMA_NOSSO,
  "servico_ollama": $SERVICO_OLLAMA
}
FIM_MARCADOR

mensagem ""
mensagem "DMaker $VERSAO instalado."
mensagem "  programa: $PROGRAMA"
mensagem "  dados:    $DADOS"
mensagem "  comandos: $BIN/dmaker, $BIN/dmaker-mcp"
case ":${PATH:-}:" in
    *":$BIN:"*) ;;
    *)
        mensagem ""
        mensagem "$BIN não está no seu PATH. Para usar o comando dmaker, acrescente ao ~/.profile:"
        mensagem "  export PATH=\"$BIN:\$PATH\""
        ;;
esac
mensagem ""
mensagem "Abra a interface com: dmaker ui   (ou pelo menu de aplicativos)"
mensagem "Modelo de linguagem (Ollama): ollama pull gpt-oss:20b"
mensagem "Ligar ao Claude Code:  claude mcp add dmaker -- $BIN/dmaker-mcp"
mensagem "Para desinstalar:      $PROGRAMA/desinstalar.sh"
