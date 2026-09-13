# DMaker

Editor de vídeos curtos **por comando**: você descreve a edição (para o Claude ou direto num JSON), o DMaker monta e renderiza no formato certo de cada plataforma: Instagram (Reels, Stories, Feed), Facebook (Reels, Stories, Feed), YouTube (Shorts, vídeo 1080p/4K), TikTok, WhatsApp Status e LinkedIn.

Base open source: [FFmpeg](https://ffmpeg.org) (corte, transições, áudio, codificação), [libass](https://github.com/libass/libass) (texto e legendas animadas), [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (legendas automáticas, roda local) e [Pillow](https://python-pillow.org) (cartões e fundos gerados). Tudo fica dentro desta pasta: FFmpeg em `bin/`, fontes em `assets/`, modelos e cache em `cache/`, renders em `output/`.

## O que ele faz

- Corta, junta e acelera trechos; transições (fade, wipe, slide, zoom...) entre eles.
- Reenquadra para qualquer formato: corte com ponto de foco, barras, fundo desfocado ou **fundo da marca** com sombra e cantos redondos (ótimo para prints de tela).
- Cartões de abertura/encerramento gerados no visual da marca (MedlyCare: blobs, rede, brilhos, Poppins, lockup).
- Texto na tela com papéis prontos: gancho, título, apoio, CTA em pílula, lower-third, com animações (pop, fade, slide, máquina de escrever). Zonas cobertas pela interface de cada app são respeitadas.
- **Legendas automáticas** em português com destaque palavra a palavra (estilo Reels), a partir de transcrição local; ou de um `.srt`.
- Trilha sonora com **ducking** (abaixa quando há voz) e normalização de loudness em duas passadas (-14 LUFS, padrão das redes).
- Logo/marca d'água, barra de progresso, fotos com movimento (Ken Burns).
- **Picture-in-picture**: webcam ou segunda câmera sobre o vídeo, em retângulo, cantos redondos ou círculo, com borda, sombra e entrada deslizando (como o Size & Position + Crop Circle do Shotcut). Ideal para mostrar o sistema e aparecer ao mesmo tempo.
- Codificação otimizada por plataforma (H.264 High, faststart, bitrate máximo por formato), preview rápido em baixa resolução, cache de trechos para reedições em segundos.

## Instalação (passo a passo)

O DMaker roda no Windows e não instala nada fora da própria pasta. Você vai precisar de:

1. **Python 3.11 ou mais novo.** Abra o PowerShell e digite `py --version`. Se não aparecer uma versão, instale em <https://www.python.org/downloads/> marcando a opção *Add python.exe to PATH*.
2. **Git** (só para baixar o projeto): <https://git-scm.com/download/win>. Alternativa: baixe o ZIP do repositório no GitHub e descompacte.
3. **Internet na primeira vez**: o instalador baixa o FFmpeg (~110 MB) e a fonte Poppins. O modelo de legendas (~470 MB) só é baixado no primeiro uso das legendas automáticas.

Depois, no PowerShell:

```powershell
# 1. baixe o projeto (ou descompacte o ZIP) numa pasta, por exemplo D:\DMaker
git clone https://github.com/DougFSA/DMaker.git D:\DMaker
cd D:\DMaker

# 2. rode o instalador: cria o ambiente Python, instala as dependências, baixa FFmpeg e fontes
.\scripts\setup.ps1

# 3. confira se está tudo certo
.\.venv\Scripts\dmaker.exe doctor
```

O `doctor` mostra a versão do FFmpeg, se o libass está presente (texto e legendas), fontes, marcas, se o faster-whisper e o MCP estão instalados e qual encoder de hardware existe na máquina. Se o PowerShell bloquear o script (`execution policy`), rode antes: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

Dica: para não digitar `.\.venv\Scripts\dmaker.exe` toda vez, ative o ambiente com `.\.venv\Scripts\Activate.ps1`; a partir daí basta `dmaker`.

## Interface gráfica (o jeito mais fácil de usar)

```powershell
cd D:\DMaker
.\.venv\Scripts\dmaker.exe ui
```

O navegador abre em <http://127.0.0.1:8765> (se não abrir, cole o endereço). Deixe a janela do PowerShell aberta enquanto usa; `Ctrl+C` encerra. Na interface você:

1. Cria um projeto em **Novo projeto**: nome, formato (Reels, Shorts, YouTube...), marca e os vídeos/fotos, escolhidos no navegador de arquivos.
2. Edita na aba **Editor**: cada trecho da linha do tempo é um cartão (vídeo, imagem ou cartão de texto) com corte, velocidade, transição e enquadramento; abaixo, sobreposições (gancho, CTA, logo, barra de progresso), legendas e áudio. A aba **JSON** mostra a mesma coisa como texto, para quem prefere.
3. Clica em **Validar** para ver duração final e avisos, e em **Preview** para gerar uma versão rápida em baixa resolução. O painel **Andamento** mostra cada etapa e a barra de progresso em tempo real; ao terminar, o vídeo aparece na aba **Preview** para assistir, com grade de quadros e captura de quadro.
4. Quando estiver bom, **Render final** (qualidade de entrega) e, se quiser outros formatos, **Exportar**. Os arquivos ficam em `D:\DMaker\output`.
5. Se o projeto tem legendas automáticas, a aba **Legendas** deixa corrigir palavras; gere o preview de novo para ver.

## Uso

```powershell
.\.venv\Scripts\dmaker.exe presets                                # formatos disponíveis
.\.venv\Scripts\dmaker.exe probe video.mp4 foto.jpg                # informações das fontes
.\.venv\Scripts\dmaker.exe new meu-reel --preset instagram/reels --src a.mp4 b.mp4 --brand medlycare
.\.venv\Scripts\dmaker.exe validate projects\meu-reel\spec.json
.\.venv\Scripts\dmaker.exe render projects\meu-reel\spec.json --preview   # rápido, para conferir
.\.venv\Scripts\dmaker.exe sheet output\meu-reel__instagram-reels__preview.mp4   # grade de quadros
.\.venv\Scripts\dmaker.exe render projects\meu-reel\spec.json             # final
.\.venv\Scripts\dmaker.exe export projects\meu-reel\spec.json youtube/shorts facebook/reels
```

Edição rápida de um único vídeo, sem escrever spec:

```powershell
.\.venv\Scripts\dmaker.exe quick video.mp4 --preset reels --start 3 --end 33 --captions --logo --brand medlycare --hook "Chega de agenda no papel" --cta "medlycare.com.br"
```

Outros: `ui` (interface gráfica), `mcp` (servidor para IAs), `sync` (sincronizar câmeras pelo áudio), `captions` (só transcrever), `thumbnail`, `frames`, `card`, `clean`, `setup`, `doctor`.

## Falando com o editor

Numa sessão do Claude Code em `D:\DMaker` (ou com a skill `dmaker` instalada), basta pedir:

> "Faz um reel de 30 s desse vídeo, legenda automática, logo do MedlyCare no canto, gancho 'Chega de agenda no papel' e CTA no final. Depois exporta para Shorts."

O Claude inspeciona as fontes, escreve a spec em `projects/<nome>/spec.json`, valida, gera um preview, confere os quadros e renderiza a versão final. O manual completo desse fluxo está em [`.claude/skills/dmaker/SKILL.md`](.claude/skills/dmaker/SKILL.md), com a referência da spec.

## Servidor MCP (qualquer IA)

O DMaker expõe tudo isso como ferramentas MCP, então Claude Desktop, Claude Code, Cursor, Windsurf ou qualquer cliente MCP pode operar o editor:

```powershell
.\.venv\Scripts\dmaker.exe mcp        # servidor por stdio
```

Configuração para o cliente (o projeto já traz `.mcp.json` para o Claude Code; para o Claude Desktop, adicione em `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "dmaker": { "command": "D:\\DMaker\\.venv\\Scripts\\dmaker.exe", "args": ["mcp"] }
  }
}
```

Ferramentas: `dmaker_guide` (manual), `spec_schema`, `presets`, `brands`, `probe_media`, `save_project`, `get_project`, `validate_project`, `list_projects`, `render_project` (com `job_id` para renders longos), `export_project`, `job_status`, `quick_edit`, `transcribe_media`, `read_captions`, `fix_captions`, `contact_sheet` e `frames` (devolvem **imagens**, para a IA ver o resultado), `render_card_preview`, `clean_cache`. Recursos `dmaker://guide` e `dmaker://schema`; prompt `editar-video`.

## Vídeos longos, multicâmera e áudio externo

Para um casamento ou evento com duas ou três câmeras e um gravador, declare as fontes e deixe o DMaker sincronizar pelo áudio:

```json
{
  "name": "casamento",
  "output": { "preset": "youtube/video" },
  "sources": {
    "cam1": { "src": "D:/casamento/cam1.mp4" },
    "cam2": { "src": "D:/casamento/cam2.mp4", "sync": "auto" },
    "gravador": { "src": "D:/casamento/altar.wav", "sync": "auto" }
  },
  "timeline": [
    { "type": "clip", "source": "cam1", "start": 120, "end": 150 },
    { "type": "clip", "source": "cam2", "start": 150, "end": 200, "transition": { "type": "cut" } }
  ],
  "audio": { "tracks": [{ "source": "gravador" }] }
}
```

- `sync: "auto"` descobre, por correlação de áudio, em que instante do relógio da câmera principal cada fonte começa (precisão de milissegundos, funciona em horas de gravação). O resultado fica em `sync.json` no projeto. `dmaker sync cam1.mp4 cam2.mp4 altar.wav` mostra os valores e a confiança.
- Clipes com `source` usam **tempos da sessão** (o relógio da câmera principal), então cortar entre câmeras é só trocar o nome da fonte: os pontos de entrada em cada arquivo são calculados.
- `audio.tracks` são faixas externas que seguem os cortes e são misturadas ao áudio das câmeras (ajuste o da câmera com `volume` ou `mute` no clipe).
- Para revisar um trecho de um vídeo longo sem renderizar tudo: `dmaker render spec.json --preview --segments 12-20`.
- Picture-in-picture (tela + webcam): sobreposição `{"type": "video", "source": "webcam", "shape": "circle", "position": "bottom-right", "width": 0.18, "border": 6}`; exemplo em [`templates/tutorial-tela-webcam.json`](templates/tutorial-tela-webcam.json).
- Exemplo completo: [`templates/casamento-multicam.json`](templates/casamento-multicam.json). Tempo estimado: cerca de 2x a duração do vídeo em 1080p (mezaninos + render final).

## Estrutura da spec (resumo)

```json
{
  "name": "meu-reel",
  "output": { "preset": "instagram/reels" },
  "brand": "medlycare",
  "timeline": [
    { "type": "card", "title": "Sua agenda em um clique", "duration": 3 },
    { "type": "clip", "src": "D:/videos/take1.mp4", "start": 2, "end": 14, "transition": { "type": "fade", "duration": 0.5 } },
    { "type": "image", "src": "print.png", "duration": 4, "motion": "zoom-in" }
  ],
  "overlays": [
    { "type": "image", "src": "logo:symbol", "position": "top-right", "width": 0.11 },
    { "type": "text", "text": "Chega de agenda no papel", "role": "hook", "start": 3, "end": 7 },
    { "type": "text", "text": "medlycare.com.br", "role": "cta", "start": 14, "end": 18 },
    { "type": "progress-bar" }
  ],
  "captions": { "source": "auto", "language": "pt" },
  "audio": { "music": { "src": "trilha.mp3", "volume": 0.18, "ducking": true }, "normalize": "two-pass" }
}
```

Exemplos completos em [`templates/`](templates/). Marcas em `assets/brands/<nome>/brand.json` (cores, fonte, logos, vocabulário para o Whisper, regras de texto).

## Estrutura do projeto

```
DMaker/
  src/dmaker/
    domain/       spec (modelo Pydantic), presets, brand, timeline (contas puras)
    media/        ffmpeg (comando + runner injetável), probe, fonts
    text/         ass, overlays (texto e legendas), captions (cues/SRT), transcribe (Whisper)
    visuals/      cards, motion (Ken Burns sub-pixel), reframe_image, geometry
    filtergraph/  grafos ffmpeg como funções puras (reframe, timeline, overlays, audio, encode, mezzanine)
    pipeline/     etapas do render (sources, segments, captions, textlayer, assembly, renderer), serviços (projects, jobs, qa)
    ui/           API FastAPI + página estática (interface gráfica)
    cli.py        adaptador Typer        mcp_server.py   adaptador MCP
  tests/          unitários (funções puras, pipeline com ffmpeg/Whisper falsos), integração (ffmpeg real), MCP (stdio)
  assets/         fonts/ (Poppins, OFL) e brands/medlycare/ (brand.json + logos)
  templates/      specs de exemplo
  projects/       seus projetos: <nome>/spec.json (+ captions.auto.json/.srt gerados)
  output/         renders finais e thumbnails (ignorado pelo git)
  cache/          mezaninos, grafos, modelos do Whisper (ignorado pelo git)
  bin/ffmpeg/     FFmpeg baixado pelo setup (ignorado pelo git)
  scripts/setup.ps1  bootstrap
```

## Como funciona por dentro

1. Cada trecho vira um **mezanino** (intermediário já no tamanho/fps de saída), guardado em `cache/mez` com chave por conteúdo. Vídeo: corte, velocidade, enquadramento e cor no FFmpeg. Imagens e cartões: reenquadramento no Pillow e **movimento de câmera calculado em ponto flutuante**, quadro a quadro, com easing e reamostragem LANCZOS (o `zoompan` do FFmpeg recorta em pixels inteiros e faz a imagem tremer; há um teste numérico que garante movimento monotônico e suave). Os quadros entram no ffmpeg pelo stdin.
2. A **montagem** concatena os mezaninos (`concat`/`xfade`/`acrossfade`), aplica sobreposições de imagem, queima um ASS com todo o texto (títulos, legendas, barra de progresso), mistura a música com `sidechaincompress` e normaliza com `loudnorm` (medição em passada separada; silêncio é detectado e pulado).
3. Codifica no preset da plataforma (libx264 `slow`, CRF 18, `maxrate` por formato, AAC 48 kHz, `+faststart`) e extrai a thumbnail.

As dependências externas (ffmpeg, Whisper, probe) entram por protocolo e injeção, então o pipeline inteiro roda em testes sem ffmpeg. Padrões de código em [`CLAUDE.md`](CLAUDE.md).

## Limites conhecidos

- Whisper roda na CPU por padrão (`captions.device: "cpu"`); com GPU NVIDIA e CUDA instalado, use `"cuda"`.
- Os limites de duração por plataforma são avisos (as redes mudam esses números).
- Renders finais em 1080x1920 levam ~1 a 2 min por 20 s de vídeo com x264 `slow`; use `--preview` para iterar.
- Fontes de baixa resolução (prints de 1000 px) perdem nitidez em 1080p; o `validate` avisa.
- Encoders de hardware (QSV/NVENC/AMF) são detectados por `dmaker doctor` e usados com `"encoder": "auto"`. O padrão x264 `medium` é o de melhor qualidade (medido: QSV da UHD 620 perde ~7 dB de PSNR); `"quality": "max"` usa x264 `slow`. Placas GeForce MX (130/150/250) não têm NVENC.
