---
name: dmaker-merge-develop
description: SKILL DE EXCEÇÃO, fora do fluxo normal. Mergeia na develop do DMaker PRs de chamados (projeto DMK) que ficaram abertos por algum motivo, por exemplo os entregues antes de 23/10/2026, quando o PR ainda esperava o teste manual, ou um PR que o executor não conseguiu mergear. No fluxo atual o executor já mergeia o PR na entrega, então NÃO use esta skill para chamados novos nem para correções. Use só quando o Douglas pedir explicitamente para mergear PRs que ficaram abertos ("mergeia os PRs abertos do DMaker", "sobrou PR aberto", "limpa os PRs antigos"). Respeita a ordem das PRs empilhadas e não quebra PR filho. Não mexe na main nem cria tag: para lançar a versão, use dmaker-producao.
---

# Merge de PRs que ficaram abertos: DMaker (exceção)

**Esta skill não faz parte do fluxo normal.** Desde 23/10/2026 o executor abre o PR
e **já o mergeia** ao entregar o card (`_comum/git.md`), então a `develop` recebe o
código na entrega, o Douglas testa nela, e `Concluído` significa só "testado e
aprovado". Não existe mais a fila "aprovado, aguardando merge" que esta skill
atendia.

Ela sobrevive para o que sobrar do fluxo antigo ou de um acidente:

- PRs entregues **antes** da mudança de fluxo, ainda abertos, com o card em
  `Teste Manual` ou `Concluído`, possivelmente empilhados em outros branches.
- Um PR que o executor abriu mas não conseguiu mergear (conflito não resolvido,
  portão vermelho na mistura) e que foi destravado depois.

**Decisão registrada (23/10/2026):** em vez de apagar a skill, ela foi mantida
com este escopo estreito, porque os PRs empilhados do fluxo antigo existem e
mergeá-los na ordem certa (retarget do filho antes do pai) é um procedimento fácil
de errar e caro de refazer. Quando não restar nenhum PR antigo aberto, esta skill
pode ser removida.

Leia junto:

- `.claude/skills/_comum/delegacao.md`: **como dividir o trabalho com os subagentes**
- `.claude/skills/_comum/jira.md`: colunas e consultas
- `.claude/skills/_comum/git.md`: convenções, merge na entrega, trava de merge
- `.claude/skills/_comum/qualidade.md`: portões

## Divisão do trabalho

O merge é irreversível na prática, então a linha aqui é conservadora: **o mapa e
a decisão são seus, e o comando de merge também.**

| Você (Opus) | Subagente Sonnet |
| --- | --- |
| Montar a cadeia e decidir mergeável × preso; relatório | - |
| **Executar os merges** (`gh pr edit` / `gh pr merge`) | - |
| - | Levantar PRs abertos, bases, cards e estados (`dmaker-apurador`) |
| - | Rodar os portões na `develop` depois da leva (`dmaker-apurador`) |
| - | Consertar a `develop` se a leva quebrar (`dmaker-executor`) |

## 1. Levante os PRs abertos

Nada de perguntar versão: o critério é o estado do PR, não a versão. Mande o
`dmaker-apurador`, numerado: (1) todos os PRs abertos
(`gh pr list --state open --json number,headRefName,baseRefName,title --limit 60`);
(2) o card de cada um e o status dele no Jira; (3) o último comentário de entrega
do card (para ver se traz `ruff` e `pytest` verdes com contagem); (4) se o
`mergeable` é `CONFLICTING`.

**Mostre a lista ao Douglas e peça a confirmação do que mergear.** A coluna do
Jira não decide mais o merge: ele pode querer mergear um PR em `Teste Manual`
justamente para testá-lo na `develop`. A decisão é dele, caso a caso.

## 2. Monte a cadeia

Para cada PR da lista confirmada, a base é `develop` (independente, entra a
qualquer momento) ou outro branch (empilhado). Um PR empilhado arrasta tudo que
está abaixo dele: se um elo da cadeia não estiver na lista confirmada, esse PR
**não pode ser mergeado**. Desenhe a cadeia (`develop ← A ← B ← C`), classifique
cada card em **mergeável agora** ou **preso atrás de <card>**, e mostre ao Douglas
antes de começar.

## 3. Mergeie, de baixo para cima

Para cada PR mergeável, do mais próximo da `develop` para o mais distante:

1. **Confira o PR**: `gh pr view <n> --json mergeable,mergeStateStatus,baseRefName`.
   `mergeable = CONFLICTING` não merge: resolva o conflito no branch (mantendo os
   dois lados) e só então siga. Se o card é de risco e o comentário de entrega não
   traz `ruff` e `pytest` verdes com contagem, pare e pergunte.
2. **Traga a `develop` para o branch e rode os portões** se veio código novo
   (`_comum/git.md` → "Antes de mergear"), e use a trava de merge.
3. **Retarget do filho ANTES do merge do pai**, se houver filho:
   ```bash
   gh pr edit <filho> --base develop
   gh pr merge <pai> --merge
   ```
   **Sem `--delete-branch` num PR que serve de base.** O GitHub **fecha** o PR
   filho quando a base some, e `gh pr reopen` falha: já custou um PR refeito do
   zero no MedlyCare. Apague o branch do pai só depois de o filho estar na `develop`.
4. **Merge commit (`--merge`), nunca squash.**
5. Registre no card uma linha de rastro, porque a auditoria de produção cruza o
   card com a `develop` por ela: `🔀 Mergeado na develop: <sha do merge> (PR #N)`.

**Não mova o card de coluna.** Quem mexe nas colunas é a entrega (`51`) e o
Douglas (`61`); esta skill não decide aprovação.

O `CHANGELOG.md` é o arquivo que mais conflita entre PRs independentes. Se
aparecer conflito só nele, mantenha as linhas dos dois lados e continue.

## 4. Verifique a develop depois da leva

Merges podem entrar limpos e ainda assim quebrar: dois cards que passaram nos
portões isolados podem se contradizer juntos, e sem CI esta é a primeira vez que a
soma é testada. Mande o `dmaker-apurador` (autorizando `checkout` e `pull`):

1. `git fetch origin && git checkout develop && git pull`.
2. Os três portões (`_comum/qualidade.md`), em primeiro plano e com
   `timeout: 600000`. Verde é uma linha por portão; vermelho são as linhas do erro.
3. A conferência de que nenhum conflito comeu trabalho:
   `git log --oneline <sha-antes-da-leva>..develop | grep -oE 'DMK-[0-9]+' | sort -u`
   contra a lista dos cards mergeados, e a coerência do `MEZZ_VERSION` em
   `pipeline/segments.py`.

Se quebrar, **conserte na hora**: despache um `dmaker-executor` (branch
`fix/...`, PR e merge imediato, como qualquer correção) e não feche a leva antes
de a `develop` estar verde.

## 5. Relatório

Em PT-BR:

- **Entrou:** card + PR + uma linha do que é.
- **Ficou de fora e por quê:** preso atrás de outro, com conflito, ou fora da
  lista confirmada.
- **Estado dos portões** na `develop` depois da leva.
- Se isso zerou os PRs antigos, diga que a skill pode ser removida.
