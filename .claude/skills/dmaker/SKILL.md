---
name: dmaker
description: Editor de vídeos curtos por comando (Instagram Reels/Stories/Feed, Facebook, YouTube Shorts/vídeo, TikTok, WhatsApp, LinkedIn). Use quando o usuário pedir para editar, cortar, legendar, adaptar formato ou montar um vídeo/reel/short/story, para o MedlyCare ou pessoal. Transforma o pedido em um spec JSON e renderiza com FFmpeg.
---

# DMaker: como operar o editor a partir de um pedido em linguagem natural

## Como rodar

Prefira o servidor MCP `dmaker` (`list_templates`, `new_from_template`, `save_project`, `validate_project`,
`render_project`, `qa_report`, `edit_project`, `fix_captions`...). Sem MCP, use a CLI: `D:\DMaker\.venv\Scripts\dmaker.exe <comando>` (nunca o Python global; `dmaker setup` se faltar
ffmpeg). `dmaker ui` abre a interface gráfica; `render_project`/`export_project` já abrem sozinhos para o
usuário acompanhar (`show_ui=false` só se ele pedir para não abrir). `dmaker agent` faz as tarefas
mecânicas (template, render, QA, legendas) com um modelo local do Ollama.

## Fluxo de trabalho (sempre nessa ordem)

1. **Entender o pedido**: plataforma(s), duração alvo, fontes (vídeos/fotos/prints/música), se tem fala
   (legenda automática), se é MedlyCare (`"brand": "medlycare"`) ou pessoal (sem brand).
2. **Ver os templates**: `list_templates()`. Um template já cobre a maioria dos pedidos (produto,
   depoimento, stories, vlog, tutorial, casamento...). Casamento da PASCOM: template `casamento-pascom`
   (duas câmeras, corte automático) seguido de `plan_multicam` (ver `dmaker://guide`).
3. **Criar o projeto**: `new_from_template(template, name, params)` é o caminho preferido; erro nomeia o
   parâmetro que falta. Sem template que sirva, inspecione as fontes (`probe_media`, nunca chute duração)
   e escreva a spec com `save_project` (referência completa em `dmaker://guide`).
4. **Validar**: `validate_project` (duração final, avisos de limite e de marca).
5. **Preview**: `render_project(preview=true)`.
6. **Conferir com `qa_report`**: checagens automáticas (zona segura, ritmo, contraste, legendas, e com
   `output=true` a saída renderizada). Só chame `contact_sheet`/`frames` (gastam tokens de imagem) se o
   relatório apontar algo ou o usuário pedir para olhar.
7. **Corrigir e repetir**: `edit_project` para ajustes pontuais (cortar, remover, mover, aparar, mudar um
   campo; `timeline_view` mostra os índices) e `fix_captions` para palavras erradas nas legendas. Volte ao
   passo 5.
8. **Render final** (`render_project`) e, se pedido, **`export_project`** para outros formatos. Entregue o
   caminho do mp4.

## O que continua sendo decisão da IA

O software não decide sozinho: os cortes, o ritmo, qual câmera aparece em cada momento (multicâmera) e
quais tomadas usar são chamadas de edição. Peça os instantes ao usuário ou avalie com
`contact_sheet`/`frames` nas fontes antes de montar a timeline. Exceções: gravação falada (`autocut`
corta pausas, vícios e repetições; `list_cuts`, `undo_cut`; nunca à mão com o Whisper) e cerimônia (bloco
`multicam` + `plan_multicam`: ritmo plausível por fase da fala; o ajuste fino é `edit_project`, pelos avisos).

## Regras da marca MedlyCare (`"brand": "medlycare"`)

Cores, fonte e logos vêm do tema da marca automaticamente, não escreva valores na mão. Nunca travessão
nem meia-risca em texto na tela (vírgula, ponto ou dois-pontos no lugar); `validate_project` avisa. CTA
sempre `medlycare.com.br`; oferta atual: teste grátis de 3 meses sem cartão. Vocabulário e nomes próprios
da marca (para a transcrição acertar) já vêm no tema; `captions.vocabulary`/`replacements` somam com os
dele. Tom e regras completas de comunicação: skill `medlycare-marketing`.

## Voz e narração

Voz local. OmniVoice (clones `clone_voice`, vozes por descrição `design_voice`): ~50 s por
segundo de áudio (`draft=true`: metade). Para conferir o roteiro, Kokoro (`dora`, `alex`, `santa`; ~3 s/s).
Toda fala leva marca inaudível e o arquivo, etiqueta de procedência; confira: `verify_watermark`, `dmaker voice verify`.
MCP: `list_voices`, `synthesize_speech` (job: `job_status`). CLI: `dmaker voice say|clone|design|list|
remove|preview`. Pronúncia ("DMaker" sai "DeMaker"): ferramenta `pronunciation` ou `dmaker voice lexicon
add|list|remove [--brand --language]`; no texto, `[[termo|pronúncia]]`. Veja o guia.
Separar voz de música/ruído: `isolate_vocals` (job) ou `audio_mode: voice|background`; lento, em cache.
Palavra dita errado: `speech_words` e `fix_speech` (jobs) regravam o trecho na voz do falante. Trocar a voz da gravação: `convert_voice`.
Dublar para outro idioma (uma voz clonada por pessoa, fundo mantido): `dub_prepare`, revisar com `dub_get` e
`dub_update_segment` (texto ou `speaker`), `dub_render` (jobs; só a fala editada é refeita). CLI: `dmaker dub ARQUIVO --to en`.

## Quando ler `dmaker://guide`

O manual completo (recurso MCP `dmaker://guide`, ou ferramenta `dmaker_guide`) tem a referência inteira da
spec (todos os campos de trecho, sobreposição, reenquadramento, cor), a tabela de presets, multicâmera e
áudio externo, picture-in-picture, o formato de `edit_project`/`timeline_view`, legendas automáticas e
receitas prontas. Leia quando for escrever uma spec na mão, usar multicâmera, picture-in-picture ou uma
operação de `edit_project` que não lembra o formato.

## Depuração

- `dmaker render ... --dry-run` mostra os comandos ffmpeg sem rodar.
- Grafos em `cache/jobs/<nome>/graph.pretty.txt`, ASS (texto/legendas) em `overlay.ass`.
- Erro do ffmpeg vem com as últimas linhas do stderr e o comando completo.
- `job_status`/`list_jobs` acompanham um render em segundo plano, local ou na interface.
- Testes: `.venv\Scripts\python -m pytest` (integração renderiza de verdade, uns 2 min).
- Trilha muda/oculta na interface (campo `tracks` da spec) some também do render final: se áudio ou
  sobreposição não aparece no vídeo, confira `tracks`.
