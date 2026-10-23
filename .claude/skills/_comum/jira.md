# Jira: DMaker (projeto DMK)

Referência compartilhada pelas skills do DMaker e pelos subagentes
`dmaker-executor` e `dmaker-apurador`.

- **cloudId:** `d6777a03-0582-42ef-a9ed-5f1afd26ee2b`
- **Site:** https://nativalabs.atlassian.net · **Projeto:** `DMK` · **Board:** 34
- **Ferramentas:** MCP Atlassian (`searchJiraIssuesUsingJql`, `getJiraIssue`,
  `getTransitionsForJiraIssue`, `transitionJiraIssue`, `addCommentToJiraIssue`,
  `createJiraIssue`). Carregue-as com `ToolSearch` (`select:...`) antes de usar.

## Tipos de chamado e como se escreve um

Tipos: Épico, História (equivale ao Feature de outros projetos), Melhoria, Bug,
Tarefa e Subtarefa. Os filhos ligam ao épico pelo campo `parent`.

**Título: `Área: o que muda em linguagem de usuário`.** Exemplos de área: `Voz:`,
`Dublagem:`, `Interface:`, `Render:`, `Áudio:`. Quem lê o título é o Douglas
testando, não um desenvolvedor: "Dublagem: a voz clonada mantém o ritmo da fala
original" vale mais que "Refatora o alinhador de cues".

**Rótulos por área:** `voz`, `dublagem`, `interface`, `audio`, `render`, `testes`,
`desempenho`. Um por área tocada.

## Colunas do quadro

| Status | id do status | id da transição | O que significa |
| --- | --- | --- | --- |
| `Backlog` | 10071 | 11 | Ainda não começou. |
| `Aguardando Atendimento` | 10072 | 21 | Priorizado, esperando alguém pegar. |
| `Redesenvolvimento` | 10073 | 31 | Ele testou e reprovou. É daqui que o **redesenvolvimento** puxa trabalho. |
| `Em desenvolvimento` | 10074 | 41 | Alguém está desenvolvendo agora. |
| `Teste Manual` | 10075 | 51 | Entregue, esperando o Douglas testar. **É onde cada card termina.** |
| `Concluído` | 10076 | 61 | Ele testou e aprovou. |

**Todas as transições do DMK são globais:** de qualquer status se vai para
qualquer outro com o id da transição de destino. Não há caminho obrigatório, então
um card em `Redesenvolvimento` volta direto para `Teste Manual` com a `51`, em uma
chamada. Mesmo assim, se uma transição falhar, chame `getTransitionsForJiraIssue`
e escolha pelo **nome do destino**: id chutado move o card para o lugar errado sem
erro nenhum.

### `Concluído` agrupa dois estados

Não existe uma coluna "aprovado, aguardando merge". O Douglas move de
`Teste Manual` para `Concluído` quando **aprova**, e é isso que libera o merge na
`develop`. Depois do merge o card continua em `Concluído`. Logo, `Concluído`
significa duas coisas:

1. **Aprovado, PR ainda aberto:** falta mergear na `develop`.
2. **Já na `develop` (ou já lançado na `main`):** nada a fazer.

**O que distingue os dois é o estado do PR**, não o Jira:

```bash
gh pr list --state open --search "DMK-XXX" --json number,headRefName,baseRefName
```

PR aberto = estado 1. Sem PR aberto, confirme com
`git log --oneline origin/develop | grep -i DMK-XXX` (case-insensitive: há commits
com a chave em minúsculas) e tire o card da fila de merge. Ao mergear, deixe o
rastro no card (`🔀 Mergeado na develop: <sha> (PR #N)`), porque é ele que a
auditoria de produção usa para cruzar "aprovado" com "realmente na develop".

## Transições por momento do trabalho

- **Começar o card:** `41` (Em desenvolvimento), a partir de `Backlog`,
  `Aguardando Atendimento` ou `Redesenvolvimento`.
- **Entregar:** `51` (Teste Manual), com o PR aberto para a `develop`, portões
  verdes e o comentário de entrega postado.
- **Reprovado:** o Douglas move para `Redesenvolvimento` (`31`). Quem corrige
  devolve com `51`, passando antes pelo `41` ao começar a correção.
- **Aprovado:** o Douglas move para `Concluído` (`61`). Nenhuma skill faz isso por
  ele.

Mova o card **quando o trabalho realmente muda de estado**: `41` ao começar
aquele card, `51` quando o PR estiver no ar e os portões verdes. Mover tudo em
lote no fim apaga a informação que o quadro existe para dar.

## Consultas úteis

As skills perguntam a versão ao Douglas e filtram por ela. Ordene sempre por
prioridade: ver "Ordem de trabalho" abaixo.

```
# A fila da rodada: o que falta desenvolver numa versão
# (10071 = Backlog, 10072 = Aguardando Atendimento)
project = DMK AND fixVersion = "<v>" AND status in (10071, 10072)
  ORDER BY priority DESC, key ASC

# O que voltou para redesenvolvimento numa versão   (10073 = Redesenvolvimento)
project = DMK AND fixVersion = "<v>" AND status = 10073
  ORDER BY priority DESC, updated DESC

# Redesenvolvimento FORA da versão escolhida: só para reportar, não para fazer
project = DMK AND status = 10073 AND (fixVersion != "<v>" OR fixVersion IS EMPTY)

# Aprovados (10076 = Concluído); depois filtre pelo PR ainda aberto
project = DMK AND fixVersion = "<v>" AND status = 10076 ORDER BY key ASC

# Esperando o Douglas testar                        (10075 = Teste Manual)
project = DMK AND fixVersion = "<v>" AND status = 10075 ORDER BY key ASC
```

`fixVersion` usa o **nome** da versão entre aspas (`"1"`), não o id. Sem aspas o
Jira interpreta como id e devolve vazio sem reclamar. O nome da versão é o que
vira a tag do release (`v` + nome). Um resultado vazio é ambíguo, então confirme
com uma consulta sem o filtro de status antes de anunciar "não há nada a fazer".

**`status` combinado com `fixVersion` precisa do id, não do nome.** Aconteceu no
MedlyCare, em 09/08/2026: `fixVersion = "6" AND status = "Tarefas pendentes"`
devolveu vazio duas vezes seguidas, com a versão cheia de cards nesse exato
status; trocando pelo id os 13 cards apareceram. O nome do status funciona
sozinho, mas combinado com `fixVersion` mente calado. **Use os ids** (10071 a
10076, a tabela acima) nas consultas das skills. Um "a rodada acabou" tirado da
consulta por nome é um falso negativo.

## Ordem de trabalho

A fila é atacada **por prioridade, da maior para a menor**. `ORDER BY priority DESC`
já devolve nessa ordem (o esquema padrão do Jira: Highest, High, Medium, Low,
Lowest).

**Empate de prioridade se desempata pelo esforço técnico: do mais fácil para o
mais difícil.** O ganho é de fluxo: os fáceis chegam cedo em teste manual e o
Douglas já vai validando enquanto os difíceis ainda andam, em vez de a fila
inteira ficar represada atrás de um card grande.

Para estimar o esforço, do mais leve ao mais pesado:

1. Só texto, interface estática ou um comando da CLI, sem mexer em render.
2. Lógica pura (`domain/`, `filtergraph/`, `text/`) ou serviço do `pipeline/`,
   com teste unitário e sem mudar a receita do mezanino.
3. Mudança que **invalida cache ou altera a spec**: `MEZZ_VERSION`, campo novo na
   spec com compatibilidade, mudança no grafo ffmpeg que exige render real para
   conferir.
4. Território novo: modelo ou biblioteca nova (voz, separação, matting),
   integração com Ollama/Whisper/Demucs, dependência com instalação pesada. O que
   tem incógnita é o que estoura a estimativa.

Um card cujo código você **já entendeu nesta sessão** é mais fácil do que a
estimativa sugere; considere isso no desempate.

**A dependência real de código vence a prioridade**, porque não é preferência: se
o card B não roda sem o A, o A vem antes mesmo sendo menos prioritário. Quando
isso acontecer, diga na hora de apresentar a fila: é a única inversão de
prioridade que o Douglas precisa entender.

**Respostas grandes estouram o limite de tokens.** Peça só os campos que vai usar
(`["summary","status"]`). Quando a resposta for salva em arquivo, leia com
PowerShell + `ConvertFrom-Json` (não existe `jq` nesta máquina).

## Ler o chamado inteiro antes de codar

Título e descrição raramente bastam. **Os comentários costumam carregar a
decisão que muda o desenho da solução**: uma escolha de produto, um print com o
sintoma, um "não faz assim". Puxe-os com `fields: ["summary","description","comment"]`
e leia os últimos primeiro.

Nos redesenvolvimentos isso é obrigatório: o comentário mais recente **é** o
chamado.

### Ver os prints

Os prints ficam como anexo e o texto do comentário traz só um blob inútil. Para
ver de verdade:

1. `getJiraIssue` com `fields: ["attachment"]` → pegue o anexo mais recente
   (compare `created` com a data do comentário).
2. Abra `https://nativalabs.atlassian.net/browse/DMK-XXX` no **Chrome do usuário**
   (`mcp__claude-in-chrome__*`, que tem a sessão logada) e clique na miniatura em
   "Anexos" para abrir o visualizador em tamanho cheio.
3. `computer{action:"zoom"}` na região de interesse quando o detalhe for pequeno.

Baixar o anexo pela API não funciona sem token, e o navegador embutido
(`mcp__Claude_Browser__*`) não tem a sessão do Jira. Vale também para vídeo de
tela e áudio anexados: o que não der para abrir, peça o trecho em texto ao Douglas
em vez de adivinhar.

## Comentário de entrega

Um comentário por entrega, no card, sempre com a mesma anatomia. Ele é lido por
uma pessoa que vai **testar**, não revisar código: o que ela precisa é saber o
que mudou, por que, e o que exatamente olhar ou ouvir.

```markdown
✅ _Entregue: pronto para teste_        ← ou: 🔁 _Redesenvolvimento: pronto para novo teste_

_PR:_ <url>

<O que foi feito e POR QUE foi feito assim. Nas decisões que tiveram alternativa,
diga qual você descartou e o motivo: é o que evita a mesma discussão no próximo
card. Num redesenvolvimento, comece pelo que estava errado e por que a tentativa
anterior não pegou.>

_Como testar:_ <o caminho na interface ou o comando da CLI, com o projeto ou o
arquivo de exemplo (em output/, quando houver) e os casos de borda que
provavelmente quebram. Inclua o caso "não mexeu no que já estava certo" quando o
ajuste tocou código compartilhado. Se precisar de `git checkout <branch>` ou de
`pip install -e .` (dependência nova), diga.>

_Validação técnica_

* <portões: ruff check · ruff format --check · pytest N passados>
* <o que foi medido ou reproduzido, com número quando houver: QA do render,
  duração, RMS, transcrição conferida>
```

Escreva em PT-BR, em prosa, na voz de quem fez o trabalho, **sem travessão**. Duas
coisas valem mais que o resto: **admitir com todas as letras quando a tentativa
anterior errou** (e por quê), e **dizer o que testar que costuma quebrar** em vez
de só "testar a tela". Um comentário que só diz "corrigido" obriga o Douglas a
descobrir sozinho o que mudou.

Não ponha nome de cliente nem trecho de áudio ou vídeo real no comentário: descreva
o teste pelo que ele exercita (`_comum/git.md` → Higiene).
