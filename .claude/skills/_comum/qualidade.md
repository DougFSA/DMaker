# Portões, verificação e CHANGELOG

Referência compartilhada pelas skills do DMaker e pelos subagentes
`dmaker-executor` e `dmaker-apurador`.

## Sem CI: o portão local é o último portão

O DMaker **não tem CI**. Isso muda o peso de tudo abaixo: no MedlyCare, o CI
reprova o que passou local e segura o merge; aqui, nada segura. O que você não
rodar, o Douglas descobre testando, e uma `develop` quebrada trava o trabalho
dele. **O portão local é obrigatório antes de cada PR e não pode ser pulado**,
nem para "ajuste pequeno", nem para mudança só de texto que mexe em código.

## Portões: todos verdes antes de mover o card

Nenhum card vai para `Teste Manual` com portão vermelho. Rode sempre os três, da
raiz `D:\DMaker`, com o Python do venv (nunca o global):

```powershell
.venv\Scripts\ruff check src tests
.venv\Scripts\ruff format --check src tests
.venv\Scripts\python -m pytest -q
```

Para consertar o que o lint acusa, `ruff check --fix src tests` e
`ruff format src tests`, e rode os três de novo para confirmar.

O `pytest` leva **cerca de 5 minutos**: a integração renderiza com ffmpeg de
verdade e o servidor MCP sobe por stdio. Isso não é lentidão a contornar, é o que
faz o teste valer.

### Portões do front (pasta `frontend/`, interface Vue)

Mexeu em `frontend/`? Rode também estes quatro, de dentro da pasta (`cd frontend`),
e todos precisam passar, **além** dos três do Python acima:

```powershell
npm run lint        # eslint, sem avisos
npm run typecheck   # vue-tsc em modo strict
npm run test        # vitest: cliente da API, stores e componentes
npm run build       # gera src/dmaker/ui/dist/ (artefato, fora do git)
```

A primeira vez, `npm ci` instala as dependências (versões fixas no
`package-lock.json`). O `dist` não é commitado: quem lança a versão roda o build
(`dmaker-producao`, seção "Depois do release"). Com o `dist` presente, `dmaker ui`
serve a interface nova em `/` e a clássica em `/classica`; sem ele, a clássica
continua em `/`. Para ver a tela ao vivo, `npm run dev` (porta 5174, com proxy de
`/api` para o `dmaker ui`; troque o destino com `DMAKER_API`).

### Rode os portões em PRIMEIRO PLANO

Nunca dispare o `pytest` (nem `ruff`, nem `gh pr checks`) em segundo plano e
encerre o turno esperando a notificação. Aconteceu no MedlyCare, em 09/08/2026:
isso travou executores **quatro vezes**. O agente mandava o build para o
background, devolvia "aguardando o build terminar" e parava; o card ficava a meio
caminho e alguém tinha que destravar rodando o portão por ele.

Espere. Como o `pytest` passa de 2 minutos (o padrão de timeout do Bash), passe
`timeout: 600000` (o máximo) na chamada. Se mesmo assim estourar, rode em
subconjuntos em primeiro plano (`-k`, ou arquivo a arquivo) e depois a suíte
inteira, mas não entregue sem uma execução completa verde.

### Testes com modelo real

Testes que usam modelos pesados de verdade (OmniVoice, Demucs, Kokoro, Whisper)
ficam **atrás de `DMAKER_VOICE_SMOKE=1`** e não rodam por padrão. Se o card toca
voz, isolamento vocal ou transcrição, rode também o smoke correspondente:

```powershell
$env:DMAKER_VOICE_SMOKE = "1"
.venv\Scripts\python -m pytest -q tests/test_voice_omnivoice_smoke.py tests/test_separation.py
```

(Hoje são esses dois arquivos; `grep -rn DMAKER_VOICE_SMOKE tests` lista os que
existirem quando você ler isto.)

A primeira execução baixa modelos (minutos e gigabytes); avise o Douglas se for
preciso baixar algo que ele não tem. Não deixe a variável ligada na sessão depois.

## Verificação de verdade quando a mudança é visível ou audível

"Os testes passaram" não é evidência de que o vídeo ficou certo. O DMaker produz
imagem e som, e nenhum teste unitário enxerga o resultado final.

- **Render e visual:** `dmaker render <projeto> --preview` (ou o fluxo do card)
  e conferência por `dmaker qa <projeto>`, que é o relatório de QA em texto. Só
  olhe imagem (`dmaker sheet`, `dmaker frames`) quando o relatório apontar algo ou
  o card for sobre aparência. Qualidade visual mensurável ganha teste numérico
  (como `test_rendered_zoom_is_smooth_without_jitter`).
- **Interface (`dmaker ui`):** suba pelo `preview_start` com a configuração
  `dmaker-ui-8769` (`.claude/launch.json`) e use o navegador embutido
  (`mcp__Claude_Browser__*`): navegue, leia a página, confira console e rede. Não
  suba a UI por outro caminho nem em outra porta: a 8765 é a do Douglas.
- **Voz e áudio:** não dá para ouvir. Meça: transcreva o resultado com o
  `WhisperTranscriber` e compare com o texto esperado; meça RMS, duração e
  silêncios. "Gerou um wav" não prova que a fala está certa.
- **Fonte de verdade para projeto de teste:** use projetos e mídia sintéticos,
  gerados pelo teste ou por um script no scratchpad. Mídia de cliente fica em
  `projects/` e **não vai para commit, PR nem comentário** (`_comum/git.md`).

O que foi medido, com número, é o que entra na "Validação técnica" do Jira:
"antes 41 dB, depois 23 dB de ruído de fundo" evita a segunda rodada; "ficou
bom" não.

**Nunca mate os processos do Douglas.** Se ele tem o `dmaker ui` aberto (porta
8765) ou um render rodando, deixe de pé e use outra porta/projeto para testar.
Use `dmaker clean` com cuidado: ele apaga cache que um render dele pode estar
usando.

## Padrões do CLAUDE.md que o portão não pega

O `ruff` não sabe de arquitetura. Antes de abrir o PR, confira à mão:

- **SOLID e injeção:** ffmpeg, Whisper e probe entram por protocolo
  (`FFmpegRunner`, `Transcriber`, `Prober`), nunca chamados direto no pipeline.
  Tipo novo de trecho, sobreposição ou fonte de legenda entra por preparador ou
  construtor registrado, não por `if/elif` espalhado.
- **Funções puras:** grafos de filtro, contas de linha do tempo, planos de
  movimento e geração de ASS não executam nada e não tocam disco.
- **Teste junto:** toda função pura tem teste direto; o pipeline tem teste com
  `RecordingRunner` + probe falso + transcritor falso (`tests/test_pipeline_unit.py`);
  ffmpeg real só em `tests/test_render_integration.py`.
- **`MEZZ_VERSION`** em `pipeline/segments.py`: mudou a receita do mezanino,
  incremente. Esquecer faz o Douglas ver trecho antigo vindo do cache e achar que
  o conserto não pegou.
- **Nada de mágica no FFmpeg:** cada opção, filtro ou valor de zona segura tem
  justificativa no comentário ou na docstring.
- **Sem travessão (—)** em texto que vai para a tela: exemplos, templates,
  mensagens e cartões. É regra da marca.
- **Português do Brasil** em mensagens, docs e comentários; identificadores em
  inglês; docstring de uma frase dizendo o porquê.

Escrever arquivo com barras invertidas pelo Bash (heredoc) colapsa `\\` em `\`:
use Write/Edit para código com escapes.

## CHANGELOG

`CHANGELOG.md` na raiz, formato Keep a Changelog adaptado. O topo tem um bloco
`## [Não lançado]` que acumula o que está na `develop` e ainda não foi para a
`main`. Abaixo dele vêm as versões fechadas (`## vX — AAAA-MM-DD`) e, no fim, a
`## Linha de base` do que já existia antes do fluxo de develop.

- Seções nesta ordem, omitindo as vazias: `### Added`, `### Changed`,
  `### Fixed`, `### Chore`, `### Pré-requisitos na máquina`.
- Cada linha começa pela ref: `- **DMK-xxx**: ...`. Criticidade com `[Crít.]`.
- Em `Fixed`, diga o **mecanismo**, não o sintoma: "o resample usava a taxa da
  fonte em vez da do preset" vale mais que "áudio saía com tom errado".
- `Pré-requisitos na máquina` lista o que o Douglas precisa fazer ou ter para a
  versão funcionar depois de instalada: extra novo do pip, modelo que baixa na
  primeira vez, `dmaker setup` de novo, variável de ambiente. A auditoria de
  produção trata **cada linha** como item de checagem.

**Chamado novo entra no CHANGELOG. Rodada de redesenvolvimento não.** O
redesenvolvimento conserta algo que nunca chegou a ser lançado: registrar como
correção contaria ao usuário final um bug que ele nunca viu. A entrada original
do card, essa sim, deve descrever o comportamento final; ajuste-a se o
redesenvolvimento mudou o que ela promete.

Feche a versão na `develop` antes do merge para a `main`: fechar depois faz o
merge **duplicar** a seção.

## Testes: prenda o que some sem deixar rastro

Nem toda correção pede teste novo, mas duas categorias pedem, porque regridem em
silêncio e nenhuma leitura de código acusa:

- **Contratos entre arquivos distantes.** Ex.: o campo que a spec aceita, o
  schema que o MCP expõe e o formulário da interface precisam concordar. Um teste
  que lê os dois lados e confere custa dez linhas e teria evitado uma rodada.
- **Qualidade que se mede, não se vê.** Ex.: suavidade do zoom, nível de áudio
  depois da mixagem, sincronismo de legenda. Um teste numérico sobre o render
  real (ou sobre a função pura que o decide) prende o que o olho não pega.
