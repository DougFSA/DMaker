---
name: dmaker
description: Editor de vídeos curtos por comando (Instagram Reels/Stories/Feed, Facebook, YouTube Shorts/vídeo, TikTok, WhatsApp, LinkedIn). Use quando o usuário pedir para editar, cortar, legendar, adaptar formato ou montar um vídeo/reel/short/story, para o MedlyCare ou pessoal. Transforma o pedido em um spec JSON e renderiza com FFmpeg.
---

# DMaker: como operar o editor a partir de um pedido em linguagem natural

O DMaker fica em `D:\DMaker`. Rode sempre pelo venv do projeto:

```
D:\DMaker\.venv\Scripts\dmaker.exe <comando>
```

(ou `cd D:\DMaker` e `.venv\Scripts\dmaker.exe`). Se der "ffmpeg não encontrado", rode `dmaker setup`.

Se o servidor MCP `dmaker` estiver conectado na sessão, as mesmas operações existem como ferramentas (`probe_media`, `save_project`, `validate_project`, `render_project`, `contact_sheet`, `frames`...); `contact_sheet` e `frames` já devolvem as imagens para conferir.

## Fluxo de trabalho (sempre nessa ordem)

1. **Entender o pedido**: plataforma(s), duração alvo, fontes (vídeos/fotos/prints/música), se tem fala (legenda automática), se é MedlyCare (`"brand": "medlycare"`) ou pessoal (sem brand).
2. **Inspecionar as fontes**: `dmaker probe <arquivos>` (duração, tamanho, orientação, áudio). Nunca chute duração.
3. **Escrever a spec** em `D:\DMaker\projects\<nome>\spec.json` (ou `dmaker new <nome> --preset ... --src ...` para começar). Nome em kebab-case.
4. **Validar**: `dmaker validate projects/<nome>/spec.json` (duração final, avisos de limite da plataforma, regra do travessão).
5. **Preview rápido**: `dmaker render projects/<nome>/spec.json --preview` (540px, segundos). Depois **olhar o resultado**: `dmaker sheet <preview.mp4>` gera uma grade de quadros; `dmaker frames <mp4> 2 7 12` extrai quadros; abra as imagens com a ferramenta Read para conferir posição de texto, legibilidade, enquadramento. Com `--guides` as zonas cobertas pela interface aparecem em vermelho.
6. **Ajustar e repetir** até ficar bom. Só então **render final**: `dmaker render projects/<nome>/spec.json`. Saída em `D:\DMaker\output\<nome>__<preset>.mp4` (+ `.jpg` de thumbnail).
7. **Outros formatos** do mesmo projeto: `dmaker export projects/<nome>/spec.json instagram/reels youtube/shorts facebook/reels`.
8. Entregar ao usuário o caminho do mp4 e, se útil, mandar o arquivo (SendUserFile) ou um quadro.

Legendas automáticas geram `projects/<nome>/captions.auto.json` e `.srt`. Se o usuário quiser corrigir uma palavra, edite o JSON (texto das `words`) e renderize de novo: o cache de transcrição é reaproveitado enquanto as fontes não mudarem. `--force` refaz tudo.

## Presets (`dmaker presets`)

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

## Spec JSON (referência resumida)

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

- **Tempos em segundos.** `transition` de um trecho é a entrada dele (vindo do anterior); tipos: `cut`, `fade`, `dissolve`, `wipeleft/right/up/down`, `slideleft/right/up/down`, `smoothleft`, `circleopen`, `zoomin`, `fadeblack`, `fadewhite`, `pixelize`... (nomes do xfade). Transição consome tempo: duração final = soma dos trechos menos as transições (`validate` mostra).
- **Trechos**: `clip` (vídeo; `start`/`end` no arquivo fonte, `speed` 0.25 a 8, `volume`, `mute`, `fade_in/out`), `image` (foto/print; `duration`, `motion`: none, zoom-in, zoom-out, pan-left, pan-right, `motion_amount` 0.04 a 0.15 fica elegante; o movimento é sub-pixel com easing, sem tremor), `card` (cartão gerado no visual do tema: `title`, `subtitle`, `variant` light/dark, `logo`).
- **reframe.mode**: `auto` (recomendado: corta se a proporção for parecida; se for muito diferente, usa `brand` quando há marca ou `blur`), `crop` (preenche e corta; `focus` [x, y] de 0 a 1 diz onde está o assunto), `pad` (barras, `pad_color`), `blur` (fundo desfocado), `brand` (fonte inteira sobre fundo gerado com o visual do tema, com sombra; imagens ganham cantos redondos), `stretch`. Vídeo horizontal de pessoa falando para reels: `crop` com `focus` no rosto. Print de tela/produto: `brand`.
- **color**: `brightness` (-1..1), `contrast`, `saturation`, `gamma`, `sharpen`, `denoise`, `vignette`, `lut` (.cube), `extra` (filtro ffmpeg cru).
- **Sobreposições de texto** (`role`): `hook` (gancho grande no topo, animação pop), `title`, `subtitle` (texto de apoio; `position` top/center/bottom), `cta` (pílula na cor da marca, slide-up), `lower-third` (nome + `secondary`, barra de destaque), `custom`. Sobre cartões e fundo `brand` o texto muda sozinho para a cor da marca (fundo claro) ou branco (fundo escuro). `style` sobrescreve tudo: `size` (px na base 1080), `color`, `outline`, `box`, `box_color`, `uppercase`, `align`, `max_width`, `font`, `weight`. `animation`: fade, pop, slide-up, typewriter, none. `x`/`y` (0..1) forçam posição.
- **Sobreposição de imagem**: `src` = `logo` (lockup horizontal), `logo:symbol`, `logo:horizontal_dark`, `logo:symbol_dark` ou caminho de PNG. `position`, `width` (fração da largura), `opacity`, `start`/`end`, `fade`.
- **progress-bar**: barra de progresso fina na base (cor accent do tema).
- **captions**: `source` = `auto` (transcreve com Whisper; modelo `small` é o padrão, `medium` é mais preciso e mais lento) ou caminho `.srt`/`.json`. `style.mode`: `karaoke` (palavra a palavra, padrão reels), `classic`, `boxed`. `max_words`/`max_chars` por linha, `uppercase`, `size`, `y`, `pop` (aumenta a palavra ativa; desligado por padrão porque desloca a linha). `vocabulary` e `replacements` corrigem nomes próprios (o tema MedlyCare já traz os seus).
- **audio**: `music` (`volume` 0.1 a 0.3 costuma bastar, `ducking` abaixa a música quando há voz, `loop`, `fade_in/out`, `start_at`), `voice_gain`, `normalize` (`two-pass` = -14 LUFS, padrão para redes; `fast`; `off`), `mute_clips`.
- **output**: `preset`, `quality` (high/medium/draft), `encoder` (x264 padrão; `qsv`/`nvenc`/`amf` se `dmaker doctor` mostrar disponível), `fps`, `thumbnail_at`, `path`.
- Caminhos relativos resolvem a partir da pasta da spec. Prefira caminhos absolutos com `/`.

## Regras da marca MedlyCare (quando `"brand": "medlycare"`)

- Fonte Poppins, cores: teal escuro `#0C535A` (primary), verde `#75B9A2` (accent), menta `#B2E1CF`. Logos em `assets/brands/medlycare/`.
- **Nunca travessão (—) nem meia-risca (–)** em texto na tela: usar vírgula, ponto, dois-pontos. `validate` avisa.
- Tom: abre pela dor do profissional, frases curtas, sem superlativo vazio, sem prometer o que o produto não faz. Só anunciar o que está em produção (ver skill `medlycare-marketing`). CTA sempre `medlycare.com.br`; oferta atual: teste de 3 meses sem cartão.
- Ritmo típico de reel de produto (15 a 30 s): cartão de abertura com a dor (3 s) → 2 a 4 telas do produto em `brand` com legenda de seção (3 a 4 s cada) → cartão escuro de CTA (4 s). Gancho nos 3 primeiros segundos.
- Prints reais do produto: `C:\Users\Douglas Vasconcelos\Desktop\MedlyCare\Marketing\Prints do Produto\` (1000x620). Identidade visual: `...\Desktop\MedlyCare\Identidade Visual\`.

## Vídeos pessoais (sem brand)

Tema padrão: fundo escuro, destaque amarelo nas legendas, Poppins. Para vídeo de celular vertical em reels use `reframe.mode: crop`. Para vídeo horizontal (câmera/drone) em reels, `crop` com `focus` no assunto ou `blur`. Para YouTube longo, `youtube/video` com `quality: high`; use `lower-third` para nomes e `title` para capítulos.

## Receitas rápidas

- Um vídeo só, corte e formato: `dmaker quick video.mp4 --preset reels --start 3 --end 33 --captions --hook "texto" --cta "medlycare.com.br" --brand medlycare`.
- Só transcrever: `dmaker captions video.mp4 --lang pt --model small` (gera .srt e .json).
- Capa: `dmaker thumbnail saida.mp4 --at 2.5`.
- Cartão avulso para ver o design: `dmaker card "Título" --subtitle "sub" --brand medlycare --preset reels`.
- Limpar cache: `dmaker clean`.

## Depuração

- `dmaker render ... --dry-run` mostra os comandos ffmpeg. Os grafos ficam em `cache/jobs/<nome>/graph.pretty.txt`, o ASS (textos/legendas) em `overlay.ass`, comandos em `cmd.txt`.
- Erro do ffmpeg vem com as últimas linhas do stderr e o comando completo.
- Testes: `.venv\Scripts\python -m pytest` (integração renderiza de verdade e leva ~1 min).
