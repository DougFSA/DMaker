---
name: dmaker-merge-develop
description: Mergeia na branch develop do DMaker os PRs dos chamados de uma versão que o Douglas já aprovou e moveu para a coluna Concluído do Jira (projeto DMK) e cujo PR ainda está aberto, respeitando a ordem das PRs empilhadas e sem quebrar PR filho. Use sempre que ele pedir para mergear os aprovados do DMaker, "mergear os aprovados", "fazer o merge dos aprovados", "subir para a develop", "os que estão concluídos", "mergear o que eu aprovei" ou qualquer variação de juntar na develop o que passou no teste manual. Não mexe na main nem cria tag: para lançar a versão, use dmaker-producao.
---

# Merge na develop: DMaker

Entra na `develop` o que o Douglas aprovou, e só isso. A coluna **`Concluído`** é
o aval dele, mas ela guarda dois estados (ver `_comum/jira.md`):

1. **Aprovado, PR ainda aberto:** é o que esta skill mergeia.
2. **Já na `develop` ou na `main`:** o PR já não está aberto; não há o que fazer.

O que distingue os dois é o **estado do PR**, não o Jira. Nada entra sem estar em
`Concluído`.

Leia junto:

- `.claude/skills/_comum/delegacao.md`: **como dividir o trabalho com os subagentes**
- `.claude/skills/_comum/jira.md`: colunas, consultas, o significado duplo de Concluído
- `.claude/skills/_comum/git.md`: convenções, **regras de merge de PR empilhada**
- `.claude/skills/_comum/qualidade.md`: portões

## Divisão do trabalho

O merge é irreversível na prática, então a linha aqui é mais conservadora que nas
outras skills: **o mapa e a decisão são seus, e o comando de merge também.**

| Você (Opus) | Subagente Sonnet |
| --- | --- |
| Perguntar a versão, apresentar o mapa, relatório | - |
| Montar a cadeia e decidir mergeável × preso | - |
| **Executar os merges** (`gh pr edit` / `gh pr merge`) | - |
| - | Levantar cards, PRs, bases e estado dos PRs (`dmaker-apurador`) |
| - | Rodar os portões na `develop` depois da leva (`dmaker-apurador`) |
| - | Consertar a `develop` se a leva quebrar (`dmaker-executor`) |

Os merges ficam com você não por desconfiança do Sonnet, mas porque são poucos
comandos de saída curta: delegá-los economizaria quase nada e colocaria a decisão
de "retargetar antes ou depois" a um passo de distância de quem desenhou a cadeia.

## 1. Pergunte a versão e levante os aprovados

```
project = DMK AND fixVersion = "<versão>" AND status = 10076 ORDER BY key ASC
```

(`10076` = Concluído.) Essa lista mistura aprovados esperando merge com cards já
mergeados em levas anteriores. O próximo passo separa um do outro.

## 2. Monte o mapa antes de mergear qualquer coisa

Este é o passo que evita estrago. O `dmaker-apurador` traz a matéria-prima:
peça, numerado: (1) os cards da versão em `Concluído`; (2) o PR **aberto** de cada
um, com `headRefName` e `baseRefName`; (3) para os que não têm PR aberto, se o
card já está na `develop` (`git log --oneline origin/develop | grep -i DMK-XXX`);
(4) o estado do PR de cada um (aberto, mergeado, fechado sem merge), porque um PR
**fechado sem merge** é anomalia que você precisa ver.

```bash
gh pr list --state open --json number,headRefName,baseRefName,title --limit 60
gh pr list --state open --search "DMK-XXX" --json number,headRefName,baseRefName
```

**A cadeia você desenha.** Com os dados na mão, responda três perguntas por card:

- **Tem PR aberto?** Card em `Concluído` sem PR aberto já foi mergeado numa leva
  anterior (ou antes do fluxo de develop existir): confirme com
  `git log --oneline origin/develop | grep -i DMK-XXX` e tire da fila em vez de
  procurar o que não existe. Se não está na `develop` **nem** tem PR aberto, não
  deixe passar: reporte como anomalia.
- **Qual é a base do PR?** Se for `develop`, é independente e entra a qualquer
  momento. Se for outro branch, ele está empilhado.
- **A cadeia de bases até a `develop` está TODA aprovada?** Um PR empilhado
  arrasta consigo tudo que está abaixo dele. Se um único elo da cadeia não estiver
  em `Concluído`, esse PR **não pode ser mergeado**: mergeá-lo colocaria na
  `develop` código que o Douglas ainda não aprovou, ou pior, que ele reprovou.

Desenhe a cadeia (`develop ← A ← B ← C`) e classifique cada card em
**mergeável agora** ou **preso atrás de <card>**. Mostre isso ao Douglas antes de
começar: é a informação que ele usa para decidir o que testar primeiro.

Como o padrão do fluxo é cada card sair da `develop`, a maioria será "base
`develop`, mergeável agora". Se aparecer pilha longa, algo fugiu da regra de
`_comum/git.md`: diga isso no relatório.

## 3. Mergeie, de baixo para cima

Para cada PR mergeável, do mais próximo da `develop` para o mais distante:

1. **Confira o PR**: `gh pr view <n> --json mergeable,mergeStateStatus,baseRefName`.
   Não há CI para consultar (`gh pr checks` vem vazio), então o PR não carrega
   prova de portão. Se o card é de risco e o comentário de entrega não traz
   `ruff` e `pytest` verdes com contagem, pare e pergunte antes de mergear.
   `mergeable = CONFLICTING` não merge: resolva o conflito no branch (mantendo os
   dois lados) e só então siga.
2. **Retarget do filho ANTES do merge do pai**, se houver filho:
   ```bash
   gh pr edit <filho> --base develop
   gh pr merge <pai> --merge
   ```
   Nunca use `--delete-branch` num PR que serve de base. O GitHub **fecha** o PR
   filho quando a base some, e `gh pr reopen` falha: já custou um PR refeito do
   zero no MedlyCare (`_comum/git.md`).
3. **Merge commit (`--merge`), nunca squash.** O histórico da `develop` é de merge
   commits; com squash, cada PR de cima passa a ver o diff do de baixo como
   estranho e conflita.
4. Registre no card uma linha de rastro:
   `🔀 Mergeado na develop: <sha do merge> (PR #N)`.
   A skill de produção usa isso para cruzar "aprovado" com "realmente na develop".

**Não mova o card de coluna.** `Concluído` já é onde ele deve ficar.

O `CHANGELOG.md` é o arquivo que mais conflita entre PRs independentes (todos
acrescentam linha no mesmo bloco `[Não lançado]`). Se aparecer conflito só nele,
mantenha as linhas dos dois lados e continue.

## 4. Verifique a develop depois da leva

Merges podem entrar limpos e ainda assim quebrar: dois cards que passaram nos
portões isolados podem se contradizer quando juntos. E como não há CI, esta é a
primeira vez que a soma dos cards é testada.

Isto é levantamento, e é onde está o volume desta skill: mande para o
`dmaker-apurador` (autorizando o `checkout` e o `pull`, que ele não faz por
padrão), pedindo três coisas:

1. Atualizar a `develop`:
   ```bash
   git fetch origin && git checkout develop && git pull
   ```
2. Rodar os portões (`_comum/qualidade.md`), os três, em primeiro plano e com
   `timeout: 600000`: `ruff check src tests`, `ruff format --check src tests`,
   `pytest -q`. Verde é uma linha por portão; vermelho são as linhas do erro, não
   o log.
3. Conferir se algum conflito de merge comeu trabalho:
   ```bash
   git log --oneline <sha-antes-da-leva>..develop | grep -oE 'DMK-[0-9]+' | sort -u
   ```
   Mande a lista dos cards que você mergeou e peça a diferença entre as duas:
   todos têm que estar aí. Peça também que confira se `MEZZ_VERSION` em
   `pipeline/segments.py` está coerente com os cards da leva que mudaram a receita
   do mezanino.

Se quebrar, **conserte na hora**: despache um `dmaker-executor` com o erro e a
causa provável (briefing dizendo que é um conserto de integração na `develop`,
caso do `dmaker-redesenvolvimento-develop`), e não feche a leva antes de a
`develop` estar verde. Uma `develop` quebrada trava todo mundo e é o pior lugar
para descobrir isso amanhã.

## 5. Relatório

Em PT-BR:

- **Entrou:** card + PR + uma linha do que é.
- **Ficou de fora e por quê**, separando "preso atrás do card X, que está em
  redesenvolvimento" de "PR com conflito" de "sem PR, já estava na develop" de
  anomalia (sem PR e fora da `develop`). Card aprovado que não entrou é a
  informação mais importante do relatório.
- **Estado dos portões** na `develop` depois da leva.
- Se ficou tudo dentro, diga que a versão está pronta para o release e ofereça a
  skill `dmaker-producao`, sem executá-la por conta própria.
