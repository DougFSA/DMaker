# DMaker

Editor de vídeos curtos por comando. Python 3.11+ (venv em `.venv`), FFmpeg 9 em `bin/ffmpeg` (baixado por `dmaker setup`), Poppins em `assets/fonts`, marcas em `assets/brands/<nome>/brand.json`.

- Como operar o editor a partir de um pedido: `.claude/skills/dmaker/SKILL.md` (fluxo e regras da marca, enxuta); a referência completa da spec, presets, multicâmera e picture-in-picture está no recurso MCP `dmaker://guide` (ferramenta `dmaker_guide`), lido só quando necessário.
- Rodar comandos: `.venv\Scripts\dmaker.exe ...` (não use o Python global). Servidor MCP: `dmaker mcp` (config em `.mcp.json`). Interface: `dmaker ui`.
- Desenvolvimento com economia de tokens: skill `dmaker-dev` (`.claude/skills/dmaker-dev/SKILL.md`): Opus planeja e revisa, agentes Sonnet implementam.
- Testes: `.venv\Scripts\python -m pytest` (~2 min; a integração renderiza com ffmpeg e o MCP sobe por stdio). Lint/format: `.venv\Scripts\ruff check --fix src tests && .venv\Scripts\ruff format src tests`. Os dois precisam passar antes de dar algo por pronto.
- Os testes nunca tocam nos dados reais: `tests/conftest.py` aponta `DMAKER_DATA_DIR` e todos os diretórios de dados do `config` para pastas temporárias, e `tests/guard.py` reprova a escrita em `cache/`, `output/`, `projects/`, `assets/voices/` e nos léxicos. Em código novo, leia `config.X_DIR` na hora do uso (nunca `from ..config import X_DIR` como default).
- Fluxo de trabalho pelo Jira (projeto DMK): cada chamado sai da `develop` num branch `feat/dmk-XXX-slug` ou `fix/dmk-XXX-slug` e entra por PR, que o executor **mergeia na própria entrega** (o Douglas testa sempre pela `develop`); nunca commit direto na `develop` nem na `main`. Skills em `.claude/skills/`: `dmaker-rodada` (chamados novos), `dmaker-redesenvolvimento` (reprovados, corrigidos a partir da `develop`), `dmaker-producao` (release e tag), `dmaker-mapa-de-testes` (o que testar na `develop`), `dmaker-catalogo-funcionalidades` e `dmaker-merge-develop` (exceção: PRs que ficaram abertos). Regras comuns em `.claude/skills/_comum/`; agentes `dmaker-apurador` e `dmaker-executor` em `.claude/agents/`.
- Sem CI: ruff e pytest locais são o último portão antes do PR. O `CHANGELOG.md` registra o que entra (bloco `[Não lançado]`, uma linha `DMK-xxx` por chamado novo).

- Interface nova (Vue 3 + Vite + TypeScript, pasta `frontend/`, só consome a API de `ui/server.py`): em `frontend/`, `npm run lint`, `npm run typecheck`, `npm run test` e `npm run build` (gera `src/dmaker/ui/dist/`, fora do git; o release roda o build). Com o `dist`, `dmaker ui` serve a nova em `/` e a clássica (HTML/JS puro em `ui/static/`) em `/classica`.

## Arquitetura (pacotes por responsabilidade)

```
agent/       llm.py (ChatModel: OllamaChat), openai_chat.py (OpenAICompatibleChat: llama.cpp server, LM Studio), settings.py (motor e modelo por
             variável de ambiente), tools.py (McpToolHost), kits.py (kits de ferramentas e excluídas, dado puro), triage.py (escolhe o kit pelo pedido),
             prompt.py (regras essenciais + manual do kit), safety.py (esquema, caminho inventado e confirmação: ToolGate), loop.py (AgentLoop),
             session.py (AgentSession), offline.py (`doctor --offline`), evaluation.py e evaluation_runner.py (bateria `agent eval`): operador local
             por um modelo pequeno sobre as ferramentas MCP, sem internet (dmaker agent, tela Agente)
domain/      spec.py (modelo Pydantic do projeto), dub.py (projeto de dublagem, `.dub.json`), presets.py, brand.py, timeline.py (contas puras), batch_sheet.py (planilha do lote: leitura de CSV/JSON e casamento das colunas com o modelo, puro)
media/       ffmpeg.py (FFmpegCommand, FFmpegRunner: SubprocessRunner | RecordingRunner, ProgressSink), probe.py, fonts.py, audiosync.py (correlação de áudio), matting.py (Matter: RvmMatter, recorte de pessoa por ONNX), separation.py (VocalSeparator: DemucsSeparator, voz x fundo), browser.py (Browser: PlaywrightBrowser, Chromium por protocolo: imprime PDF e tira capturas; extra `docs`)
text/        ass.py (ASS), overlays.py (texto/legendas -> eventos), captions.py (cues, SRT, regroup), transcribe.py (Transcriber: WhisperTranscriber), translate.py (Translator: OllamaTranslator, tradução em lotes com contexto)
voice/       synth.py (SpeechSynthesizer: OmniVoiceSynthesizer), router.py, library.py (VoiceLibrary), reference.py, pronunciation.py, speech_edit.py (achar o trecho e planejar a emenda, puro), levels.py (volume e ponto mais quieto, puro), dub_plan.py (frases, espaço de cada fala e regra de velocidade da dublagem, puro)
visuals/     cards.py (cartões e fundos), motion.py (Ken Burns sub-pixel), reframe_image.py, geometry.py, pip.py (máscara/moldura do PiP)
filtergraph/ grafos e comandos ffmpeg como funções puras: reframe, timeline (xfade), overlays, pip (picture-in-picture), audio, encode, mezzanine, voice, stems, speech_edit (emenda de fala regravada), dub (mixagem da dublagem)
pipeline/    recipes (receitas MCP: narrar no projeto, cortar e legendar, explicativo), context (RenderContext/Options/Result), sources (avulsas e sessão multicâmera), sync (offsets com cache), isolation (stems em cache), narration, voices, speech_fix (regravar fala com a voz do falante), dubbing (dublar: preparar e gerar), segments (preparadores por tipo), captions, textlayer, assembly (+ LoudnessMeter), renderer (orquestra), projects (serviços), jobs, qa, lint, batch (lote de vídeos de uma planilha: batch_files, batch_validation, batch_state, batch_report, filelock)
manual/      o manual (docs/MANUAL.md): outline.py (tarefas por molde fixo), reference_cli/reference_mcp/reference_spec (referência gerada, funções puras), ia_docs.py (docs/ia e llms.txt), examples.py (confere os exemplos contra o código), search.py + bm25.py + tokens.py (busca BM25), ask.py (`dmaker ajuda`: ChatModel injetado), evaluation.py (bateria de perguntas), export.py (HTML de página única), build.py (monta tudo, puro); só files.py e service.py tocam o disco
ui/          server.py (API FastAPI local + SSE de jobs), voice_routes.py, speech_routes.py e dub_routes.py (aba Voz), agent_routes.py (conversa com o agente local) e static/ (página, vanilla JS)
cli.py       adaptador Typer, fino    mcp_server.py   adaptador MCP, fino (mesmos serviços)
```

Progresso: o `FFmpegRunner` recebe um `ProgressSink` (Rich no terminal, `JobSink` na interface/MCP); o pipeline emite etapas por `ctx.log`. Jobs em segundo plano em `pipeline/jobs.py` (eventos + SSE).

Fluxo do render: `resolve_sources` -> `MezzanineBuilder` (um `SegmentPreparer` por tipo; cache em `cache/mez` por hash) -> `CaptionPipeline` -> `build_text_layer` (ASS) -> `LoudnessMeter` -> `build_assembly` -> runner -> thumbnail.

## Padrões de desenvolvimento (obrigatórios)

- **SOLID.** Uma responsabilidade por módulo/classe. Novos tipos de trecho, sobreposição ou fonte de legenda entram por extensão (novo preparador/builder registrado), não por `if/elif` espalhado. Dependências externas (ffmpeg, Whisper, probe) entram por protocolo e injeção (`FFmpegRunner`, `Transcriber`, `Prober`), nunca chamadas diretas dentro do pipeline.
- **Funções puras onde der.** Grafos de filtro, contas de linha do tempo, planos de movimento e geração de ASS não executam nada e não tocam disco: recebem dados, devolvem dados. Só o runner executa.
- **Testes unitários acompanham cada mudança.** Toda função pura tem teste direto; o pipeline tem teste com `RecordingRunner` + probe falso + transcritor falso (`tests/test_pipeline_unit.py`); o que envolve ffmpeg de verdade fica em `test_render_integration.py`. Qualidade visual mensurável tem teste numérico (ex.: `test_rendered_zoom_is_smooth_without_jitter`).
- **Código limpo e legível por humano.** Nomes que dizem o que é, funções curtas, docstrings de uma frase dizendo o porquê (não o como), sem comentários óbvios, sem abreviações crípticas, sem parâmetros booleanos em série. Mensagens, docs e comentários em português do Brasil; identificadores em inglês.
- **Nada de mágica no FFmpeg.** Cada opção de codificação, filtro ou valor de zona segura tem justificativa no comentário ou docstring. Mudou a receita do mezanino: incremente `MEZZ_VERSION` em `pipeline/segments.py`.
- Regras da marca (sem travessão em texto na tela) valem para exemplos, templates e mensagens.
- Ao escrever arquivos com barras invertidas pelo Bash (heredoc), o `\\` vira `\`; use as ferramentas Write/Edit para código com escapes.
