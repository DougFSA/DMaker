---
name: dmaker-redesenvolvimento-develop
description: Corrige os chamados do DMaker que o Douglas reprovou testando a DEVELOP, ou seja, código que já foi mergeado e voltou para a coluna Redesenvolvimento do Jira (projeto DMK). Conserta direto na develop, sem branch nem PR, e devolve o card para Teste Manual para ele testar de novo na develop. Use quando ele falar em "achei um erro na develop", "testei na develop e quebrou", "voltei uns chamados da develop", "corrige na develop", "redev da develop" ou reprovar algo do DMaker que já está mergeado. Para cards reprovados que ainda NÃO foram mergeados (têm PR aberto), use dmaker-redesenvolvimento.
---

# Redesenvolvimento na develop: DMaker

O Douglas testa a `develop` rodando local (`git checkout develop`, `dmaker ui` ou
a CLI). Quando acha um defeito num card que já foi mergeado, manda o card para
**`Redesenvolvimento`** e escreve o que viu. Esta skill pega esses cards,
conserta **direto na `develop`** e devolve cada um para **`Teste Manual`**, para
ele testar de novo na `develop`. Quando aprovar, ele mesmo move para `Concluído`.

Leia junto:

- `.claude/skills/_comum/delegacao.md`: **como dividir o trabalho com os subagentes**
- `.claude/skills/_comum/jira.md`: colunas, comentário de entrega, **como abrir os prints**
- `.claude/skills/_comum/qualidade.md`: portões locais (sem CI), verificação real, testes de regressão
- `.claude/skills/_comum/git.md`: convenção de commit

## Divisão do trabalho

Como na skill irmã, **o diagnóstico é seu**, e aqui pesa mais ainda, porque a
causa costuma estar no encontro entre dois cards, não dentro de um (passo 2).

| Você (Opus) | Subagente Sonnet |
| --- | --- |
| Fila, ordem, apresentação ao Douglas, relatório | - |
| **Diagnosticar a causa**, inclusive olhar o merge que comeu trabalho | - |
| Escrever o comentário de entrega | - |
| - | Levantar cards, comentários, entrega anterior, `git log` (`dmaker-apurador`) |
| - | Reproduzir/medir quando você pedir: render, QA, transcrição (`dmaker-apurador`) |
| - | Aplicar a correção, teste, portões, commit e push na `develop`, Jira (`dmaker-executor`) |

O briefing do executor **precisa dizer que a skill é esta**: é um dos dois casos
em que ele tem licença para commitar direto na `develop`, e a definição dele o
proíbe por padrão.

## Esta skill é a exceção autorizada ao "nunca commite na develop"

`_comum/git.md` diz para nunca commitar direto na `develop`. **Aqui é diferente, e
é a mesma exceção que o fluxo do MedlyCare tem:** o código já está na `develop`, é
ali que o Douglas testa, e abrir um PR para um ajuste de duas linhas só adiciona
latência entre o defeito e o novo teste.

O preço disso é que **não há PR para registrar nem revisar o ajuste**, e o DMaker
**não tem CI** para segurar nada. O que protege a `develop` é só o portão do passo
3.3. Um push que quebra a `develop` trava todo o trabalho do Douglas: é o único
jeito de esta skill dar errado, e é por isso que os portões aqui não são
negociáveis.

## 1. Levante a fila e confirme que é caso desta skill

Mande o `dmaker-apurador` levantar, numa tacada só:

```
project = DMK AND status = 10073 ORDER BY priority DESC, updated DESC
```

(`10073` = Redesenvolvimento.) Peça, por card: (1) chave, título, prioridade; (2)
**o que o Douglas apontou**, citado do comentário mais recente dele; (3) se há
print ou arquivo anexado, com a data; (4) **o que a entrega anterior afirmou ter
resolvido**, citado; (5) o veredito de roteamento do parágrafo abaixo, com a
evidência.

**Não pergunte a versão.** O critério de corte aqui não é a versão, é **se o
código já está na `develop`**, e isso se verifica, não se pergunta:

```bash
git fetch origin && git log --oneline origin/develop | grep -i 'DMK-XXX'
gh pr list --state open --search "DMK-XXX" --json number,headRefName
```

- **Achou o card na `develop` e não há PR aberto** → é caso desta skill.
- **Não achou na `develop`, e existe PR aberto** → é da `dmaker-redesenvolvimento`.
  Não toque; cite no relatório final para não sumir da vista.

Deixe explícito no pedido que o `grep` precisa ser case-insensitive: pode haver
commits com `dmk-16` em minúsculas, e um `grep 'DMK-16'` devolve vazio e faz
concluir errado que o card não entrou.

Mostre a fila ao Douglas com uma linha por card dizendo **o que ele apontou**
(não o título do card), na ordem em que vai atacar: prioridade primeiro; no empate,
do mais fácil ao mais difícil (`_comum/jira.md` → "Ordem de trabalho"). Depois
siga sem pedir autorização card a card.

## 2. O último comentário é o chamado

Esta etapa é **sua**, não do subagente. Leia **o comentário mais recente do
Douglas**, não a descrição do card. A descrição descreve a funcionalidade; o
comentário descreve o que quebrou. São coisas diferentes e só a segunda importa
agora.

- **Abra o print você mesmo.** Quase sempre tem um, o texto sozinho engana, e
  descrito de segunda mão engana mais. `_comum/jira.md` explica como ver (Chrome
  logado do Douglas → issue → anexo).
- **Releia a entrega anterior no card**: o apurador já trouxe a citação. O que
  foi afirmado como resolvido, e que evidentemente não resolveu, aponta direto
  para a hipótese errada.
- **Reproduza ou meça antes de corrigir.** Um render de reprodução na `develop`,
  o `dmaker qa`, a transcrição com o `WhisperTranscriber`, RMS e duração
  transformam palpite em número (`_comum/qualidade.md`). Montar a reprodução e
  colher as medidas é trabalho de `dmaker-apurador`: mande a hipótese e as medidas
  que quer. **A leitura dos números é sua.**

Cuidado com o padrão que já custou rodadas (no MedlyCare, e vale igual aqui):
**corrigir o sintoma onde ele foi descrito.** A causa costuma estar a três
camadas de distância. Pergunte **por que a tentativa anterior não pegou isso**
antes de dar o problema por entendido.

### Um defeito que só aparece na develop costuma ser de integração

Este é o ponto em que esta skill difere de verdade da irmã. O card passou nos
portões sozinho, no PR dele, e só quebrou depois de conviver com os outros. Então
a causa provável **não é o card**: é o encontro dele com outro.

- Dois cards mexeram na mesma etapa do pipeline ou na mesma tela da interface e
  um desfez o do outro.
- Uma resolução de conflito de merge escolheu um lado e comeu o outro
  (`_comum/git.md` → "Conflito se resolve mantendo os DOIS lados").
- **`MEZZ_VERSION`:** dois cards mudaram a receita do mezanino, o conflito foi
  resolvido ficando com um dos números, e um dos dois deixou de invalidar o
  cache. Ou o contrário: ninguém incrementou, e o Douglas está vendo trecho velho
  do `cache/mez`. Antes de achar que o conserto não pegou, limpe o cache
  (`dmaker clean`, avisando-o se ele tiver render em andamento) e refaça.
- A spec ganhou campo em um card e outro card passou a validar de outro jeito.
- O `CHANGELOG.md` perdeu uma linha na resolução de conflito.

Antes de reescrever a lógica do card, **olhe o merge**: `git log --oneline` no
arquivo suspeito e `git show <merge>` costumam mostrar o trabalho que sumiu. Se
foi isso, a correção é restaurar o lado comido, não reimplementar o card. Peça o
levantamento ao apurador (quais commits tocaram o arquivo desde o merge do card,
e o que a resolução de conflito descartou), mas **a conclusão é sua**.

## 3. Despache a correção

Os passos 3.1 a 3.4 abaixo são o conteúdo do briefing do `dmaker-executor`
(`_comum/delegacao.md`), não trabalho seu. Um card por subagente, e **um
executor por vez** mesmo quando os cards não se tocam: ver `_comum/delegacao.md`
→ "Nunca dois executores ao mesmo tempo". Aqui a regra pesa ainda mais: são
commits diretos na `develop`, sem PR para isolar o estrago.

O briefing precisa carregar, além da causa diagnosticada e do porquê a tentativa
anterior não pegou:

- **Que a skill é a `dmaker-redesenvolvimento-develop`**: a licença de
  commitar direto na `develop`, com o motivo (não há PR; é a exceção combinada).
- **Que não há CI nem PR para segurar erro**, e por isso os portões do passo 3.3
  são inegociáveis.
- As transições do passo 3.4, na ordem.
- O comentário de entrega **verbatim** que você escreveu no passo 4.

Quando o retorno chegar, confira contra o critério de aceite e leia os DESVIOS.
Se algum portão ficou vermelho, isso não é "entregue": redespache o conserto
antes de pegar o próximo card. Como o commit já está na `develop`, vale você
mesmo rodar a conferência que prova a causa corrigida (o comando de reprodução
do apurador, de novo).

### 3.1. Trabalhar na develop, atualizada

```bash
git checkout develop && git fetch origin && git pull
```

Confira que o working tree está limpo antes de começar (`git status --short`).
Arquivos de verificação e saídas de render não podem vazar para o commit, e
`projects/`, `output/`, `cache/`, `bin/` e `assets/voices/` nunca entram:
`git add` com caminhos explícitos, **nunca `-A`**.

Se dois cards da fila tocam o mesmo arquivo, faça um de cada vez até o push. Dois
ajustes meio-feitos no mesmo arquivo é como se perde qual mudança causou o quê.

### 3.2. Corrigir a causa

- Conserte a causa, não o sintoma. Se o ajuste revela que o mesmo erro afeta
  outros pontos, conserte todos: deixar a armadilha montada gera a rodada
  seguinte.
- **Prenda a regressão com teste** quando o que quebrou some sem deixar rastro:
  contrato entre arquivos distantes, qualidade que só se mede
  (`_comum/qualidade.md` → "Testes: prenda o que some sem deixar rastro"). Num
  defeito que só apareceu na integração isso vale dobrado: se dois cards se
  atropelaram uma vez, vão se atropelar de novo.
- Os padrões do `CLAUDE.md` valem como em qualquer card (injeção por protocolo,
  função pura, teste junto, `MEZZ_VERSION` se a receita do mezanino mudar, sem
  travessão em texto de tela).
- **CHANGELOG: não crie linha de `Fixed`.** O card ainda não foi lançado:
  registrar a correção contaria ao usuário final um bug que ele nunca viu. Mas
  **se o conserto mudou o que a entrada original promete, ajuste a entrada
  original** para descrever o comportamento final.

### 3.3. Portões verdes ANTES do push: inegociável

Não há PR nem CI. O que você não rodar aqui, o Douglas descobre com a `develop`
quebrada. Rode os três, sempre (`_comum/qualidade.md`), em primeiro plano e com
`timeout: 600000`:

```powershell
.venv\Scripts\ruff check src tests
.venv\Scripts\ruff format --check src tests
.venv\Scripts\python -m pytest -q
```

Quando a mudança é visível ou audível, some a verificação real do card (render
com `dmaker render <projeto> --preview` e `dmaker qa`, interface pelo
`preview_start` `dmaker-ui-8769`, ou transcrição e medição para voz e áudio).

**Se mexeu em `domain/spec.py`**, confira também que um projeto antigo ainda
valida (`dmaker validate` num spec de exemplo de `templates/`) e que o schema
exposto pelo MCP continua coerente (`tests/test_mcp.py` cobre; não o pule).

### 3.4. Commit, push, card

1. Commit na convenção do repositório (`_comum/git.md`):
   `fix(DMK-XXX): resumo no imperativo, sem acento, até 72 colunas`, corpo
   explicando **por que**, terminando com o `Co-Authored-By:`.
2. `git push origin develop`. Depois confira que ficou sincronizado:
   `git status -sb` sem "ahead" e `git log origin/develop -1 --oneline` com o seu
   commit.
3. **Mova o card para `Teste Manual`** (transição `51`; as transições do DMK são
   globais, uma só chamada, e a `41` antes ao começar a correção, ver
   `_comum/jira.md`). O Douglas testa de novo na `develop` e, ao aprovar, move
   para `Concluído`. Como o PR original já foi mergeado, o `dmaker-merge-develop`
   não vai tentar mergear de novo: ele só pega cards em `Concluído` cujo PR ainda
   está aberto.

   Se a transição falhar, chame `getTransitionsForJiraIssue` e escolha pelo
   **nome do destino** em vez de insistir num id. Se nenhuma rota chegar em
   `Teste Manual`, pare e pergunte: não deixe o card num status errado.
4. Poste o comentário de entrega: o texto vem pronto no briefing (passo 4).

## 4. O comentário é metade do trabalho, e é você quem escreve

O texto sai do seu diagnóstico e vai **pronto** no briefing, para o executor
postar sem reescrever: um comentário redigido por quem só aplicou o patch vira
"corrigido o problema relatado", que é exatamente o que não serve. Os números da
validação técnica só existem depois do retorno: deixe o marcador e complete
antes de mandar postar, ou peça a ele que preencha só essa linha.

Estrutura, nesta ordem: **o que estava errado de fato** → **por que a tentativa
anterior não pegou** → o que mudou agora → **como testar, com o caso que costuma
quebrar** → validação técnica com números.

Cabeçalho: `🔁 _Redesenvolvimento na develop: pronto para novo teste_`, e como
não há PR, o rastro é o commit:

```markdown
🔁 _Redesenvolvimento na develop: pronto para novo teste_

_Commit:_ <sha> (direto na `develop`)
```

No "Como testar", lembre que ele precisa estar com a `develop` atualizada
(`git checkout develop && git pull`) e, se a dependência mudou, de
`pip install -e .`; e que, se o card mexeu na receita do mezanino, o cache se
renova sozinho por causa do `MEZZ_VERSION`.

Duas coisas valem mais que o resto: **admitir com todas as letras quando a
tentativa anterior errou** (é o que dá ao Douglas motivo para confiar que desta
vez é diferente) e **dizer o que testar que costuma quebrar**, em vez de "testar
a tela". Se o defeito veio da integração entre cards, diga qual era o outro card:
é a informação que faz ele testar os dois.

Quando ele sugeriu uma solução no comentário e você seguiu, diga que seguiu. Se
não seguiu, diga por quê, em uma frase, sem rodeio.

## 5. Relatório

Em PT-BR:

- **O que voltou para `Teste Manual`:** card + sha + uma linha do que era o
  defeito de verdade (não o sintoma que ele descreveu).
- **Estado dos portões** ao final da leva e se a `develop` local e a remota estão
  iguais.
- **O que ficou de fora e por quê**, separando "precisa de decisão sua" de
  "estava em `Redesenvolvimento` mas ainda não está na `develop`, então é da outra
  skill" (cite esses com o PR aberto de cada um).
- Se algum card exigir decisão do Douglas para avançar, registre a pergunta no
  card, siga o resto da fila e junte as perguntas no fim.
