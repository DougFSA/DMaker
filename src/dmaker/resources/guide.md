# Manual completo do DMaker

Referência detalhada para quando o fluxo básico da skill não basta: spec completa, presets, multicâmera,
picture-in-picture, legendas e receitas. Leia isto pela ferramenta MCP `dmaker_guide` ou o recurso
`dmaker://guide`, não de cor.

## Presets (`presets` no MCP, `dmaker presets` na CLI)

| id | tamanho | limite | uso |
|---|---|---|---|
| instagram/reels | 1080x1920 | 180 s | reels (padrão para vertical) |
| instagram/stories | 1080x1920 | 60 s | stories |
| instagram/feed-portrait | 1080x1350 | 90 s | post 4:5 |
| instagram/feed-square | 1080x1080 | 90 s | post 1:1 |
| instagram/feed-landscape | 1080x608 | 90 s | post horizontal |
| facebook/reels, facebook/stories (20 s), facebook/feed-portrait, feed-square, feed-landscape (1920x1080) | | | |
| youtube/shorts | 1080x1920 | 180 s | shorts |
| youtube/video | 1920x1080 | sem limite | vídeo longo |
| youtube/video-4k | 3840x2160 | sem limite | vídeo longo 4K |
| tiktok/video, whatsapp/status (30 s), linkedin/feed-square, linkedin/feed-landscape | | | |

Atalhos aceitos: reels, stories, shorts, youtube, feed, square, tiktok, status, linkedin.

## Templates parametrizados

`list_templates()` lista os templates de `templates/*.json` com descrição, resumo e parâmetros (tipo,
obrigatório, valor padrão). `new_from_template(template, name, params)` monta e salva o projeto sem
escrever a spec inteira; erro de parâmetro nomeia o que falta ou está errado. Um template é uma spec
normal com placeholders `{{nome}}`, listas via `$for` e trechos condicionais via `$if`; ver
`templates/README.md` para o formato completo e criar um template novo.

Só escreva a spec na mão (`save_project`) quando nenhum template cobrir o pedido: aí ainda assim comece
copiando o template mais próximo.

## Spec JSON (referência completa)

```json
{
  "name": "medlycare-agenda-reel",
  "output": { "preset": "instagram/reels", "quality": "high" },
  "brand": "medlycare",
  "timeline": [
    { "type": "card", "title": "Sua agenda em um clique", "subtitle": "MedlyCare", "duration": 3, "variant": "light" },
    { "type": "clip", "src": "D:/videos/take1.mp4", "start": 2.0, "end": 14.5, "speed": 1.0,
      "reframe": { "mode": "auto", "focus": [0.5, 0.4] }, "volume": 1.0,
      "transition": { "type": "fade", "duration": 0.5 } },
    { "type": "image", "src": "print.png", "duration": 4, "motion": "zoom-in", "transition": { "type": "slideleft", "duration": 0.4 } },
    { "type": "card", "title": "Teste grátis por 3 meses, sem cartão", "subtitle": "medlycare.com.br", "variant": "dark", "duration": 4, "transition": { "type": "fade", "duration": 0.6 } }
  ],
  "overlays": [
    { "type": "image", "src": "logo:symbol", "position": "top-right", "width": 0.11, "start": 3, "end": 18 },
    { "type": "text", "text": "Chega de agenda no papel", "role": "hook", "start": 3, "end": 7 },
    { "type": "text", "text": "Agenda por profissional", "role": "subtitle", "position": "bottom", "start": 3, "end": 7 },
    { "type": "text", "text": "Dra. Helena Prado", "secondary": "Clínica Modelo", "role": "lower-third", "start": 8, "end": 13 },
    { "type": "text", "text": "medlycare.com.br", "role": "cta", "start": 14, "end": 18 },
    { "type": "progress-bar" }
  ],
  "captions": { "source": "auto", "language": "pt", "model": "small", "style": { "mode": "karaoke", "max_words": 4 } },
  "audio": { "music": { "src": "trilha.mp3", "volume": 0.18, "ducking": true }, "normalize": "two-pass" }
}
```

Regras e valores:

- **Tempos em segundos.** `transition` de um trecho é a entrada dele (vindo do anterior); tipos: `cut`, `fade`, `dissolve`, `wipeleft/right/up/down`, `slideleft/right/up/down`, `smoothleft`, `circleopen`, `zoomin`, `fadeblack`, `fadewhite`, `pixelize`... (nomes do xfade). Transição consome tempo: duração final = soma dos trechos menos as transições (`validate_project` mostra).
- **Trechos**: `clip` (vídeo; `src` + `start`/`end` no arquivo fonte, ou `source` + tempos da sessão, ver multicâmera; `speed` 0.25 a 8, `volume`, `mute`, `fade_in/out`), `image` (foto/print; `duration`, `motion`: none, zoom-in, zoom-out, pan-left, pan-right, `motion_amount` 0.04 a 0.15 fica elegante; movimento sub-pixel com easing, sem tremor), `card` (cartão gerado no visual do tema: `title`, `subtitle`, `variant` light/dark, `logo`).
- **reframe.mode**: `auto` (recomendado: corta se a proporção for parecida; senão usa `brand` quando há marca ou `blur`), `crop` (preenche e corta; `focus` [x, y] de 0 a 1 diz onde está o assunto), `pad` (barras, `pad_color`), `blur` (fundo desfocado), `brand` (fonte inteira sobre fundo gerado com o visual do tema, com sombra; imagens ganham cantos redondos), `stretch`. Vídeo horizontal de pessoa falando para reels: `crop` com `focus` no rosto. Print de tela/produto: `brand`.
- **matte** (só em `clip`): troca o fundo atrás da pessoa por uma cor lisa, sem chroma key (rede neural de matting de vídeo, RVM). `{"matte": {"background": "#FFFFFF"}}`; `background` aceita hex ou chave do tema (`primary`, `accent`, `mint`, `white`). `model`: `resnet50` (padrão, separa melhor cadeira/objeto que encosta na pessoa, mais lento na CPU) ou `mobilenetv3` (mais leve e rápido, bom para rascunho). O recorte fica em cache: o preview já faz o trabalho pesado e o render final reaproveita. Funciona bem com pessoa falando de frente e fundo parado; movimentos rápidos podem falhar na borda.
- **color**: `brightness` (-1..1), `contrast`, `saturation`, `gamma`, `sharpen`, `denoise`, `vignette`, `lut` (.cube), `extra` (filtro ffmpeg cru).
- **Sobreposições de texto** (`role`): `hook` (gancho grande no topo, animação pop), `title`, `subtitle` (texto de apoio; `position` top/center/bottom), `cta` (pílula na cor da marca, slide-up), `lower-third` (nome + `secondary`, barra de destaque), `custom`. Sobre cartões e fundo `brand` o texto muda sozinho para a cor da marca (fundo claro) ou branco (fundo escuro). `style` sobrescreve tudo: `size` (px na base 1080), `color`, `outline`, `box`, `box_color`, `uppercase`, `align`, `max_width`, `font`, `weight`. `animation`: fade, pop, slide-up, typewriter, none. `x`/`y` (0..1) forçam posição.
- **Sobreposição de imagem**: `src` = `logo` (lockup horizontal), `logo:symbol`, `logo:horizontal_dark`, `logo:symbol_dark` ou caminho de PNG. `position`, `width` (fração da largura), `margin` (px na base 1080), `safe_zone` (padrão true; false cola no canto, ignorando a zona coberta pela interface do app), `opacity`, `start`/`end`, `fade`.
- **progress-bar**: barra de progresso fina na base (cor accent do tema).
- **Picture-in-picture** (`type: "video"` numa sobreposição): um segundo vídeo sobre a linha do tempo, como no Shotcut (Size & Position + Crop Circle/Mask). `src` + `offset` (ponto de entrada no arquivo) ou `source` + `offset` (tempo da sessão mostrado em `start`); `start`/`end` na linha do tempo; `position` (cantos, top, bottom, center) ou `x`/`y`; `width` (fração da largura, 0.18 a 0.3 para webcam); `shape` rect/rounded/circle (`radius` para rounded, `aspect` como "16:9", círculo é 1:1); `border` + `border_color` (chave do tema ou hex), `shadow`, `softness`; `animation` fade/slide/none; `volume` mistura o áudio do picture-in-picture (0 = mudo). Caso típico: tela gravada + webcam, ambos em `sources` com `sync: "auto"`, círculo no canto inferior direito com borda `accent` (template `templates/tutorial-tela-webcam.json`).
- **captions**: `source` = `auto` (transcreve com Whisper; `small` é o padrão, `medium` é mais preciso e mais lento) ou caminho `.srt`/`.json`. `style.mode`: `karaoke` (palavra a palavra, padrão reels), `classic`, `boxed`. `max_words`/`max_chars` por linha, `uppercase`, `size`, `y`, `pop` (aumenta a palavra ativa; desligado por padrão porque desloca a linha). `vocabulary` e `replacements` corrigem nomes próprios (o tema MedlyCare já traz os seus); some com os da marca.
- **audio**: `tracks` (faixas externas sincronizadas, ver multicâmera), `music` (`volume` 0.1 a 0.3 costuma bastar, `ducking` abaixa a música quando há voz, `loop`, `fade_in/out`, `start_at`), `voice_gain`, `normalize` (`two-pass` = -14 LUFS, padrão para redes; `fast`; `off`), `mute_clips`.
- **output**: `preset`, `quality` (`high` = x264 medium, padrão; `max` = x264 slow, mais lento e arquivo menor; `medium`; `draft`), `encoder` (`x264` padrão e melhor qualidade; `auto` usa encoder de hardware quando `dmaker doctor` detectar um, mais rápido e com qualidade um pouco menor), `fps`, `thumbnail_at`, `path`.
- Caminhos relativos resolvem a partir da pasta da spec. Prefira caminhos absolutos com `/`.

## Vídeos longos, multicâmera e áudio externo

Declare as fontes do mesmo evento em `sources` e diga qual é o relógio principal (`master`, padrão: a
primeira). `sync: "auto"` descobre pelo áudio em que instante do relógio principal cada fonte começa
(correlação; resultado em `projects/<nome>/sync.json`, reaproveitado depois). Clipes com `source` (em vez
de `src`) usam tempos **da sessão**, então trocar de câmera é só trocar o `source` e manter a contagem.
Faixas de `audio.tracks` seguem os cortes automaticamente e são misturadas ao áudio das câmeras.

```json
"sources": {"cam1": {"src": "cam1.mp4"}, "cam2": {"src": "cam2.mp4", "sync": "auto"}, "rec": {"src": "altar.wav", "sync": "auto"}},
"timeline": [{"type": "clip", "source": "cam1", "start": 120, "end": 150}, {"type": "clip", "source": "cam2", "start": 150, "end": 200, "transition": {"type": "cut"}}],
"audio": {"tracks": [{"source": "rec", "volume": 1.0}]}
```

- `sync_sources(master, others)` (MCP) ou `dmaker sync` (CLI) mostra o deslocamento e a confiança antes de
  gravar na spec; confiança abaixo de 4, confira à mão.
- Revisar sem renderizar tudo: `render_project(preview=true, segments="3-6")` (só esses trechos, sem
  sobreposições nem legendas).
- Cronograma realista: mezaninos ~1x tempo real e render final ~1x em 1080p; um vídeo de 1 h leva ~2 h.
- Template: `templates/casamento-multicam.json`.

## Edições pontuais e linha do tempo

`edit_project(name, op)` carrega o projeto, aplica uma operação e salva, sem reescrever a spec inteira.
`timeline_view(name)` devolve a vista multitrilha (V2/V3... picture-in-picture, TX texto, GR imagem/barra
de progresso, V1 trechos, A1 áudio dos clipes, A2... faixas externas, MUS música, CC legendas), útil para
descobrir índices e tempos antes de editar.

Operações (`op["type"]`): `split` (`index`, `at` em segundos desde o início do trecho), `remove`
(`index`), `move` (`index`, `to`), `trim` (`index`, `side`: "in"/"out", `delta` em segundos), `duplicate`
(`index`), `insert` (`index`, `segment`: dict do trecho novo), `overlay_span` (`index`, `start`, `end`),
`overlay_remove` (`index`), `overlay_duplicate` (`index`), `set_field` (`path` com pontos e índices, ex.:
`"timeline.2.speed"`, `"overlays.0.style.size"`, `"sources.cam1.sync"`; `value` = `None` volta ao padrão).

```
edit_project("meu-reel", {"type": "split", "index": 1, "at": 2.5})
edit_project("meu-reel", {"type": "trim", "index": 0, "side": "out", "delta": -0.5})
edit_project("meu-reel", {"type": "set_field", "path": "timeline.2.speed", "value": 1.5})
```

## Legendas automáticas

`captions.source = "auto"` transcreve com Whisper e grava `projects/<nome>/captions.auto.json` (com
`probability` por palavra) e `.srt`, com cache por hash das fontes. `read_captions(name)` (padrão
`mode=compact`) devolve um resumo e só as cues suspeitas (baixa confiança, termo da marca ouvido errado,
cue longa/curta, substituição pendente); `mode=full` devolve tudo, com tempo por palavra, só quando
precisar inspecionar de verdade. `fix_captions(name, {"errado": "certo"})` corrige o texto de todas as
cues (o próximo render usa o corrigido); o cache de transcrição é reaproveitado enquanto as fontes não
mudarem, `force=true` refaz tudo.

## Regras da marca MedlyCare (`"brand": "medlycare"`)

- Fonte Poppins, cores: teal escuro `#0C535A` (primary), verde `#75B9A2` (accent), menta `#B2E1CF`. Logos
  em `assets/brands/medlycare/`.
- **Nunca travessão nem meia-risca** em texto na tela: usar vírgula, ponto, dois-pontos. `validate_project`
  avisa.
- Tom: abre pela dor do profissional, frases curtas, sem superlativo vazio, sem prometer o que o produto
  não faz. Só anunciar o que está em produção (ver skill `medlycare-marketing`). CTA sempre
  `medlycare.com.br`; oferta atual: teste de 3 meses sem cartão.
- Ritmo típico de reel de produto (15 a 30 s): cartão de abertura com a dor (3 s) -> 2 a 4 telas do
  produto em `brand` com legenda de seção (3 a 4 s cada) -> cartão escuro de CTA (4 s). Gancho nos 3
  primeiros segundos.
- Prints reais do produto: `C:\Users\Douglas Vasconcelos\Desktop\MedlyCare\Marketing\Prints do Produto\`
  (1000x620). Identidade visual: `...\Desktop\MedlyCare\Identidade Visual\`.

## Vídeos pessoais (sem brand)

Tema padrão: fundo escuro, destaque amarelo nas legendas, Poppins. Vídeo de celular vertical em reels:
`reframe.mode: crop`. Vídeo horizontal (câmera/drone) em reels: `crop` com `focus` no assunto, ou `blur`.
YouTube longo: `youtube/video` com `quality: high`; `lower-third` para nomes e `title` para capítulos.

## Receitas rápidas

- Um vídeo só, corte e formato: `quick_edit(src, preset="reels", start=3, end=33, captions=true, hook="texto", cta="medlycare.com.br", brand="medlycare")`.
- Só transcrever: `transcribe_media(path, language="pt", model="small")`.
- Cartão avulso para ver o design: `render_card_preview(title, subtitle, brand="medlycare", preset="reels")`.
- Limpar cache: `clean_cache()`.

## Depuração

- `dmaker render ... --dry-run` mostra os comandos ffmpeg. Grafos em `cache/jobs/<nome>/graph.pretty.txt`,
  o ASS (textos/legendas) em `overlay.ass`, comandos em `cmd.txt`.
- Erro do ffmpeg vem com as últimas linhas do stderr e o comando completo.
- `job_status(job_id)`/`list_jobs()` acompanham um render em segundo plano, local ou na interface.
- Testes: `.venv\Scripts\python -m pytest` (integração renderiza de verdade e leva uns 2 min).
