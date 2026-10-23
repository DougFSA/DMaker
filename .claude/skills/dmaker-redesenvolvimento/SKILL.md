---
name: dmaker-redesenvolvimento
description: Resolve os chamados de uma versão do DMaker que o Douglas reprovou no teste manual e devolveu para a coluna Redesenvolvimento do Jira (projeto DMK), entregando cada um de volta em Teste Manual com o PR atualizado, na ordem de prioridade. Vale para os cards que ainda NÃO foram mergeados na develop, os que têm PR aberto. Use quando ele falar em redesenvolvimento do DMaker, redev, "os que eu voltei", "os que reprovei", "voltei alguns chamados", "faz os ajustes que pedi" ou qualquer variação de "corrige o que eu apontei no teste manual", mesmo sem citar números de card. Se o card reprovado já foi mergeado na develop (ele testou a develop e achou o erro lá), use dmaker-redesenvolvimento-develop. Para chamados novos que ainda não começaram, use dmaker-rodada.
---

# Rodada de redesenvolvimento: DMaker

Pega o que voltou reprovado numa versão e devolve para teste.

Leia junto:

- `.claude/skills/_comum/delegacao.md`: **como dividir o trabalho com os subagentes**
- `.claude/skills/_comum/jira.md`: colunas, transições, ordem de trabalho, comentário de entrega, **como abrir os prints**
- `.claude/skills/_comum/git.md`: branch existente, cascata, merge
- `.claude/skills/_comum/qualidade.md`: portões locais (sem CI), verificação real, testes de regressão

## Divisão do trabalho

Aqui a linha é diferente da rodada normal, e é o ponto mais importante desta
skill: **o diagnóstico é seu, sempre.** O card já voltou pelo menos uma vez
porque a leitura anterior do problema estava errada: delegar a leitura é o
caminho mais curto para uma terceira rodada.

| Você (Opus) | Subagente Sonnet |
| --- | --- |
| Fila, ordem, apresentação ao Douglas, relatório | - |
| **Diagnosticar a causa** e por que a tentativa anterior errou | - |
| Escrever o comentário de entrega (o texto, não a postagem) | - |
| - | Levantar cards, comentários e a entrega anterior (`dmaker-apurador`) |
| - | Reproduzir/medir quando você pedir: render, QA, transcrição (`dmaker-apurador`) |
| - | Aplicar a correção, teste de regressão, portões, push, cascata, Jira (`dmaker-executor`) |

## 1. Pergunte a versão e levante a fila

Pergunte a versão antes de qualquer coisa, como na rodada: a coluna de
redesenvolvimento acumula cards de versões diferentes, e mexer num card de outra
versão é entregar trabalho que ninguém pediu agora.

```
project = DMK AND fixVersion = "<versão>" AND status = 10073
  ORDER BY priority DESC, updated DESC
```

(`10073` = Redesenvolvimento; use o id, não o nome, quando combinar com
`fixVersion`.) Quem roda isso é o `dmaker-apurador`: o JSON de comentários é o
maior gasto de contexto desta skill e não precisa passar por você. Peça, por
card:

1. Chave, título, prioridade.
2. **O que o Douglas apontou**, citado do comentário mais recente dele: a frase,
   não um resumo.
3. Se há print, vídeo ou arquivo anexado (e a data, para casar com o comentário).
4. **O que a entrega anterior afirmou ter resolvido**, citado do seu comentário
   de entrega anterior. É o que aponta para a hipótese errada.
5. O branch e o PR abertos do card, e se ele é base de outro PR.
6. **Se o PR ainda está aberto.** Card em `Redesenvolvimento` cujo PR já foi
   mergeado na `develop` não é desta skill: é da `dmaker-redesenvolvimento-develop`.

Peça também a consulta do que está em redesenvolvimento **fora** dessa versão
(`_comum/jira.md`): você **cita esses cards no relatório final**, sem tocar
neles. Um card reprovado que não aparece em lugar nenhum é assim que se perde por
meses.

Mostre a fila ao Douglas com uma linha por card dizendo **o que ele apontou**, não
o título do card, e na ordem em que vai atacar: **prioridade primeiro; no empate,
do mais fácil ao mais difícil** (`_comum/jira.md` → "Ordem de trabalho"). Depois
siga sem pedir autorização card a card.

No redesenvolvimento o esforço se estima pelo **ajuste pedido**, não pelo tamanho
do card original: um card grande que voltou por causa de um texto cortado na tela
é fácil, e um card pequeno que voltou porque a regra estava errada é difícil. Só
dá para saber isso depois de ler o comentário e abrir o print: por isso a fila só
é ordenada depois da leitura, não direto do resultado do JQL.

## 2. Entenda o que estava errado antes de mexer

Esta é a etapa que decide se vai haver uma quarta rodada. O card já voltou pelo
menos uma vez, o que significa que **a leitura anterior do problema estava errada**,
não que faltou capricho.

Esta etapa é **sua**, não do subagente. Antes de escrever qualquer linha:

- **Abra o print você mesmo.** O comentário quase sempre traz um; o texto sozinho
  engana, e um print descrito de segunda mão engana mais ainda. `_comum/jira.md`
  explica como ver (Chrome logado do Douglas → issue → anexo). Quando o defeito é
  de som ou de ritmo, o texto do comentário é tudo que existe: releia com atenção
  e, se faltar o trecho, pergunte o instante exato (ex.: "aos 00:12 do render").
- **Releia a entrega anterior**: o apurador já trouxe a citação. O que foi
  afirmado como resolvido, e que evidentemente não resolveu, aponta para a
  hipótese errada.
- **Reproduza ou meça** antes de corrigir. Um render pequeno de reprodução, o
  `dmaker qa`, uma transcrição com o `WhisperTranscriber` ou a leitura de RMS e
  duração transformam palpite em número (`_comum/qualidade.md`), e são a
  diferença entre "acho que é o resample" e "o trecho sai com 44,1 kHz num
  preset de 48 kHz". Montar a reprodução e colher as medidas é trabalho de
  `dmaker-apurador`: mande a hipótese e as medidas que você quer, ele devolve os
  números. **A leitura dos números é sua.**

Cuidado com o padrão que já custou rodadas (no MedlyCare, e vale igual aqui):
**corrigir o sintoma que ele descreveu, no lugar onde ele descreveu.** A causa
costuma estar a três camadas de distância: a cor não pintava por causa de uma
regra que sobrescrevia a outra, não no cálculo da cor. No DMaker o análogo é o
trecho que "não mudou" porque o mezanino veio do cache (faltou `MEZZ_VERSION`), ou
o ajuste feito no preset quando o valor vinha da marca. Pergunte-se sempre **por
que a tentativa anterior não pegou isso** antes de dar o problema por entendido.

E olhe se o mesmo defeito não está em irmãos que ele ainda não testou: o mesmo
preparador de trecho, a mesma conta de segurança de zona, o outro preset.

## 3. Para cada card, o ciclo

Com a causa diagnosticada, você move o card e despacha um `dmaker-executor`.

1. **Mova o card para `Em desenvolvimento`** (transição `41`; as transições do DMK
   são globais, uma chamada basta, ver `_comum/jira.md`).
2. **Escreva o briefing** (`_comum/delegacao.md`). Num redesenvolvimento ele tem
   dois campos que não existem na rodada normal:
   - **A causa**, dita como mecanismo: "o mezanino vem do cache porque a receita
     mudou sem incrementar `MEZZ_VERSION`", não "o trecho não muda".
   - **Por que a tentativa anterior não pegou**, porque é o que impede o executor
     de reencontrar sozinho o mesmo caminho errado.

   E manda junto: trabalhar **no branch que já existe** do card (não criar branch
   novo: o PR já está aberto e recebe o commit novo); se o mesmo defeito afeta
   irmãos, consertar todos; prender a regressão com teste quando o que quebrou
   some sem deixar rastro (`_comum/qualidade.md`); portões verdes; transição `51`
   e o comentário de entrega **verbatim** que você escreveu no passo 4.
3. **Se o branch é base de outros**, a cascata **não** vai no mesmo briefing.
   Ela é decisão sua (`_comum/git.md`): calcule os forks antes, defina a ordem, e
   só então mande o executor rebasear com a tabela pronta, conferir que nenhum
   card sumiu e rodar os portões no topo da pilha.
4. **Confira o retorno** contra o critério de aceite e a seção DESVIOS. Se o
   executor consertou o sintoma em vez da causa, é aqui que se pega. Como não há
   CI, vale rodar você mesmo a conferência que prova a causa corrigida (o render
   de reprodução de novo, o mesmo comando do apurador).

## 4. O comentário é metade do trabalho, e é você quem escreve

Num redesenvolvimento o comentário tem uma exigência a mais que na rodada normal:
**dizer com todas as letras por que a tentativa anterior errou.** Não é
autoflagelação: é o que dá ao Douglas motivo para confiar que desta vez é
diferente, e é o que impede a hipótese de se repetir.

Por isso o texto sai do seu diagnóstico e vai **pronto** no briefing, para o
executor postar sem reescrever. Um comentário redigido por quem só aplicou o
patch vira "corrigido o problema relatado", que é exatamente o que não serve.

Cabeçalho: `🔁 _Redesenvolvimento: pronto para novo teste_`, com o `_PR:_` logo
abaixo (a anatomia está em `_comum/jira.md`). Estrutura, na ordem: o que estava
errado de fato → por que a tentativa anterior não pegou → o que mudou agora →
**como testar, com o caso que costuma quebrar** → validação técnica com números.
Os números da validação você só tem depois do retorno do executor: deixe o
marcador no texto e complete antes de mandar postar, ou peça a ele que preencha só
essa linha.

Quando o Douglas sugeriu uma solução no comentário e você seguiu, diga que
seguiu. Se não seguiu, diga por quê, em uma frase, sem rodeio.

## 5. Feche com o relatório

Em PT-BR: o que voltou para `Teste Manual` (card + PR + resumo de uma linha do que
era), o que continua travado e por quê, e, se a pilha ficou destravada por essas
correções, quais cards aprovados agora podem ser mergeados.

Inclua os cards em redesenvolvimento **de outras versões** que você deixou de
fora, com a versão de cada um. É uma linha, e é o que impede um chamado reprovado
de ficar esquecido numa versão que ninguém está tocando. E inclua, separados, os
que estão em `Redesenvolvimento` mas já foram mergeados na `develop` (são da
`dmaker-redesenvolvimento-develop`).

Se algum card exigir decisão do Douglas para avançar, registre a pergunta no card,
siga o resto da fila e junte as perguntas no fim.
