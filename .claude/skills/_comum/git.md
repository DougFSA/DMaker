# Git: um chamado, um PR

Referência compartilhada pelas skills do DMaker e pelos subagentes
`dmaker-executor` e `dmaker-apurador`.

Remoto: https://github.com/DougFSA/DMaker. Branches de longa vida: `main`
(o que está lançado) e `develop` (o que foi aprovado e mergeado, ainda não
lançado). A `develop` sai da `main` e é criada pelo Douglas; se ela não existir,
**pare e avise**, não crie por conta própria.

## Convenções

- **Branch:** `feat/dmk-XXX-slug-curto` para funcionalidade, `fix/dmk-XXX-slug-curto`
  para correção. Slug em minúsculas, sem acento. Sempre sai da `develop`.
- **Commit:** `tipo(DMK-XXX): resumo no imperativo, sem acento, até 72 colunas`.
  O corpo explica **por que**, não o que: o diff já diz o que. Sempre termina com:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  ```
- **Corpo do PR:** mesma explicação do comentário do Jira, e termina com:
  ```
  🤖 Generated with [Claude Code](https://claude.com/claude-code)
  ```
- **Nunca** commitar direto na `develop` nem na `main`. As únicas exceções são
  as duas que as skills autorizam por escrito: o `dmaker-redesenvolvimento-develop`
  (correção direta na `develop`) e o fechamento do CHANGELOG no `dmaker-producao`.

## A regra que evita o engarrafamento: saia da `develop`

**Por padrão, todo chamado sai da `develop`.** Empilhe um branch sobre outro
**só quando o código de um precisar do código do outro para importar ou fazer
sentido**, e não porque foram feitos na mesma sessão.

O motivo é concreto, e aconteceu no MedlyCare. Em agosto/2026 a rodada inteira
virou uma pilha de 19 branches encadeados por ordem de execução, não por
dependência real. O resultado: um único card reprovado lá embaixo prendeu **13
cards já aprovados** acima dele, e cada correção de redesenvolvimento obrigava a
rebasear 15 branches. Nenhum desses 13 dependia do reprovado: a dependência era
um acidente de cronologia.

Chamados independentes que saem da `develop` são mergeáveis em qualquer ordem: o
Douglas aprova o que quiser, na hora que quiser, e o que ainda está em teste não
segura ninguém.

**Quando empilhar de fato:** o card B usa uma função, classe, campo da spec ou
etapa do pipeline que só existe no card A. Aí `gh pr create --base <branch-do-A>`
e diga no corpo do PR que ele depende do A. Quando A for mergeado, retarget o B
para `develop`.

**Como saber se dá para não empilhar:** se os dois cards mexem em arquivos
diferentes, saem os dois da `develop` sem pensar. Se mexem no mesmo arquivo mas
em trechos distintos, ainda saem da `develop`: o conflito de merge, se vier, é
pequeno e local. Só empilhe quando B **não roda** sem A.

## Quando a pilha existe mesmo assim

Às vezes uma pilha é legítima. Aí o que protege o código:

**1. Calcule todos os pontos de fork ANTES de rebasear qualquer coisa.**
`git merge-base` devolve a resposta errada depois que o pai foi reescrito, e o
erro é silencioso: some com commits sem conflito nenhum.

```bash
prev=develop
while read -r b; do
  echo "$b|$(git merge-base "$prev" "$b")|$(git rev-parse "$b")"
  prev="$b"
done < ordem-da-pilha.txt
```

Guarde essa tabela. Depois rebaseie de baixo para cima, sempre com o fork
**gravado antes**:

```bash
git rebase --onto <pai-novo> <fork-gravado> <branch>
```

**2. Confira que nenhum card sumiu.** Antes e depois da cascata:

```bash
git log --oneline develop..<topo-da-pilha> | grep -oE 'DMK-[0-9]+' | sort -u
```

As duas listas têm que bater. Esta é a checagem que pega o rebase que "deu certo"
e comeu um commit, o tipo de estrago que só aparece semanas depois.

**3. Rode os portões no TOPO da pilha, não só no branch que você mexeu.** O topo
é o único lugar onde todo o código coexiste; é lá que uma resolução de conflito
malfeita aparece (`_comum/qualidade.md`).

**4. `--force-with-lease`, nunca `--force`.** Vale ligar o `rerere`
(`git config rerere.enabled true`): a mesma resolução de conflito é reaproveitada
nas cascatas seguintes. Os conflitos recorrentes tendem a cair sempre nos mesmos
arquivos (`CHANGELOG.md`, `cli.py`, `mcp_server.py`, `pipeline/projects.py`).

**5. Conflito se resolve mantendo os DOIS lados.** Em cascata, os dois lados são
trabalho aprovado de cards diferentes; escolher um é apagar um chamado. Se os
dois lados forem de verdade incompatíveis, pare e pergunte.

## Merge na develop

Só entra na `develop` o que está em **`Concluído`** (aprovado pelo Douglas) e
ainda tem PR aberto. `Concluído` agrupa "aprovado, aguardando merge" e "já na
`develop` ou na `main`"; o que distingue os dois é o estado do PR (ver
`_comum/jira.md`). Merge commit, que é a convenção do repositório:

```bash
gh pr merge <n> --merge
```

**Nunca use `--delete-branch` quando o branch é base de outro PR.** O GitHub
**fecha** o PR filho quando a base some, e ele não reabre (`gh pr reopen` falha).
Já aconteceu no MedlyCare (PR #124) e a saída foi abrir um PR novo. A ordem certa:

```bash
gh pr edit <filho> --base develop   # 1. retarget do filho
gh pr merge <pai> --merge           # 2. merge do pai, sem --delete-branch
```

Ao final de uma leva, reporte o que **não** entrou e por quê. Card aprovado que
ficou de fora por estar preso atrás de um reprovado é informação que o Douglas
precisa para decidir o que testar primeiro.

## Higiene

- Antes de commitar, `git status --short`. Adicione caminhos explícitos no
  `git add`, nunca `-A`. Arquivos de verificação (ver `_comum/qualidade.md`) e
  saídas de teste não podem vazar para o commit.
- **Não vão para o git, nunca:** `projects/`, `output/`, `cache/`, `bin/` e
  `assets/voices/`. Projetos têm vídeos de clientes e de casamentos; vozes
  clonadas são dado pessoal. Todos já estão no `.gitignore`, mas confira o
  `git status` antes de cada commit: um `git add -f` ou um arquivo de outra pasta
  com extensão de mídia escapa do filtro.
- **Nada de nome de cliente, áudio ou vídeo real** em commit, PR ou Jira, além do
  estritamente necessário para descrever o teste (por exemplo, "projeto de teste
  com duas câmeras", não o nome do casal). Mídia que serviu de fixture de teste
  é sintética, gerada pelo próprio teste.
