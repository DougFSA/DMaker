---
name: dmaker-redesenvolvimento
description: Resolve os chamados do DMaker que o Douglas reprovou testando a develop e devolveu para a coluna Redesenvolvimento do Jira (projeto DMK). Corrige sempre a partir da develop, por um branch fix/dmk-XXX-ajuste-N com PR mergeado na hora, e devolve cada card para Teste Manual, na ordem de prioridade. Use quando ele falar em redesenvolvimento do DMaker, redev, "os que eu voltei", "os que reprovei", "voltei alguns chamados", "achei um erro na develop", "testei na develop e quebrou", "faz os ajustes que pedi" ou qualquer variação de "corrige o que eu apontei no teste manual", mesmo sem citar números de card. Para chamados novos que ainda não começaram, use dmaker-rodada.
---

# Rodada de redesenvolvimento: DMaker

O Douglas testa a `develop` rodando local (`git checkout develop`, `dmaker ui` ou a
CLI). Quando acha um defeito, move o card para **`Redesenvolvimento`** e escreve o
que viu. Esta skill pega esses cards, **corrige a partir da `develop`** e devolve
cada um para **`Teste Manual`**. Quando ele aprovar, move para `Concluído`.

Há um caminho só: todo código do DMaker já chega à `develop` na entrega
(`_comum/git.md`), então todo card reprovado é um card mergeado, e toda correção
percorre o mesmo caminho de uma entrega nova: branch, PR, portões, merge
imediato, card de volta. Não há mais "corrigir no branch do PR aberto" nem
"commit direto na `develop`".

Leia junto:

- `.claude/skills/_comum/delegacao.md`: **como dividir o trabalho com os subagentes**
- `.claude/skills/_comum/jira.md`: colunas, ordem de trabalho, comentário de entrega, **como abrir os prints**
- `.claude/skills/_comum/git.md`: branch de ajuste, merge na entrega, worktrees
- `.claude/skills/_comum/qualidade.md`: portões locais (sem CI), verificação real, testes de regressão

## Divisão do trabalho

O ponto mais importante desta skill: **o diagnóstico é seu, sempre.** O card já
voltou pelo menos uma vez porque a leitura anterior do problema estava errada;
delegar a leitura é o caminho mais curto para uma terceira rodada.

| Você (Opus) | Subagente Sonnet |
| --- | --- |
| Fila, ordem, apresentação ao Douglas, relatório | - |
| **Diagnosticar a causa**, inclusive olhar o merge que comeu trabalho | - |
| Escrever o comentário de entrega (o texto, não a postagem) | - |
| - | Levantar cards, comentários, entrega anterior, `git log` (`dmaker-apurador`) |
| - | Reproduzir/medir quando você pedir: render, QA, transcrição (`dmaker-apurador`) |
| - | Correção, teste de regressão, portões, PR, merge, Jira (`dmaker-executor`) |

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
2. **O que o Douglas apontou**, citado do **comentário mais recente dele**: a
   frase, não um resumo. A descrição do card diz o que a funcionalidade era; o
   comentário diz o que quebrou, e só a segunda coisa importa agora.
3. Se há print, vídeo ou arquivo anexado (e a data, para casar com o comentário).
4. **O que a entrega anterior afirmou ter resolvido**, citado do comentário de
   entrega anterior. É o que aponta para a hipótese errada.
5. O PR e o commit de merge do card na `develop` (o card tem de estar lá;
   `git log --oneline origin/develop | grep -i DMK-XXX`, **sem diferenciar
   maiúsculas**: há commits com a chave em minúsculas).
6. Quais commits tocaram os arquivos suspeitos **depois** do merge do card (ver
   "defeito de integração", abaixo).

Card em `Redesenvolvimento` **sem** commit na `develop` é anomalia (entrega que
nunca mergeou, ou PR antigo ainda aberto de antes desta mudança de fluxo): não
corrija por conta própria; cite-o no relatório. Se houver PR antigo aberto, o
caminho é a skill `dmaker-merge-develop` (exceção), com o Douglas.

Peça também a consulta do que está em redesenvolvimento **fora** dessa versão
(`_comum/jira.md`): você **cita esses cards no relatório final**, sem tocar neles.
Um card reprovado que não aparece em lugar nenhum é assim que se perde por meses.

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

Esta é a etapa que decide se vai haver uma quarta rodada. Ela é **sua**, não do
subagente. Antes de escrever qualquer linha:

- **Abra o print você mesmo.** O comentário quase sempre traz um; o texto sozinho
  engana, e um print descrito de segunda mão engana mais ainda. `_comum/jira.md`
  explica como ver (Chrome logado do Douglas → issue → anexo). Quando o defeito é
  de som ou de ritmo, o texto do comentário é tudo que existe: releia com atenção
  e, se faltar o trecho, pergunte o instante exato (ex.: "aos 00:12 do render").
- **Releia a entrega anterior**: o apurador já trouxe a citação. O que foi
  afirmado como resolvido, e que evidentemente não resolveu, aponta para a
  hipótese errada.
- **Reproduza ou meça** antes de corrigir, **na `develop`**, que é onde ele viu o
  defeito. Um render pequeno de reprodução, o `dmaker qa`, uma transcrição com o
  `WhisperTranscriber` ou a leitura de RMS e duração transformam palpite em
  número (`_comum/qualidade.md`), e são a diferença entre "acho que é o resample"
  e "o trecho sai com 44,1 kHz num preset de 48 kHz". Montar a reprodução e colher
  as medidas é trabalho de `dmaker-apurador`: mande a hipótese e as medidas que
  você quer. **A leitura dos números é sua.**

Cuidado com o padrão que já custou rodadas (no MedlyCare, e vale igual aqui):
**corrigir o sintoma que ele descreveu, no lugar onde ele descreveu.** A causa
costuma estar a três camadas de distância: a cor não pintava por causa de uma
regra que sobrescrevia a outra, não no cálculo da cor. No DMaker o análogo é o
trecho que "não mudou" porque o mezanino veio do cache (faltou `MEZZ_VERSION`), ou
o ajuste feito no preset quando o valor vinha da marca. Pergunte-se sempre **por
que a tentativa anterior não pegou isso** antes de dar o problema por entendido.

E olhe se o mesmo defeito não está em irmãos que ele ainda não testou: o mesmo
preparador de trecho, a mesma conta de segurança de zona, o outro preset.

### Um defeito só visto na develop costuma ser de integração

O card passou nos portões sozinho, no PR dele, e só quebrou depois de conviver com
os outros. Então a causa provável **não é o card**: é o encontro dele com outro.

- Dois cards mexeram na mesma etapa do pipeline ou na mesma tela da interface e um
  desfez o do outro.
- Uma resolução de conflito de merge escolheu um lado e comeu o outro
  (`_comum/git.md`: conflito se resolve mantendo os DOIS lados).
- **`MEZZ_VERSION`:** dois cards mudaram a receita do mezanino, o conflito foi
  resolvido ficando com um dos números, e um dos dois deixou de invalidar o cache.
  Ou o contrário: ninguém incrementou, e o Douglas está vendo trecho velho do
  `cache/mez`. Antes de achar que o conserto não pegou, limpe o cache
  (`dmaker clean`, avisando-o se ele tiver render em andamento) e refaça.
- A spec ganhou campo em um card e outro card passou a validar de outro jeito.
- O `CHANGELOG.md` perdeu uma linha na resolução de conflito.

Antes de reescrever a lógica do card, **olhe o merge**: `git log --oneline` no
arquivo suspeito e `git show <merge>` costumam mostrar o trabalho que sumiu. Se foi
isso, a correção é restaurar o lado comido, não reimplementar o card. Peça o
levantamento ao apurador (quais commits tocaram o arquivo desde o merge do card, e
o que a resolução de conflito descartou), mas **a conclusão é sua**.

## 3. Para cada card, o ciclo

Com a causa diagnosticada, você move o card e despacha um `dmaker-executor`.

1. **Mova o card para `Em desenvolvimento`** (transição `41`; as transições do DMK
   são globais, uma chamada basta, ver `_comum/jira.md`).
2. **Escreva o briefing** (`_comum/delegacao.md`). Num redesenvolvimento ele tem
   campos que não existem na rodada normal:
   - **A causa**, dita como mecanismo: "o mezanino vem do cache porque a receita
     mudou sem incrementar `MEZZ_VERSION`", não "o trecho não muda".
   - **Por que a tentativa anterior não pegou**, porque é o que impede o executor
     de reencontrar sozinho o mesmo caminho errado.
   - **O caminho de entrega**: branch **novo** `fix/dmk-XXX-ajuste-N` saindo da
     `develop` atualizada (N é a rodada), PR para a `develop`, portões, merge
     imediato (`_comum/git.md`) e card de volta com `51`. O branch original do
     card já foi mergeado e apagado; não o reaproveite.
   - Se o mesmo defeito afeta irmãos, consertar todos; prender a regressão com
     teste quando o que quebrou some sem deixar rastro, vale dobrado num defeito
     de integração (`_comum/qualidade.md`).
   - **CHANGELOG: não crie linha de `Fixed`.** O card ainda não foi lançado:
     registrar a correção contaria ao usuário final um bug que ele nunca viu. Mas
     **se o conserto mudou o que a entrada original promete, ajuste a entrada
     original** para descrever o comportamento final.
   - O comentário de entrega **verbatim** que você escreveu no passo 4.
3. **Cards independentes podem ir em paralelo**, cada um num worktree, como na
   rodada (`_comum/delegacao.md`); o merge de cada um é serializado. Defeitos
   que mexem no mesmo arquivo vão em série: dois ajustes meio-feitos no mesmo
   arquivo é como se perde qual mudança causou o quê.
4. **Confira o retorno** contra o critério de aceite e a seção DESVIOS. Se o
   executor consertou o sintoma em vez da causa, é aqui que se pega. Como não há
   CI e o commit já está na `develop`, rode você mesmo, na `develop` atualizada, a
   conferência que prova a causa corrigida (o render de reprodução de novo, o
   mesmo comando do apurador). Portão vermelho ou ponta da `develop` quebrada
   **não é "entregue"**: redespache o conserto antes de pegar o próximo card.

Se uma correção reprovar na ponta da `develop` por causa de **outro** card (não o
que você está corrigindo), o card dele é o que volta: registre e reporte, sem
mascarar.

## 4. O comentário é metade do trabalho, e é você quem escreve

Num redesenvolvimento o comentário tem uma exigência a mais que na rodada normal:
**dizer com todas as letras por que a tentativa anterior errou.** Não é
autoflagelação: é o que dá ao Douglas motivo para confiar que desta vez é
diferente, e é o que impede a hipótese de se repetir.

Por isso o texto sai do seu diagnóstico e vai **pronto** no briefing, para o
executor postar sem reescrever. Um comentário redigido por quem só aplicou o patch
vira "corrigido o problema relatado", que é exatamente o que não serve.

Cabeçalho: `🔁 _Redesenvolvimento: corrigido na develop, pronto para novo teste_`,
com o `_PR:_` (mergeado) e o `_Commit na develop:_` logo abaixo (a anatomia está
em `_comum/jira.md`). Estrutura, na ordem: o que estava errado de fato → por que a
tentativa anterior não pegou → o que mudou agora → **como testar, com o caso que
costuma quebrar** → validação técnica com números. Se o defeito veio da integração
entre cards, diga qual era o outro card: é a informação que faz ele testar os
dois.

No "Como testar", lembre que ele precisa estar com a `develop` atualizada
(`git checkout develop && git pull`) e, se a dependência mudou, de
`pip install -e .`; e que, se o card mexeu na receita do mezanino, o cache se
renova sozinho por causa do `MEZZ_VERSION`.

Os números da validação você só tem depois do retorno do executor, e o PR e o
commit de merge só existem depois do merge: deixe os marcadores no texto e
complete antes de mandar postar, ou peça a ele que preencha só essas linhas.

Quando o Douglas sugeriu uma solução no comentário e você seguiu, diga que
seguiu. Se não seguiu, diga por quê, em uma frase, sem rodeio.

## 5. Feche com o relatório

Em PT-BR: o que voltou para `Teste Manual` (card + PR + commit de merge + resumo
de uma linha do **defeito de verdade**, não do sintoma), o estado dos portões na
ponta da `develop` ao final, o que continua travado e por quê.

Inclua os cards em redesenvolvimento **de outras versões** que você deixou de
fora, com a versão de cada um, e os que estão em `Redesenvolvimento` sem commit na
`develop` (anomalia, acima). São linhas curtas, e é o que impede um chamado
reprovado de ficar esquecido.

Se algum card exigir decisão do Douglas para avançar, registre a pergunta no card,
siga o resto da fila e junte as perguntas no fim.
