---
name: dmaker-rodada
description: Desenvolve de ponta a ponta todos os chamados de uma versão do Jira do DMaker (projeto DMK) que ainda não começaram (colunas Backlog e Aguardando Atendimento), na ordem de prioridade, deixando cada um em Teste Manual com PR aberto para a develop e portões locais verdes. Use sempre que o Douglas pedir para tocar a rodada do DMaker, "toca a rodada", "toca a versão", "pegar os chamados que faltam", "desenvolver o que está pendente", "começar os cards da versão" ou qualquer variação de "toca o que sobrou no Jira do DMaker", mesmo que ele não diga a palavra "skill" nem cite números de card. É o ponto de entrada padrão para trabalho NOVO vindo do Jira; para o que voltou reprovado, use dmaker-redesenvolvimento; para pedido avulso sem chamado, dmaker-dev.
---

# Rodada de desenvolvimento: DMaker

Puxa do Jira tudo que ainda não começou numa versão e entrega card por card, cada
um com seu PR e seu comentário, até a fila zerar.

Leia junto:

- `.claude/skills/_comum/delegacao.md`: **como dividir o trabalho com os subagentes**
- `.claude/skills/_comum/jira.md`: colunas, transições, consultas, comentário de entrega
- `.claude/skills/_comum/git.md`: branch, commit, PR, quando (não) empilhar
- `.claude/skills/_comum/qualidade.md`: portões locais (sem CI), verificação, CHANGELOG

As três últimas são as regras que valem em cada card, mas quem as executa é o
subagente, e ele as lê no contexto dele. Você lê o que precisa para **decidir**.
Para planejar cada card, os padrões do `CLAUDE.md` do projeto valem, e a skill
`dmaker-dev` descreve o formato de plano curto que serve de base ao briefing.

## Divisão do trabalho

| Você (Opus) | Subagente Sonnet |
| --- | --- |
| Perguntar a versão, apresentar a fila, relatório final | - |
| Ordenar a fila e decidir o que cada card exige | - |
| Escrever o briefing de cada card | - |
| - | Levantar a fila no Jira (`dmaker-apurador`) |
| - | Implementar o card de ponta a ponta (`dmaker-executor`) |
| Conferir o retorno contra o critério de aceite | - |

## 1. Pergunte a versão

Sempre pergunte, mesmo que uma versão pareça óbvia pelo contexto: quem decide o
que entra na rodada é o Douglas. Uma pergunta curta basta: "qual versão?".

Com a resposta, mande o `dmaker-apurador` levantar a fila. Ele roda a consulta,
lê descrição **e comentários** de cada card, e devolve o que você precisa para
ordenar, sem despejar o JSON no seu contexto. Use os ids de status (nome de status
combinado com `fixVersion` mente calado, ver `_comum/jira.md`):

```
project = DMK AND fixVersion = "<versão>" AND status in (10071, 10072)
  ORDER BY priority DESC, key ASC
```

Peça, por card: chave, título, prioridade, o que a história pede em duas linhas,
**a decisão de produto que estiver nos comentários** (citada), se há print ou
arquivo anexado, e o palpite dele de esforço na escala de `_comum/jira.md`. E peça
o alerta de cards que aparentam tocar o mesmo módulo.

Vazio é ambíguo: pode ser "acabou" ou pode ser JQL errada. Peça a ele que
confirme com a mesma consulta **sem** o filtro de status: se a versão também
vier vazia, o nome está errado; se vier cheia, a rodada realmente acabou e é isso
que você reporta.

Confira também que a `develop` existe (`git ls-remote --heads origin develop`).
Se não existir, pare e avise o Douglas: ela é criada por ele a partir da `main`.

## 2. Mostre a fila e a ordem antes de começar

Liste os cards com título, prioridade e uma linha do que cada um envolve, e diga
em que ordem vai atacar. Não peça autorização card a card depois disso: o "pode
seguir" vale para a fila inteira.

A ordem sai de `_comum/jira.md` → "Ordem de trabalho": **prioridade primeiro; no
empate, do mais fácil ao mais difícil tecnicamente.** Diga a estimativa de
esforço que você usou para desempatar: é o que o Douglas consegue corrigir se
você subestimou algum card.

Duas coisas ajustam essa ordem:

- **Dependência real de código vence a prioridade**, e quando vencer, avise, com
  o motivo. Não invente dependência onde não há: por padrão cada card sai da
  `develop` (ver `_comum/git.md`).
- **Cards que tocam o mesmo módulo**, quando estão na mesma faixa de prioridade,
  ficam adjacentes na fila: o conflito é resolvido com o contexto fresco em vez
  de voltar dias depois.

Use a lista de tarefas (`TaskCreate`) com um item por card: a rodada é longa e o
Douglas acompanha por ali.

## 3. Para cada card: você planeja, o executor entrega

Um card por vez, e um `dmaker-executor` por card. Não acumule etapas de vários
cards para o fim: PR aberto e card movido antes de começar o próximo.

**Antes de despachar**, faça a parte que é sua:

1. **Entenda o chamado.** Você já tem o resumo do apurador; se a decisão de
   produto ficou ambígua ou há print que muda o desenho, abra o card ou o print
   você mesmo (`_comum/jira.md`): é barato e é justamente o que evita retrabalho.
2. **Decida a estratégia**: qual mecanismo resolve, em qual pacote a mudança cabe
   (`domain/`, `media/`, `text/`, `visuals/`, `filtergraph/`, `pipeline/`, `ui/`),
   o que está fora do escopo, se o card **de fato** depende de outro para rodar
   (`_comum/git.md`: por padrão sai da `develop`), e **qual verificação real** ele
   exige (render, QA, interface, transcrição). Use o formato de plano curto do
   `dmaker-dev` como esqueleto.
3. **Mova para `Em desenvolvimento`** (transição `41`).
4. **Escreva o briefing** no formato de `_comum/delegacao.md`, com as regras do
   `CLAUDE.md` que pesam neste card. O critério de aceite é o comportamento
   observável, não "passar o lint".

**Um executor por vez, sempre**, inclusive quando os cards não se tocam. Dois
executores compartilham o mesmo repositório e trocam de branch um debaixo do
outro; ver `_comum/delegacao.md` → "Nunca dois executores ao mesmo tempo".

O executor faz o resto: implementa, portões verdes (ruff e pytest, sem CI),
verificação de verdade quando a mudança é visível ou audível, CHANGELOG, commit,
push, PR para a `develop` e a transição `51` para `Teste Manual` com o comentário
de entrega.

**Ao receber o relatório**, confira contra o critério de aceite e leia a seção
DESVIOS. Portão vermelho, entrega parcial ou desvio de estratégia: corrija o
briefing e redespache; não termine o card no seu contexto.

**Sem CI, o portão do executor é o único.** Para card de risco (mexe em
`pipeline/`, `filtergraph/`, `spec.py` ou na receita do mezanino), rode você mesmo
um comando de conferência antes de dar por entregue: o `pytest` do arquivo
tocado, ou o render de conferência que o briefing mandou. Um relatório "tudo
verde" que você não cruzou com nada é a fonte da próxima rodada de
redesenvolvimento.

Se um card revelar uma bifurcação que só o Douglas decide (regra de negócio
ambígua, comportamento de voz ou de render que depende de gosto), **registre a
pergunta no card, siga para o próximo** e junte a pergunta no relatório final.
Não pare a rodada inteira esperando resposta: o resto da fila não depende dela.

## 4. Feche com um relatório

Ao final, em PT-BR:

- O que entrou em `Teste Manual`, um card por linha, com o PR.
- O que **não** foi feito e por quê: bloqueio, pergunta em aberto, escopo que
  você decidiu não assumir. Isto é a parte mais importante do relatório: card
  silenciosamente pulado é o que quebra a confiança na rodada.
- Perguntas pendentes, agrupadas, para ele responder de uma vez.
- Se o Douglas for testar agora, ofereça a skill `dmaker-mapa-de-testes`.

Não anuncie "tudo pronto" se algum portão ficou vermelho ou alguma etapa ficou
pela metade. Diga o que ficou e o estado real.
