# Delegação: Opus planeja, Sonnet executa

Referência compartilhada por todas as skills de fluxo do DMaker. É o mesmo fluxo
do MedlyCare, adaptado a este repositório.

O modelo caro (Opus) fica com o que exige julgamento: entender o chamado,
diagnosticar causa, ordenar a fila, decidir estratégia, dar veredito, falar com o
Douglas. Tudo que é volume (abrir arquivo, rodar portão, ler JSON do Jira,
percorrer log do git, aplicar o patch) vai para o Sonnet em subagente, cujo
contexto é descartado no fim.

O ganho não é o preço do token: é o **contexto que não entra**. Um `pytest` de 5
minutos e três módulos abertos consomem mais contexto do que a decisão inteira de
um card. Quem decide precisa do resultado, não do material.

Não confunda com a skill `dmaker-dev`: ela é o mesmo princípio aplicado a pedidos
avulsos, sem Jira. Aqui o trabalho nasce de um chamado do projeto DMK.

## Os dois subagentes

| Agente | Faz | Devolve |
| --- | --- | --- |
| `dmaker-apurador` | Levantamento sem mudar nada: Jira com comentários, mapa de PRs, portões, log do git, CHANGELOG, comandos da CLI | Fatos condensados |
| `dmaker-executor` | Um card: implementa, portões, CHANGELOG, commit, push, PR, transição e comentário | Relatório curto do que fez |

Os dois já vêm fixados em `model: sonnet` na definição: **não passe `model` na
chamada**, senão você sobrescreve isso sem querer.

**Sempre `run_in_background: false`.** O padrão é background e quebra o fluxo das
skills, que dependem do resultado para seguir.

```
Agent(
  subagent_type: "dmaker-executor",
  run_in_background: false,
  description: "DMK-16 dublagem com voz clonada",
  prompt: "<o briefing>"
)
```

Quando as tarefas são independentes, dispare os `Agent` **na mesma mensagem** e
eles rodam em paralelo. Isso vale para o `dmaker-apurador`, que só lê: quatro
auditorias juntas é o uso certo.

## Nunca dois executores ao mesmo tempo

**`dmaker-executor` sempre em série, um por vez**, mesmo quando os cards são
independentes, mesmo quando mexem em arquivos diferentes.

O motivo não é o código: é o git. Todos os subagentes trabalham no mesmo
diretório (`D:\DMaker`), e um repositório tem **um HEAD e um index só**. Dois
executores em paralelo trocam de branch um debaixo do outro, e o commit de um
nasce no branch do outro.

Aconteceu no MedlyCare, em 09/08/2026: dois cards independentes (telas
diferentes, camadas diferentes) foram despachados juntos. O commit de um nasceu no
branch do outro; desfazer isso exigiu `reset`, `stash` por pathspec e `restore` em
cima do trabalho não commitado, com risco real de apagá-lo. Os dois PRs
sobreviveram, mas por pouco, e a limpeza custou mais que a serialização teria
custado.

**Independência de arquivo não é independência de repositório.** A fila em série
é mais lenta e é o preço certo. No DMaker há um agravante: o `cache/` e o
`projects/` são compartilhados no disco, e dois renders ao mesmo tempo disputam
ffmpeg e CPU. Se o paralelismo for mesmo necessário, cada executor precisa de um
worktree isolado, não basta que os cards não se toquem.

## O briefing é o produto do planejamento

O subagente começa **frio**: não viu o Jira, não viu esta conversa, não sabe o que
o Douglas falou. Tudo que ele precisa tem que estar no briefing. Ao mesmo tempo,
briefing gordo desperdiça o que a delegação economiza: o que ele consegue
descobrir sozinho (onde fica o módulo, como o arquivo está estruturado), não
escreva; ele que abra.

Para o `dmaker-executor`, um card:

```
CARD: DMK-XXX: <título>
SKILL: <qual das skills está rodando> (leia .claude/skills/_comum/<as que valem>)
LEIA ANTES: D:\DMaker\CLAUDE.md (arquitetura em pacotes e padrões obrigatórios)

O CHAMADO
<o que o Douglas quer, em prosa, JÁ INTERPRETADO, incluindo a decisão que estava
enterrada no comentário do card. Não mande ele "ler o Jira".>

COMO RESOLVER
<a estratégia decidida: o mecanismo, não o passo a passo do teclado. Num
redesenvolvimento, a CAUSA diagnosticada e por que a tentativa anterior errou.>

ONDE
<pacotes/arquivos prováveis, se você já souber; "descubra" se não souber>

REGRAS DO CLAUDE.md QUE PESAM NESTE CARD
<só as que se aplicam: SOLID e injeção por protocolo (FFmpegRunner, Transcriber,
Prober); função pura sem tocar disco; teste unitário junto, com fakes, e ffmpeg real
só em test_render_integration.py; MEZZ_VERSION em pipeline/segments.py se a receita
do mezanino mudar; sem travessão em texto de tela; docstring de uma frase com o
porquê; mensagens em PT-BR, identificadores em inglês>

NÃO FAÇA
<o que está fora do escopo, e a armadilha específica deste card>

CRITÉRIO DE ACEITE
<como se sabe que ficou pronto: o comportamento observável, não "passar o lint">

ENTREGA
- Branch: <novo a partir da develop | o branch existente <nome> | direto na develop>
- CHANGELOG: <seção e texto da linha | não entra, motivo>
- Portões: ruff check, ruff format --check, pytest (sempre os três; sem CI, são o
  último portão)
- Verificação real: <render/QA/interface/transcrição que precisa rodar, e o que medir>
- PR: <abrir com base <x> | já existe, só empurrar o commit>
- Jira: <transições na ordem> + poste este comentário VERBATIM:
  ---
  <texto pronto>
  ---
```

O comentário do Jira vai **pronto** quando ele carrega diagnóstico: é texto que
depende do julgamento de quem planejou, e reescrito pelo executor vira "corrigido
o problema". Quando é entrega de card novo e direta, mande a anatomia
(`_comum/jira.md`) e deixe ele escrever.

Para o `dmaker-apurador`, itens **numerados**, com o formato de resposta
pedido. Diga o que você vai fazer com a informação: é o que faz ele trazer a
frase certa em vez de um resumo educado.

## O retorno volta para o planejador

Delegar não é terceirizar a responsabilidade. Ao receber o relatório:

1. **Cruze com o critério de aceite.** Bateu ou não bateu.
2. **Leia a seção DESVIOS.** É onde aparece o card resolvido pela metade, e o
   caso, mais raro e mais útil, em que o executor achou algo que o plano não viu.
3. **Portão vermelho ou "parcial" não vira "entregue"** no relatório ao Douglas.
4. Quando o desvio for de estratégia, corrija o briefing e **redespache**: não
   assuma o trabalho no seu próprio contexto, é o que anula a economia.

Não relate ao Douglas o que o subagente disse: relate o que você conferiu. Se
uma afirmação do relatório for surpreendente e cara de errar, confira você
mesmo o ponto exato (um comando, não uma releitura de tudo). Como não há CI,
vale rodar você mesmo o `pytest` ou o render de conferência quando o card é
arriscado: ele é o único portão.

## O que nunca se delega

- **Falar com o Douglas.** Perguntar a versão, apresentar a fila, dar o veredito
  da auditoria, escrever o relatório final.
- **Diagnóstico de causa** num redesenvolvimento. Ele existe porque a leitura
  anterior do problema estava errada; delegar diagnóstico é repetir a hipótese.
- **A ordem da fila** e a decisão de empilhar ou não branch.
- **O merge na `main` e a tag do release.** É a publicação da versão, depende de
  autorização explícita nesta conversa. Este comando é do planejador, sempre.
- **Decidir contornar uma verificação que reprovou.**

## Economia que vale independente de quem executa

- Jira sempre com `fields` limitado ao que vai usar.
- `--limit` no `gh`, `--oneline` no `git log`, `| Select-Object -First N` quando
  a saída puder ser longa.
- Não releia arquivo já lido nesta sessão; não confira com `Read` uma edição que
  o `Edit` já confirmou.
- Um card por subagente. Fila inteira num subagente só devolve um relatório
  grande demais para ser conferido, e perde o isolamento que é o ponto.
