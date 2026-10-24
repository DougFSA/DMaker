---
name: dmaker-producao
description: Lança uma versão do DMaker, audita se todos os chamados da versão estão em Concluído no Jira (projeto DMK), testados e aprovados pelo Douglas na develop, sem nada em Redesenvolvimento ou Teste Manual e sem pendência na máquina, fecha a versão no CHANGELOG, faz o release da develop para a main e cria a tag vX. Não há deploy em nuvem: o DMaker roda na máquina do Douglas. Use sempre que ele falar em lançar o DMaker, "sobe para produção", "põe em produção", "fazer o release", "sobe a v1", "manda pra main", "fecha a versão", "publicar a versão" ou qualquer variação de liberar a versão. Os chamados já entram na develop na entrega (o executor mergeia o PR); esta skill só leva a develop inteira para a main.
---

# Release da versão: DMaker

Lança uma versão do DMaker: fecha o CHANGELOG, leva a `develop` para a `main` e
marca a tag `vX`. **Não existe deploy.** O DMaker roda na máquina do Douglas (não
há servidor, nuvem nem pipeline), então "produção" aqui é a `main` com a tag, mais
o pacote reinstalado no `.venv` a partir dela. Mesmo assim a auditoria antes do
merge não é burocracia: depois do release, a `main` é o que ele considera estável
e o que a skill de catálogo trata como "o que o sistema faz hoje".

Leia junto:

- `.claude/skills/_comum/delegacao.md`: **como dividir o trabalho com os subagentes**
- `.claude/skills/_comum/jira.md`: colunas e consultas
- `.claude/skills/_comum/qualidade.md`: portões (sem CI) e CHANGELOG
- `.claude/skills/_comum/git.md`: convenções

## Divisão do trabalho

As quatro auditorias são **coleta de fatos**: vão inteiras para o
`dmaker-apurador`, e as quatro rodam **em paralelo**, na mesma mensagem. O
veredito sobre os fatos é seu.

Aqui o paralelismo é seguro **porque apurador só lê**: nenhum deles cria branch,
commita ou troca o HEAD. A proibição de paralelizar em `_comum/delegacao.md` vale
para o `dmaker-executor`, não para esta etapa. (A auditoria D pede `checkout` da
`develop` e roda o `pytest`; deixe só uma delas mexer no working tree e avise as
outras para não depender dele.)

| Você (Opus) | Subagente Sonnet |
| --- | --- |
| Perguntar a versão; dar o **veredito** das auditorias; falar com o Douglas | - |
| **Mergear na `main` e criar a tag**: nunca delegado, em hipótese nenhuma | - |
| Ler o retorno do smoke e decidir se a versão está de pé | - |
| - | Coletar as auditorias A, B, C e D (`dmaker-apurador`, em paralelo) |
| - | Fechar o CHANGELOG e abrir o PR de release (`dmaker-executor`) |
| - | Reinstalar o pacote e rodar o smoke, e resumir (`dmaker-apurador`) |

O apurador traz **fatos**, não veredito: "DMK-12 está em Teste Manual" é fato; "o
release está bloqueado" é sua conclusão. Peça sempre a **evidência citada**: é ela
que você vai mostrar ao Douglas.

## Regra que não se flexibiliza

**Nunca mergeie na `main` nem crie a tag sem o Douglas dizer explicitamente que
pode subir**, nesta conversa, depois de ver o resultado da auditoria. "Roda a
skill de produção" é pedido de auditoria e preparação, não é autorização de
release.

Se qualquer item da auditoria reprovar, **pare e reporte**. Não conserte por
conta própria contornando a verificação: o item que falhou costuma ser
exatamente o que quebraria na máquina dele.

## 1. Pergunte a versão

Sem versão não há release. O nome da versão no Jira é o que vira a tag (`v` +
nome). Com ela em mãos, dispare as quatro auditorias abaixo **antes** de tocar em
qualquer branch: as quatro, na mesma mensagem, mesmo que a primeira já reprove,
porque o Douglas precisa da lista completa do que falta para resolver tudo de uma
vez.

Uma chamada de `dmaker-apurador` por auditoria: são independentes, rodam
juntas, e cada relatório volta do tamanho de um parágrafo em vez de despejar
comentário do Jira, diff e log de teste no seu contexto. Em cada briefing,
numere os itens e peça a resposta na mesma numeração.

## 2. Auditoria A: todo card da versão está no lugar certo

```
project = DMK AND fixVersion = "<versão>" ORDER BY status ASC, key ASC
```

Todo card tem que estar em **`Concluído`**, ou seja, testado e aprovado pelo
Douglas **na `develop`**. Como o código entra na `develop` na entrega e o merge não
depende mais da aprovação, o que a auditoria confere é o inverso do fluxo antigo:
que **nada ficou sem passar pelo teste dele**.

- **Nenhum card da versão em `Teste Manual` ou `Redesenvolvimento`.** Esses dois
  status significam "na `develop`, mas ainda não aprovado" e **bloqueiam o
  release**: a `develop` inteira sobe, e subiria código não testado ou reprovado.
  Ou o trabalho termina e o Douglas aprova, ou ele tira o card da versão.
- Qualquer card em `Backlog`, `Aguardando Atendimento` ou `Em desenvolvimento`
  também bloqueia, pelo mesmo motivo. Liste cada um com o status atual e diga qual
  das saídas cabe.
- Para cada card em `Concluído`, confirme que o código **está** na `develop`:
  `git log --oneline origin/develop | grep -i DMK-XXX`, e que o comentário de
  entrega traz o commit de merge. Card em `Concluído` sem commit na `develop` é
  anomalia (aprovado, mas o merge nunca aconteceu, ou se perdeu): bloqueia.
- **Nenhum PR de card da versão ainda aberto** (`gh pr list --state open --search
  "DMK-XXX"`): PR aberto de card entregue é entrega que não mergeou, ou PR
  antigo do fluxo anterior; neste caso o caminho é a skill `dmaker-merge-develop`
  (exceção), com o Douglas decidindo.

Confira também o contrário: **código na `develop` sem card na versão**:

```bash
git log --oneline origin/main..origin/develop | grep -oE 'DMK-[0-9]+' | sort -u
```

Todo `DMK-xxx` que aparecer aí e **não** estiver na versão vai subir junto de
qualquer forma (o release leva a `develop` inteira). Ou o card entra na versão,
ou o Douglas sabe e aceita, mas ninguém pode descobrir isso depois. Peça também os
commits sem chave de card, que o `grep` não acusa.

## 3. Auditoria B: cada card tem a aprovação do Douglas

No DMK a aprovação **é** a coluna `Concluído`: não existe um comentário de "ok"
separado, e não existe a coluna intermediária "Teste em Develop" do MedlyCare
(`Teste Manual` já é o teste na `develop`). O risco é o cartão arrastado por
engano, ou movido por outra pessoa/automação.

Peça ao apurador, por card, o **histórico de transições** (o changelog do card:
`getJiraIssue` com `expand=changelog`, quando a ferramenta permitir): **quem**
moveu para `Concluído`, **quando**, e se foi **depois** da última entrega do card
(o último comentário `✅ _Entregue` ou `🔁 _Redesenvolvimento`). Uma linha por
card: autor, data e o status de origem.

Quem decide se aquilo é aprovação é você. Card em `Concluído` movido pelo Douglas
depois da última entrega, a partir de `Teste Manual`, é aprovado. Card movido por
outro autor, antes da última entrega, ou sem passar por `Teste Manual`, entra na
lista de bloqueio com a pergunta ao Douglas. Comentário de bot e de entrega da IA
(inclusive o que cita o PR mergeado e o commit na `develop`) não contam como
aprovação. Não
interprete o silêncio como aval: um subagente resumindo "parece aprovado" é
exatamente o modo de esta auditoria falhar.

## 4. Auditoria C: pré-requisitos na máquina

Leia o bloco `### Pré-requisitos na máquina` do `[Não lançado]` em `CHANGELOG.md`
e trate **cada linha** como um item de checagem, não como texto informativo. Para
cada uma, diga se está resolvida, como você confirmou, ou que depende do Douglas.

Some a isso a checagem que independe do CHANGELOG, comparando `main` e `develop`:

- **`pyproject.toml`**: `git diff origin/main..origin/develop -- pyproject.toml`.
  Dependência nova ou extra novo (`voice`, `captions`, `dev`) significa que o
  `.venv` do Douglas precisa de `pip install -e .[voice,captions]`. O `torch`
  entra à parte, versão CPU, pelo índice da PyTorch:
  `pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu`.
- **`dmaker setup`**: algo novo para baixar (ffmpeg em `bin/ffmpeg`, fonte Poppins,
  modelo de recorte de pessoa)? Se `setup` mudou, o Douglas precisa rodar de novo.
- **Modelos que baixam na primeira vez**, e que vão pesar na primeira execução
  depois do release: OmniVoice, Demucs, Kokoro, Whisper. Diga quais a versão
  passou a usar e se algum é novo; são minutos e gigabytes, e é o Douglas quem
  decide quando baixar.
- **Ollama para tradução**: o modelo padrão é o `gpt-oss:20b` (ou o que estiver em
  `DMAKER_TRANSLATE_MODEL`). Confirme com o Douglas que ele está instalado
  (`ollama list`) se a versão toca dublagem ou tradução. Nada sobe sem isso.
- **Cache e receita**: a versão alterou `MEZZ_VERSION`? Então o primeiro render
  depois de instalar refaz os mezaninos (mais lento uma vez); avise.
- **Spec/projetos**: o `domain/spec.py` mudou de forma que projetos antigos em
  `projects/` deixam de validar? Peça a migração ou a compatibilidade.

Esta auditoria só lê. Se não der para conferir algo (modelo instalado, `ollama
list`), liste o que precisa ser conferido e **peça a confirmação ao Douglas** em
vez de assumir.

## 5. Auditoria D: a develop está sã

```bash
git fetch origin && git checkout develop && git pull
```

Sem CI, **esta é a única verificação de integração da versão inteira**: os três
portões (`_comum/qualidade.md`), em primeiro plano e com `timeout: 600000`:

```powershell
.venv\Scripts\ruff check src tests
.venv\Scripts\ruff format --check src tests
.venv\Scripts\python -m pytest -q
```

Se a versão tocou voz, isolamento vocal ou transcrição, some os testes de fumaça
com modelo real (`DMAKER_VOICE_SMOKE=1`, ver `_comum/qualidade.md`). Some também o
smoke de linha de comando, que prova que o pacote instala e abre:
`dmaker --help`, `dmaker presets` e `dmaker doctor`.

Autorize o apurador a fazer o `checkout` e o `pull` (ele não mexe no working tree
por padrão) e peça o resultado condensado: uma linha por portão, e só as linhas
do erro quando algum reprovar.

## 6. Apresente o resultado e espere o aval

Um relatório em PT-BR com o veredito claro logo na primeira linha: **pronta para
subir** ou **bloqueada por N itens**, seguido das quatro auditorias, cada
bloqueio com o que fazer para destravá-lo.

Se estiver liberada, diga o que vai acontecer quando ele autorizar: o texto do
bloco da versão no CHANGELOG, a tag `vX`, o que ele precisa instalar ou baixar
(extras, modelos) e o que você vai conferir depois. Então **pare e espere**.

## 7. Com o aval: feche a versão e faça o release

Os passos 1 a 3 vão num `dmaker-executor` (o fechamento do CHANGELOG é a **única**
exceção em que ele commita direto na `develop`, e o briefing precisa dizer isso).
Os passos 4 e 5 são seus, sempre.

1. **Feche a versão no CHANGELOG, na `develop`, ANTES do merge.** Troque
   `## [Não lançado]` por `## vX — AAAA-MM-DD` com a data de hoje, e abra um novo
   `## [Não lançado]` vazio acima dele. Fechar depois do merge faz a seção
   **duplicar** (`_comum/qualidade.md`). Commit e push na `develop`.
2. **Abra o PR de release `develop` → `main`.** Nunca push direto: o PR dá
   trilha. Corpo do PR = o resumo da versão, com os pré-requisitos na máquina
   listados como já conferidos. **O texto do corpo é seu**: sai da auditoria que
   você acabou de fazer, e vai verbatim no briefing.
3. **Confirme que o PR está limpo:** `gh pr view <n> --json mergeable,mergeStateStatus`.
   Não há CI para esperar; o portão foi a auditoria D, e ela precisa ter sido
   rodada no commit que está em ponta de `develop` (se entrou commit depois dela,
   rode de novo).
4. **Mergeie com merge commit** (`gh pr merge <n> --merge`). É o ato que publica a
   versão, e o comando é **seu**: não delegue, não peça a ninguém que o rode
   "junto com o resto". Confira antes que o PR é `develop` → `main` e que a
   autorização do Douglas veio nesta conversa.
5. **Crie a tag e empurre.** Com a `main` local igual à remota:
   ```bash
   git checkout main && git pull origin main
   git tag -a vX -m "DMaker vX"
   git push origin vX
   git push origin main   # só se a main local tiver algo a mais; normalmente já está igual
   ```
   Confirme com `git ls-remote --tags origin vX` e
   `git rev-parse main origin/main` (devem ser iguais).

## 8. Depois do release: reinstale e confirme que está de pé

Um release não termina no merge: termina quando o pacote instalado na máquina é o
da `main` e funciona. Vai para o `dmaker-apurador`, numerado:

1. Com a `main` em checkout, reinstalar a partir dela:
   `.venv\Scripts\python -m pip install -e .[voice,captions]` (as extras que o
   Douglas usa; se só mudou o código, `pip install -e .` basta). **Não mate o
   `dmaker ui`, o `dmaker mcp` nem render dele**: no Windows, um `dmaker.exe` em
   uso impede o pip de substituí-lo. Se der erro de arquivo em uso, pare e peça
   que ele feche, em vez de matar o processo.
   **Interface nova (Vue):** o `src/dmaker/ui/dist/` não vai para o git, então o
   release **roda o build do front** antes do smoke: `cd frontend; npm ci; npm run build`.
   Sem o `dist`, `dmaker ui` continua servindo a interface clássica em `/`.
2. Smoke: `dmaker --help`, `dmaker presets` e `dmaker doctor` (saída de exit
   code 0, e `doctor` sem item vermelho novo). `dmaker --version` deve mostrar a
   versão do pacote.
3. Se a versão trouxe comando ou ferramenta MCP nova, rodar o `--help` dela.
4. **Erros** de inicialização, citados. Peça as linhas de erro, não o log.

Se ele voltar com qualquer coisa ambígua, confira você mesmo o ponto exato. Se
algo falhar, diga imediatamente o que falhou e o estado real. Não há rollback
automático: o desfazer é `git revert` do merge de release numa `develop` limpa, e
só com a decisão do Douglas.

Deixe o repositório no estado em que o Douglas trabalha: depois do smoke, volte
para a `develop` (`git checkout develop`), a menos que ele peça para ficar na
`main`.

## 9. Depois de no ar

Reporte: o que foi lançado, o commit de merge, a tag, e o resultado do smoke.

Pergunte ao Douglas se ele quer que você **marque a versão como lançada** no Jira
(os cards já estão em `Concluído`): não faça por conta própria, é um estado que
ele pode querer usar de outro jeito. Ofereça também a skill
`dmaker-catalogo-funcionalidades` para atualizar o catálogo com o que acabou de
sair.

Vale registrar o que a preparação exigiu desta vez (extra novo, modelo para
baixar, `MEZZ_VERSION`, migração de projeto): é isso que faz o próximo release não
repetir a mesma descoberta.
