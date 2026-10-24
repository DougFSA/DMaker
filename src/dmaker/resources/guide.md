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
- **audio_mode** (só em `clip`): `original` (padrão), `voice` (só a voz, limpa de música e ruído) ou `background` (só o fundo, para dublar ou trocar a fala). Usa o isolamento vocal, lento na CPU; veja a seção "Isolamento vocal". Vale só para o áudio da própria câmera, não para `audio.tracks`.
- **color**: `brightness` (-1..1), `contrast`, `saturation`, `gamma`, `sharpen`, `denoise`, `vignette`, `lut` (.cube), `extra` (filtro ffmpeg cru).
- **Sobreposições de texto** (`role`): `hook` (gancho grande no topo, animação pop), `title`, `subtitle` (texto de apoio; `position` top/center/bottom), `cta` (pílula na cor da marca, slide-up), `lower-third` (nome + `secondary`, barra de destaque), `custom`. Sobre cartões e fundo `brand` o texto muda sozinho para a cor da marca (fundo claro) ou branco (fundo escuro). `style` sobrescreve tudo: `size` (px na base 1080), `color`, `outline`, `box`, `box_color`, `uppercase`, `align`, `max_width`, `font`, `weight`. `animation`: fade, pop, slide-up, typewriter, none. `x`/`y` (0..1) forçam posição.
- **Sobreposição de imagem**: `src` = `logo` (lockup horizontal), `logo:symbol`, `logo:horizontal_dark`, `logo:symbol_dark` ou caminho de PNG. `position`, `width` (fração da largura), `margin` (px na base 1080), `safe_zone` (padrão true; false cola no canto, ignorando a zona coberta pela interface do app), `opacity`, `start`/`end`, `fade`.
- **progress-bar**: barra de progresso fina na base (cor accent do tema).
- **Picture-in-picture** (`type: "video"` numa sobreposição): um segundo vídeo sobre a linha do tempo, como no Shotcut (Size & Position + Crop Circle/Mask). `src` + `offset` (ponto de entrada no arquivo) ou `source` + `offset` (tempo da sessão mostrado em `start`); `start`/`end` na linha do tempo; `position` (cantos, top, bottom, center) ou `x`/`y`; `width` (fração da largura, 0.18 a 0.3 para webcam); `shape` rect/rounded/circle (`radius` para rounded, `aspect` como "16:9", círculo é 1:1); `border` + `border_color` (chave do tema ou hex), `shadow`, `softness`; `animation` fade/slide/none; `volume` mistura o áudio do picture-in-picture (0 = mudo). Caso típico: tela gravada + webcam, ambos em `sources` com `sync: "auto"`, círculo no canto inferior direito com borda `accent` (template `templates/tutorial-tela-webcam.json`).
- **captions**: `source` = `auto` (transcreve com Whisper; `small` é o padrão, `medium` é mais preciso e mais lento) ou caminho `.srt`/`.json`. `style.mode`: `karaoke` (palavra a palavra, padrão reels), `classic`, `boxed`. `max_words`/`max_chars` por linha, `uppercase`, `size`, `y`, `pop` (aumenta a palavra ativa; desligado por padrão porque desloca a linha). `vocabulary` e `replacements` corrigem nomes próprios (o tema MedlyCare já traz os seus); some com os da marca.
- **audio**: `tracks` (faixas externas sincronizadas, ver multicâmera), `music` (`volume` 0.1 a 0.3 costuma bastar, `ducking` abaixa a música quando há voz, `loop`, `fade_in/out`, `start_at`; `spans` limita a música a janelas do vídeo final, cada uma com `start`, `end` (None = até o fim), `start_at`, `fade_in/out`, ex.: trilha só na abertura e no encerramento de um casamento; `from_end: true` conta `start`/`end` a partir do fim do vídeo em vez do começo, útil quando a duração final só se sabe depois de um `plan_multicam`; `tail: true` toca o FINAL da música, terminando junto com a janela, e `start_at` vira uma folga antes desse fim em vez de um ponto de entrada), `voice_gain`, `normalize` (`two-pass` = -14 LUFS, padrão para redes; `fast`; `off`), `mute_clips`.
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

### Câmera que grava em vários arquivos (`parts`)

Câmera que parte a gravação sozinha (a Canon corta a cada 30 min; o celular para e volta) usa `parts`
em vez de `src`: a lista dos arquivos, em ordem. O pipeline encadeia as partes pelo áudio sozinho, sem
precisar declarar uma fonte por arquivo nem calcular pontos de corte na mão:

```json
"sources": {
  "cam1": {"parts": ["cam1_0001.mp4", "cam1_0002.mp4", "cam1_0003.mp4", "cam1_0004.mp4"]},
  "cam2": {"src": "celular.mp4", "sync": "auto"}
}
```

Um clipe com `source: "cam1"` pode atravessar a fronteira entre dois arquivos sem que isso mude nada na
spec: `start`/`end` continuam no relógio da sessão inteira, e o pipeline parte o trecho sozinho no ponto
certo (o corte é interno, sem transição visível). Um trecho que cai num intervalo que nenhuma parte cobre
(arquivo faltando, gravação com buraco) dá erro claro na validação, com os intervalos que as partes cobrem.

Cada parte é ligada por áudio a uma parte já posicionada de QUALQUER outra fonte da sessão (não só à
principal); sem link confiável, o pipeline cai para o `creation_time` do próprio arquivo (detecta sozinho
se a câmera grava esse relógio no início ou no fim da gravação) e avisa "posicionada pelo relógio, confira"
em `dmaker validate`: vale a pena conferir esse trecho com `sync_sources` ou olhando os quadros
(`contact_sheet`) antes de renderizar tudo.

### Casamento padrão PASCOM (template `casamento-pascom`)

Fluxo completo, do pedido ao render final:

1. `new_from_template("casamento-pascom", nome, params)` com `camera_altar`/`camera_lateral` (as
   pastas das duas câmeras, tipo `dir`: viram sozinhas a lista dos arquivos, em ordem), `nomes` (lista
   de casais, "Nome & Nome") e `data`; o resto tem padrão (marca `pascom-sjb`, celebrante, diácono,
   cerimonial, músicos, trilha).
2. `plan_multicam(nome)` (CLI: `dmaker plan <nome>`): transcreve a câmera de áudio do bloco `multicam`,
   reconhece as fases da cerimônia pela fala e substitui o bloco pelos clipes de verdade, alternando as
   câmeras. Devolve avisos e a lista de fases reconhecidas com o instante de cada uma.
3. `validate_project`: confere a duração final e os avisos (o bloco expandido já não avisa mais nada
   sobre si mesmo).
4. `render_project(preview=true)`: prévia rápida para conferir o corte.
5. Conferir as fases reconhecidas e os avisos do passo 2 (buracos de cobertura entre as câmeras, partes
   posicionadas pelo relógio do arquivo em vez de um link de áudio confiável); ajustar com
   `edit_project` se precisar (trocar um trecho de câmera, mover um corte).
6. Render final (`render_project`).

**Formato do bloco `multicam`** (campo de topo da spec, ainda por planejar):

```json
"multicam": {
  "at": 2,
  "cameras": ["altar", "lateral"],
  "main": "altar",
  "audio": "altar",
  "cadence": [40, 30],
  "phases": "casamento",
  "min_clip": 4,
  "snap_window": 5,
  "pause": 0.6,
  "start": null,
  "end": null,
  "transition_in": { "type": "dissolve", "duration": 2.0 }
}
```

- `at`: índice da timeline onde os clipes planejados entram (o resto desloca; os cartões antes desse
  índice não mudam de lugar).
- `cameras`: nomes em `sources` que podem aparecer nos clipes; `main` é a que fica mais tempo em tela;
  `audio` é a fonte cuja fala é transcrita e usada para reconhecer as fases (os clipes de outras câmeras
  ficam mudos onde ela cobre, para não duplicar o áudio).
- `cadence`: `[tempo_na_principal, tempo_na_secundaria]` em segundos, o ritmo de troca de câmera fora de
  uma fase com regra própria.
- `phases`: `"casamento"` usa as fases padrão do rito (entrada, liturgia da palavra, votos, bênção das
  alianças, assinatura, saída...), cada uma reconhecida por termos ditos na fala; uma lista de regras
  próprias substitui isso: `[{"name": "...", "match": ["termo1", "termo2"], "main": "altar", "cadence":
  [60, 15], "max_duration": 300}]` (`match` é o que procurar na transcrição; `main`/`cadence` sobrescrevem
  os do bloco só nessa fase; `max_duration` limita o quanto essa fase pode durar).
- `min_clip`: menor duração aceitável de um clipe (evita cortes picotados); `snap_window`: encaixa um
  corte planejado numa pausa da fala a até essa distância, em vez de cortar no meio de uma frase;
  `pause`: silêncio mínimo (segundos) para contar como uma pausa.
- `start`/`end`: relógio da sessão (o da câmera `audio`) onde a cerimônia começa/termina; `null` cobre
  do início ao fim do que as câmeras gravaram.
- `transition_in`: transição do primeiro clipe planejado (o dos seguintes é decidido pelo planejador).

`validate_project` só avisa que o bloco ainda não foi expandido; `render_project` recusa renderizar com
um bloco `multicam` pendente (chame `plan_multicam` antes).

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

`project.tracks` (`dict[id da trilha] -> {"muted", "hidden", "locked"}`, ex.: `{"A2": {"muted": true}}`)
guarda o mudo/oculto/bloqueio por trilha da interface (botões M/H/cadeado); vale para a prévia E para o
render final (`domain.tracks.apply_track_state`), então uma faixa marcada aqui some do vídeo exportado.

## Legendas automáticas

`captions.source = "auto"` transcreve com Whisper e grava `projects/<nome>/captions.auto.json` (com
`probability` por palavra) e `.srt`, com cache por hash das fontes. `read_captions(name)` (padrão
`mode=compact`) devolve um resumo e só as cues suspeitas (baixa confiança, termo da marca ouvido errado,
cue longa/curta, substituição pendente); `mode=full` devolve tudo, com tempo por palavra, só quando
precisar inspecionar de verdade. `fix_captions(name, {"errado": "certo"})` corrige o texto de todas as
cues (o próximo render usa o corrigido); o cache de transcrição é reaproveitado enquanto as fontes não
mudarem, `force=true` refaz tudo.

## Voz e narração

Duas engines locais, sem custo, escolhidas pela voz (extra `voice`: `pip install torch torchaudio
--index-url https://download.pytorch.org/whl/cpu` e depois `pip install -e .[voice]`):

| Motor | Vozes | Quando usar | Velocidade na CPU (i5 de 4 núcleos, medido) |
|---|---|---|---|
| OmniVoice (padrão) | voz automática, clones (`clone_voice`) e vozes por descrição (`design_voice`) | narração final, realista | cerca de 50 s de processamento por segundo de áudio com 16 passos; ~25 s no rascunho (8 passos) |
| Kokoro-82M (opcional) | prontas: `dora` (feminina), `alex` e `santa` (masculinas), pt-BR | rascunho rápido para conferir roteiro e ritmo | cerca de 3 s por segundo de áudio |

Sem `voice` a narração usa o OmniVoice com voz automática (ou desenhada, se houver `instruct`); escolha
`dora`, `alex` ou `santa` para o Kokoro, ou defina `DMAKER_DEFAULT_VOICE=dora` para que ele seja o padrão.
Os modelos baixam sozinhos na primeira vez, com conferência de hash: OmniVoice (~3,2 GB) em
`cache/models/omnivoice`, Kokoro (~350 MB) em `cache/models/kokoro`. O Kokoro depende do espeak-ng (GPL-3,
instalado pelo `kokoro-onnx` como biblioteca à parte).

- Biblioteca: as vozes prontas vêm embutidas (não se removem); as suas ficam em `assets/voices/<id>/`
  (`voice.json` e, nos clones, `reference.wav`). `list_voices(brand)` lista prontas, da marca e sem marca,
  com `engine` e `kind` (`preset`, `clone` ou `design`).
- `clone_voice(name, reference_audio, reference_text?)`: gravação de fala limpa (3 a 15 s é o ideal e o
  mais rápido). Até 20 s a gravação vale inteira (sem silêncio nas pontas); acima disso o DMaker transcreve
  janelas de 15 s e guarda a que tem mais fala, com o texto dela (o `reference_text` passado é descartado,
  porque não alinha com um trecho). Sem `reference_text`, o Whisper transcreve.
- `design_voice(name, gender, age, pitch, accent, whisper)` ou `instruct` completo. Termos aceitos:
  gênero `male|female`; idade `child, teenager, young adult, middle-aged, elderly`; tom `very low pitch,
  low pitch, moderate pitch, high pitch, very high pitch`; sotaque `american, british, australian,
  chinese, canadian, indian, korean, portuguese, russian, japanese` + ` accent`; `whisper`. Apelidos em
  português (feminino, grave, idoso, britânico) são traduzidos.
- `synthesize_speech(text, out, voice, language, speed, instruct, seed, steps, srt, draft)`: job em segundo
  plano que devolve `job_id`; o resultado traz `output`, `duration_s` e `cues` (início, fim e texto de cada
  fala). Linha em branco é pausa de parágrafo, `[pausa 1.2]` fixa uma pausa em segundos, R$, % e números
  são lidos por extenso. Saída `.wav`, `.mp3` ou `.m4a` (48 kHz, mono). `speed` vai de 0.5 a 2 no Kokoro.
- Marca d'água: toda fala sintetizada (narração, projeto, correção de fala, dublagem) sai com uma marca
  inaudível de voz gerada por IA (AudioSeal, sobrevive ao AAC do vídeo). Ligada por padrão; desligue com
  `DMAKER_WATERMARK=0` ou `dmaker voice say --no-watermark`. `verify_watermark(path)` ou
  `dmaker voice verify ARQUIVO` (wav, mp3, m4a, mp4) devolve probabilidade e veredito. A marca entra na
  chave do cache de falas; áudio que o DMaker não sintetizou (vídeo do cliente, música) nunca é marcado.
- Fila de narrações (roteiro longo, audiobook, vários roteiros de uma vez): `voice_queue_add(text | file_path,
  voice, title, draft, format, language, speed, brand)` enfileira e `voice_queue_list()` mostra estado,
  capítulo e fala em andamento, porcentagem e tempo estimado restante. A fila roda um item por vez, sozinha,
  no `dmaker ui` aberto (seção Fila de narrações do painel Voz) ou em primeiro plano com `dmaker voice queue
  run`; se o processo cair, o item em andamento volta a pendente e retoma sem ressintetizar as falas que já
  estão em `cache/voice`. O roteiro vem de texto ou de arquivo `.txt`, `.md` ou `.docx`: linha com `# `,
  `Capítulo N` ou `Parte N` (no Markdown, `#` e `##`; no Word, estilo Título/Heading 1 ou 2) abre um
  capítulo. Cada item grava em `output/narracoes/<título>/`: `NN-<capítulo>.wav` (ou mp3), o
  `<título>-completo.wav` com 1,5 s de silêncio entre capítulos e o `.srt` do completo. O tempo estimado
  parte de ~1,4 s por caractere a 16 passos (~0,7 s no rascunho, ~0,2 s no Kokoro) e passa a usar a
  velocidade medida nas últimas falas desta máquina. CLI: `dmaker voice queue add|list|cancel|pause|resume|run`.
- Pronúncia: o modelo lê "DMaker" como "DeMaker"; o dicionário de pronúncia troca o termo por uma grafia
  que ele fala certo, só na hora de sintetizar (legendas, SRT e `cues` mantêm o texto escrito). Há um
  global (`assets/pronunciation.json`) e um por marca (`assets/brands/<marca>/pronunciation.json`), que
  vale por cima. Cada termo vale por idioma, porque a grafia feita para o português estraga a fala em
  inglês: `{"pt": {"DMaker": "Di Mêiker"}, "en": {"MedlyCare": "Medly Care"}}`. O formato antigo
  `{"termo": "pronúncia"}` solto na raiz continua valendo e conta como `pt`. `pt-BR` e `pt_br` são `pt`;
  sem entrada no idioma da fala, o termo é lido como está (em inglês, "DMaker" já sai certo). A dublagem
  usa a pronúncia do idioma de destino, e o glossário dela mantém os termos de todos os idiomas sem
  traduzir. Casa sem diferenciar maiúsculas, só palavra inteira, termo mais longo primeiro. Gerencie com a
  ferramenta `pronunciation(action=list|add|remove, term, spoken, brand, language)`,
  `dmaker voice lexicon list|add|remove [--brand] [--language]` ou a seção Pronúncia do painel Voz. Em `synthesize_speech`, `brand` escolhe a marca (sem ele vale a da voz; numa narração do
  projeto, a `brand` do projeto). Para uma só ocorrência, escreva no texto `[[termo|pronúncia]]` (fala a
  pronúncia, a legenda mostra o termo) ou `[[pronúncia]]`, em qualquer idioma. A pronúncia entra na chave do cache: mudar o
  dicionário ressintetiza só as falas afetadas.
- Qualidade, seguindo o VoiceStudio: `steps` 16 (padrão, o "balanced" dele), `draft=true` ou `steps` 8 para
  rascunho (o "fast" dele, mais áspero), `steps` 32 para o máximo. O DMaker fixa também `guidance_scale` 2.0,
  `denoise` e `postprocess_output` ligados, e `preprocess_prompt` ligado nas referências. O texto passa por
  limpeza de segurança (caracteres invisíveis, entidades HTML, pontuação repetida), frases com menos de 20
  caracteres juntam-se à seguinte e trechos vão até 800 caracteres antes de serem cortados. Cada fala sai
  com o silêncio das pontas aparado (-40 dBFS, 40 ms de margem) e a narração recebe o acabamento broadcast
  dele (highpass, compressor, EQ e limiter; `--raw` na CLI desliga). Não foram reproduzidos o refinamento
  por LLM e o ajuste de ritmo por slot: servem a ditado e dublagem, não a narração.
- Custo no OmniVoice: além do tempo por segundo de áudio, conte ~30 s para carregar o modelo e, em voz sem
  gravação, o preparo único da âncora. A referência é reprocessada a cada fala, então referências curtas
  (5 a 10 s) deixam tudo mais rápido. A quantização int8 do modelo acelera só ~20% e estraga a
  inteligibilidade, por isso não é usada. Cada fala fica em `cache/voice` (por motor, voz e parâmetros):
  refazer um roteiro com poucas mudanças só sintetiza o que mudou. Vozes por descrição ganham uma frase de
  âncora gerada uma vez, para o timbre não mudar entre as falas.
- CLI equivalente: `dmaker voice say "texto" --voice ID --out narracao.wav [--draft] [--steps 32]`.

### Isolamento vocal (voz x fundo)

Separa a fala da música e do ruído com o Demucs htdemucs (local, MIT), em dois arquivos: `voice` e
`background` (a soma de tudo que não é voz). Três caminhos:

- `isolate_vocals(path, start, end, out_dir, format)`: job em segundo plano (`job_status`); grava
  `<nome>_voz` e `<nome>_fundo` (wav ou mp3) em `out_dir` (padrão `output/isolamento`) e devolve os dois
  caminhos em `result.voice` e `result.background`. CLI: `dmaker audio isolate ARQUIVO [--start --end
  --out-dir --format wav|mp3]`.
- `audio_mode: "voice"` ou `"background"` num `clip`: o mezanino usa o stem no lugar do áudio da câmera.
- Custo na CPU deste projeto (4 núcleos físicos): conte de 3x a 6x a duração do trecho (medido com a CPU compartilhada) mais ~30 s para carregar o
  modelo na primeira vez. O resultado fica em `cache/stems` (por arquivo, trecho, modelo e versão):
  preview, render final e novas exportações do mesmo trecho não separam de novo. Para economizar, use
  `start`/`end` estreitos no clipe.
- Não é mágica: música muito alta, voz cantada ou várias pessoas falando ao mesmo tempo deixam resíduos de
  fundo na voz e pedaços de voz no fundo.

### Corrigir fala (regravar um trecho com a voz do próprio falante)

Troca uma palavra ou frase dita errado, sem gravar de novo: o DMaker acha o trecho pela transcrição, separa
a voz do fundo só em volta dele, clona a voz do falante a partir de outro pedaço do mesmo arquivo
(temporário: não entra na biblioteca, a menos que `save_voice` dê um nome), sintetiza o texto certo e emenda.
O arquivo mantém a duração, o vídeo é copiado sem recodificar e só a região trocada muda (o resto do áudio é
o original). Dublagem reaproveita estas peças (`SpeechFixService`).

- `speech_words(path, start, end)`: job que devolve as palavras com tempo (`dmaker voice words ARQUIVO
  [--start --end --words]`). Em vídeo longo, limite `start`/`end`: transcrever tudo leva tempo.
- `fix_speech(path, text, find | start+end, ...)`: job (`job_status`). `find` é o texto errado como foi dito
  (sem acento nem caixa; `occurrence` escolhe entre repetidas, e sem ele a repetição é erro); `start`/`end`
  apontam por tempo; `text` é o certo; `voice` usa uma voz da biblioteca no lugar do clone do falante;
  `expand=false` fala só o trecho (por padrão fala também as palavras vizinhas até o próximo fôlego, para a
  entonação ficar natural); `search_from`/`search_to` limitam a transcrição; `draft=true` usa 8 passos.
  CLI: `dmaker voice fix ARQUIVO (--find "errado" | --start S --end E) --text "certo" [--voice ID]
  [--no-expand] [--save-voice NOME] [--out]`. Saída padrão: `output/correcao/<nome>.corrigido.<ext>`.
- Duração: o texto novo cabe no trecho original (diferença de até 10% nas letras mantém a duração). Mais
  longo estica o trecho para dentro das pausas vizinhas (até meia pausa de cada lado, no máximo 0,5 s); se nem
  assim couber, a fala é comprimida (`squeezed`) e `duration_rule` avisa. O comprimento do arquivo nunca muda.
- A emenda cai no ponto mais quieto da pausa (crossfade de 30 ms) e o volume da fala nova é igualado ao do
  falante em volta. O dicionário de pronúncia vale (`[[termo|pronúncia]]` em `text`).
- Custo na CPU: ~20 s por segundo de fala sintetizada (o grupo de fôlego, 2 a 6 s) mais a separação da janela
  de 60 s em volta do trecho (3x a 6x, em cache) e a transcrição. Reparos próximos reaproveitam a separação.
- Na interface, aba Voz: seções "Isolar voz" e "Corrigir fala" (transcreve, clique na primeira e na última
  palavra, ouça original e corrigido, "Usar no projeto" troca o arquivo nos trechos).

### Trocar voz (a gravação inteira fala com outra voz da biblioteca)

Troca o timbre de quem fala por uma voz da biblioteca (clonada ou desenhada), mantendo as palavras, o ritmo,
as pausas, a entonação e o fundo. Não traduz (isso é a dublagem) nem refaz um trecho (isso é a correção): cada
quadro da fala original vira um quadro da fala nova, então a duração não muda. A voz é separada do fundo
(cache do isolamento), só a voz passa pelo modelo (OpenVoice V2, local, na CPU) e o fundo volta como estava.

- `convert_voice(path, voice, start, end, out)`: job (`job_status`). `voice` é o id de `list_voices`; `start`
  e `end` convertem só um trecho (bom para testar a voz em 20 a 30 s antes do arquivo todo). CLI: `dmaker voice
  convert ARQUIVO --voice ID [--start S --end E] [--out]`. Saída padrão:
  `output/troca-de-voz/<nome>.<voz>-<id>.<ext>`.
- O alvo é descrito por poucos segundos de fala: a gravação do clone, ou, para voz pronta ou desenhada, uma
  frase de ~8 s sintetizada uma vez e guardada em `cache/voice/convert-refs`.
- Arquivos longos são convertidos em blocos de ~25 s, cortados nos vales de silêncio, com 1 s de sobreposição e
  fade complementar na emenda. O volume da fala nova é igualado ao da original (no máximo 9 dB).
- Vídeo inteiro: a imagem passa sem recodificar. Trecho (`start`/`end`) de vídeo: recortado e recodificado.
- Limites: o motor muda o timbre, não o sotaque nem a melodia (a fala nova mantém o jeito de falar da original).
  Gravação com muita reverberação ou ruído sobra pior: use `isolate_vocals` para conferir a fala antes.
- Custo na CPU: ~1,5 a 2 s por segundo de fala, mais a separação (3x a 6x, em cache).
- Na interface, aba Voz: seção "Trocar voz" (arquivo do projeto ou enviado, voz, trecho opcional, ouvir
  original e voz trocada, baixar, "Usar no projeto" quando o arquivo inteiro foi convertido).

### Dublar (traduzir a fala e refazê-la com a voz clonada de quem fala)

Troca a fala de um vídeo ou áudio por outro idioma, mantendo música e ruído de fundo. É feito em dois passos
com a revisão no meio, e o roteiro vive num projeto editável `<nome>.<idioma>.dub.json` em `output/dublagem`.

1. **Preparar** (`dub_prepare`, ou `dmaker dub prepare ARQUIVO --to en [--from pt]`): separa voz e fundo
   (Demucs, em cache), transcreve a voz com tempo por palavra (Whisper), parte em frases de 1 a 12 s
   (pontuação, pausas de fôlego e tamanho), separa quem fala (diarização local, no modo `per_speaker`) e
   traduz com o Ollama local (modelo em `DMAKER_TRANSLATE_MODEL`,
   padrão `gpt-oss:20b`; sem o Ollama aberto o erro diz como abrir). A tradução recebe o roteiro inteiro em
   JSON para ter contexto, pede fala natural de tamanho parecido com o original e mantém intactos os termos
   do dicionário de pronúncia (marcas) e `glossary` (termos extras). Opções: `speaker_mode` (`per_speaker`,
   o padrão: separa quem fala e usa uma voz clonada por pessoa, montada do melhor trecho de 3 a 15 s só com a
   fala dela; com uma pessoa só vale como `single`. `per_segment`: cada frase clona a voz em volta dela, uma
   aproximação para vários falantes. `single`: um clone para o arquivo), `num_speakers` (força quantas pessoas
   falam; `--speakers N` na CLI; só no `per_speaker`), `voice` (voz da biblioteca no lugar do clone),
   `keep_original_db` (ex.: -18: voz original por baixo, estilo voice-over; sem ele só a dublada), `brand`
   (dicionário de pronúncia). A diarização roda na CPU, sem conta nem token (sherpa-onnx; os modelos baixam
   para `cache/models/diarization` na primeira vez), em cerca de 0,3x a duração do áudio; `DMAKER_DIARIZATION=off`
   a desliga (o padrão volta a ser `per_segment`).
2. **Revisar**: `dub_get(project)` lista as falas (`id`, tempo, `speaker`, `original`, `text`) e os `speakers`;
   `dub_update_segment(project, segment_id, text, locked, speaker)` corrige a tradução (aceita
   `[[termo|pronúncia]]`) e/ou troca quem fala ("Falante 2"): só aquela fala é sintetizada de novo; `locked=true`
   protege a fala de `dub_retranslate` (traduz de novo só as destravadas). O JSON também pode ser editado à mão.
3. **Gerar** (`dub_render`, ou `dmaker dub render PROJETO.dub.json [--out] [--draft]`): para cada fala usa a voz
   do falante dela (`per_speaker`), ou clona a janela de fala em volta dela, ou a vizinha se ela for curta
   (`per_segment`; usa o cache de clones da correção de fala),
   sintetiza a tradução no idioma alvo com a duração que cabe e monta fundo inteiro + falas dubladas nas
   posições originais (+ voz original atenuada) sobre o vídeo, copiado sem recodificar. Grava o vídeo
   (`output/dublagem/<nome>.<idioma>.<ext>`) e a legenda `.srt` no idioma alvo. `dmaker dub ARQUIVO --to en` faz
   os dois passos de uma vez.
4. **Trilhas separadas** (`dub_stems`, ou `dmaker dub stems PROJETO.dub.json [--zip]`, ou `dub render --stems`),
   para refazer a mixagem em outro editor: `voz-dublada.wav` (só as falas dubladas nas posições do vídeo),
   `fundo.wav` e `voz-original.wav` (isolada, sem atenuar), em `output/dublagem/<nome>.<idioma>.trilhas`. WAV
   16 bits, 48 kHz, estéreo, com a duração exata do vídeo e alinhados no zero, sem loudnorm nem limitador;
   somadas a voz dublada e o fundo reproduzem a mixagem do vídeo antes do acabamento. As falas vêm do cache.

Encaixe de duração (por fala): a duração natural da tradução é estimada pelo ritmo do falante original e pelas
letras de cada idioma. Se cabe, a fala dura isso; se passa, avança na pausa seguinte (até 1,2 s, deixando 0,15 s
de silêncio); se ainda passa, o modelo é pedido para falar mais rápido (até 1,25x) e o áudio pronto é acelerado
sem mudar o tom (`atempo`, até 1,15x); acima disso o fim da fala é cortado com fade e o resultado traz
`warnings` pedindo uma tradução mais curta. Cada fala tem `status` (`fits`, `advances`, `squeezed`,
`stretched`, `overflow`, `empty`) no relatório.

`fit_mode` (no projeto; `--fit` na CLI; `fit_mode` no `dub_prepare`, e no `dub_render` só para aquela geração)
troca o que fazer quando a tradução não cabe: `voz` (padrão, o encaixe acima), `video` (a voz fica na velocidade
natural e o vídeo estica, sem interpolar quadros, só na janela daquela fala, até 1,3x) e `misto` (a voz acelera
até 1,15x e o vídeo estica no que faltar). Só a fala que não coube estica; o fundo e a voz original atenuada
acompanham o vídeo (mesmo tom), as falas seguintes e a legenda `.srt` caem nos tempos novos, e o arquivo final
fica mais longo (`output_seconds`; `stretched` lista fala, fator e segundos a mais). Com trecho esticado a imagem
é recodificada (x264, CRF 18); sem ele continua copiada. Passou de 1,3x: o fim da fala é cortado e o resultado traz
`warnings`. Em áudio sem imagem o modo vale como `voz`.

Cache por fala: o áudio de cada fala sai do cache quando texto, voz, idioma, duração e passos são os mesmos,
então corrigir uma tradução e gerar de novo sintetiza só ela (`regenerated` no resultado). Custo na CPU: ~20 s
por segundo de fala sintetizada, mais a separação (3x a 6x a duração, uma vez) e a tradução (minutos com o
`gpt-oss:20b`). `draft=true` usa 8 passos. Na interface, aba Voz, seção "Dublar": escolher o arquivo, idiomas,
preparar, editar a tabela de falas (tempo, falante, original, tradução, travar), gerar com progresso "fala i de
n", comparar original e dublado, baixar vídeo, legenda e as trilhas separadas ("Baixar trilhas") e "Usar no projeto". Fora do escopo: sincronia labial.

### Narração no projeto

`audio.narration` põe a fala sintetizada como voz do vídeo, direto na spec, sem gerar o áudio antes. Cada
item tem `text` (ou `script`, um arquivo `.txt` relativo à pasta do projeto, nunca os dois), `voice` (id de
`assets/voices`; sem ele, voz automática), `instruct`, `start` (instante do vídeo, em segundos), `volume`
(0 a 4), `speed` (0.5 a 2), `language` (`pt`) e `seed` (fixa a síntese). A narração entra no barramento de
voz antes do ducking e da normalização: a música abaixa sob ela e o loudness final a conta. Em vídeo só de
cartões e imagens, ela é a voz (com `mute_clips` a música também abaixa sob a narração).

```json
{
  "timeline": [{"type": "card", "title": "Bem-vindo", "duration": 6}],
  "audio": {
    "music": {"src": "trilha.mp3"},
    "narration": [{"text": "Olá, este é o DMaker.", "voice": "ana", "start": 0.5, "seed": 1}]
  },
  "captions": {"source": "narration"}
}
```

- `captions.source: "narration"` usa o texto falado como legenda, com os tempos da própria síntese
  (sem Whisper, sem transcrever). Combina com `style.mode: "karaoke"`.
- Cada fala fica em `cache/voice`: só a primeira vez sintetiza (na CPU, dezenas de segundos por segundo de
  áudio); render de prévia e final reaproveitam. Mudar texto, voz, `speed` ou `seed` gera de novo só o que mudou.
- A vista da linha do tempo ganha a trilha `NAR` (um item por narração, duração estimada em ~14 caracteres
  por segundo até a síntese). O `validate_project` avisa se a voz não existe na biblioteca ou se a
  narração estimada passa do fim do vídeo; `render_project` avisa se a real passou.
- Com `dry_run` nada é sintetizado (usa a estimativa). Render parcial (`segments`) ignora a narração.

## Cartões por layout (brand.json)

Marcas com identidade visual própria (placa floral, fontes cursivas) podem definir cartões fixos no
`brand.json` em vez do visual genérico do tema: `{"type": "card", "layout": "abertura", "fields": {...},
"duration": 4}` (sem `title`; `layout` e `fields` são exclusivos com o cartão genérico). O brand.json
ganha uma seção `card_layouts`:

```json
"fonts": { "family": "Poppins", "files": { "script": "GreatVibes-Regular.ttf", "serif": "georgia.ttf" } },
"card_layouts": {
  "abertura": {
    "background": "cards/placa.png",
    "elements": [
      { "kind": "text", "text": "{{data}}", "font": "date", "size": 118, "y": 190, "color": "#1a1a1a", "shadow": true },
      { "kind": "lines", "field": "nomes", "font": "script", "size": 75, "y": 632, "x": 850, "line_gap": 88, "per_line": 2, "join": "   ·   " },
      { "kind": "blocks", "title_font": "serif", "text_font": "serif", "title_size": 52, "text_size": 38,
        "items": [ { "title": "Celebrante", "text": "{{celebrante}}" } ] },
      { "kind": "image", "src": "logo:paroquia", "width": 760, "x": 880, "y": 40, "blend": "multiply" }
    ]
  }
}
```

- `fonts.files`: papel de fonte (usado no `font` de cada elemento) -> arquivo `.ttf` em
  `assets/brands/<marca>/fonts/`; se não estiver lá, cai para a mesma fonte em `C:\Windows\Fonts`
  (útil para Georgia, Arial etc., sem precisar copiar).
- `background` e caminhos de `image` (fora de `logo:...`) são relativos à pasta da marca.
- Posições e tamanhos são px na base 1920x1080, escalados para a resolução do vídeo.
- `text`: interpola `{{campo}}` de `fields`; texto vazio depois de interpolar = elemento omitido.
  `x` é opcional (centro do quadro quando ausente); `shadow` desenha a sombra suave do cartão de
  referência da PASCOM (texto preto a 43%, deslocado (4,5), blur 4).
- `lines`: `field` é uma lista em `fields`, quebrada em linhas de `per_line` itens unidos por `join`;
  lista de 1 item usa `single_size`/`single_y` quando definidos (nome de casal único vs. vários).
- `blocks`: lista de `{"title", "text"}` (título + texto, `text` pode ter `\n`) empilhados e
  centralizados verticalmente; item com texto vazio (campo não preenchido) é omitido, sem deixar buraco.
- `image`: `src` é `logo:<nome>` (de `logos` do brand.json) ou caminho relativo à marca; `x`/`y` são o
  canto superior esquerdo (não o centro); `blend: "multiply"` escurece a placa clara com um logo de
  fundo branco (como na placa floral); `"alpha"` é a sobreposição transparente normal.
- Exemplo completo: marca `pascom-sjb` (`assets/brands/pascom-sjb/brand.json`), layouts `abertura`,
  `creditos` e `encerramento` do casamento comunitário da PASCOM (Paróquia São João Batista, Amparo-SP).

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
- Modelos de IA baixados (tamanho, licença, sobras): `models()` lista; `models("download", model_id)` baixa em
  segundo plano (`job_status`); `models("remove", model_id, confirm=true)` e `models("prune", confirm=true)`
  apagam, e só com `confirm=true` (sem ele o erro traz quais funções deixam de funcionar). Confira o espaço
  livre do disco que a listagem devolve antes de baixar os modelos grandes (OmniVoice ~3 GB).

## Depuração

- `dmaker render ... --dry-run` mostra os comandos ffmpeg. Grafos em `cache/jobs/<nome>/graph.pretty.txt`,
  o ASS (textos/legendas) em `overlay.ass`, comandos em `cmd.txt`.
- Erro do ffmpeg vem com as últimas linhas do stderr e o comando completo.
- `job_status(job_id)`/`list_jobs()` acompanham um render em segundo plano, local ou na interface.
- Testes: `.venv\Scripts\python -m pytest` (integração renderiza de verdade e leva uns 2 min).
