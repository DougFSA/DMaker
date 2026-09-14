# DMaker

Editor de vídeos curtos por comando. Python 3.11+ (venv em `.venv`), FFmpeg 9 em `bin/ffmpeg` (baixado por `dmaker setup`), Poppins em `assets/fonts`, marcas em `assets/brands/<nome>/brand.json`.

- Como operar o editor a partir de um pedido: `.claude/skills/dmaker/SKILL.md` (fluxo e regras da marca, enxuta); a referência completa da spec, presets, multicâmera e picture-in-picture está no recurso MCP `dmaker://guide` (ferramenta `dmaker_guide`), lido só quando necessário.
- Rodar comandos: `.venv\Scripts\dmaker.exe ...` (não use o Python global). Servidor MCP: `dmaker mcp` (config em `.mcp.json`). Interface: `dmaker ui`.
- Desenvolvimento com economia de tokens: skill `dmaker-dev` (`.claude/skills/dmaker-dev/SKILL.md`): Opus planeja e revisa, agentes Sonnet implementam.
- Testes: `.venv\Scripts\python -m pytest` (~2 min; a integração renderiza com ffmpeg e o MCP sobe por stdio). Lint/format: `.venv\Scripts\ruff check --fix src tests && .venv\Scripts\ruff format src tests`. Os dois precisam passar antes de dar algo por pronto.

## Arquitetura (pacotes por responsabilidade)

```
agent/       llm.py (OllamaChat), tools.py (McpToolHost), prompt.py, loop.py (AgentLoop): operador local
             por um modelo do Ollama sobre as ferramentas MCP, para tarefas mecânicas (dmaker agent)
domain/      spec.py (modelo Pydantic do projeto), presets.py, brand.py, timeline.py (contas puras)
media/       ffmpeg.py (FFmpegCommand, FFmpegRunner: SubprocessRunner | RecordingRunner, ProgressSink), probe.py, fonts.py, audiosync.py (correlação de áudio), matting.py (Matter: RvmMatter, recorte de pessoa por ONNX)
text/        ass.py (ASS), overlays.py (texto/legendas -> eventos), captions.py (cues, SRT, regroup), transcribe.py (Transcriber: WhisperTranscriber)
visuals/     cards.py (cartões e fundos), motion.py (Ken Burns sub-pixel), reframe_image.py, geometry.py, pip.py (máscara/moldura do PiP)
filtergraph/ grafos e comandos ffmpeg como funções puras: reframe, timeline (xfade), overlays, pip (picture-in-picture), audio, encode, mezzanine
pipeline/    context (RenderContext/Options/Result), sources (avulsas e sessão multicâmera), sync (offsets com cache), segments (preparadores por tipo), captions, textlayer, assembly (+ LoudnessMeter), renderer (orquestra), projects (serviços), jobs, qa, lint
ui/          server.py (API FastAPI local + SSE de jobs) e static/ (página, vanilla JS)
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
