# Manual do DMaker

Manual completo de uso do DMaker: editor de vídeos curtos por comando, para quem opera pela IA, por um
modelo local, pela interface gráfica ou pela linha de comando. Este documento é a referência de uso; as
regras de desenvolvimento do próprio DMaker ficam em [`CLAUDE.md`](../CLAUDE.md).

## Sumário

1. [O que é o DMaker](#1-o-que-é-o-dmaker)
2. [Instalação passo a passo no Windows](#2-instalação-passo-a-passo-no-windows)
3. [Conceitos](#3-conceitos)
4. [Usando com o Claude (Claude Code)](#4-usando-com-o-claude-claude-code)
5. [Usando com LLM local (Ollama)](#5-usando-com-llm-local-ollama)
6. [Usando manualmente pela interface gráfica](#6-usando-manualmente-pela-interface-gráfica)
7. [Usando manualmente pela linha de comando](#7-usando-manualmente-pela-linha-de-comando)
8. [Marca MedlyCare](#8-marca-medlycare)
9. [Solução de problemas](#9-solução-de-problemas)
10. [Anexos](#10-anexos)

---

## 1. O que é o DMaker

O DMaker é um editor de vídeos curtos que funciona por comando: em vez de arrastar clipes numa linha do
tempo do início ao fim, você descreve a edição (para uma IA ou direto num arquivo JSON, a "spec") e o
DMaker monta e renderiza o vídeo pronto para a plataforma certa: Instagram (Reels, Stories, Feed),
Facebook (Reels, Stories, Feed), YouTube (Shorts e vídeo longo, 1080p ou 4K), TikTok, WhatsApp Status e
LinkedIn.

Por baixo, ele usa só ferramentas abertas: [FFmpeg](https://ffmpeg.org) corta, junta e codifica;
[libass](https://github.com/libass/libass) desenha texto e legendas animadas; o
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) transcreve a fala localmente, sem mandar
nada para a internet; o [Pillow](https://python-pillow.org) gera os cartões e fundos. Tudo fica dentro
da própria pasta do projeto (`D:\DMaker`): nada é instalado no sistema.

### Três formas de usar

| Forma | Como | Quem usa |
| --- | --- | --- |
| Pela IA (Claude Code) | Abre uma sessão do Claude na pasta `D:\DMaker` e descreve o pedido em português | Quem quer só descrever o vídeo e receber o arquivo pronto, sem aprender a spec |
| Por um LLM local (Ollama) | `dmaker agent`, um modelo pequeno rodando na própria máquina | Tarefas mecânicas repetidas (template, render, QA, legendas) sem depender de uma sessão de IA em nuvem |
| Manual, pela interface gráfica | `dmaker ui`, um editor no navegador | Quem prefere ver a linha do tempo, arrastar arquivos e mexer nos campos visualmente |
| Manual, pela linha de comando | `dmaker <comando>` no PowerShell | Quem quer automatizar, integrar em scripts ou tem controle fino sobre cada opção |

### Qual usar quando

| Situação | Melhor caminho |
| --- | --- |
| "Faz um reel desse vídeo com legenda e o logo" (não sabe o que é spec) | Claude Code (seção 4) |
| Corte fino, ritmo específico, decidir qual câmera aparece quando | Claude Code ou interface gráfica (decisão de edição é sempre humana ou de uma IA maior) |
| Casamento ou evento padrão da PASCOM, já com o template pronto | `dmaker agent` (seção 5) ou Claude Code |
| Renderizar de novo, exportar para outro formato, corrigir uma legenda | Qualquer um: `dmaker agent`, interface ou CLI, é tarefa mecânica |
| Ajustar um campo visualmente, ver a linha do tempo, organizar a tela do seu jeito | Interface gráfica (seção 6) |
| Escrever a spec inteira na mão, rodar em lote, integrar com outro script | Linha de comando (seção 7) |
| Ligar outra ferramenta de IA (Cursor, Windsurf, Claude Desktop) ao DMaker | Servidor MCP (`dmaker mcp`, seção 4) |

O que o DMaker faz sozinho: cortar, encadear e acelerar trechos com transições; reenquadrar qualquer
vídeo ou imagem para o formato certo (corte com foco, barras, fundo desfocado ou fundo da marca);
cartões de abertura e encerramento no visual do tema; texto na tela com papéis prontos (gancho, título,
apoio, CTA, nome e cargo); legendas automáticas em português, palavra a palavra; trilha sonora com
ducking (abaixa quando há voz) e normalização de loudness; logo, barra de progresso e movimento de
câmera em fotos (Ken Burns); picture-in-picture (webcam ou segunda câmera); troca de fundo sem chroma
key (recorte de pessoa por rede neural); sincronização de múltiplas câmeras e gravadores pelo áudio.

O que continua sendo decisão humana (ou de uma IA maior como o Claude): escolher os cortes, o ritmo de
troca entre trechos, qual câmera aparece em cada momento e quais tomadas usar. Isso está detalhado na
seção 4.

---

## 2. Instalação passo a passo no Windows

### 2.1 Pré-requisitos

1. **Python 3.11 ou mais novo** (o projeto atual usa 3.13). Abra o PowerShell e digite:

   ```powershell
   py --version
   ```

   Se não aparecer uma versão, instale em <https://www.python.org/downloads/>, marcando a opção
   **Add python.exe to PATH** durante a instalação.

2. **Git**, só para baixar o projeto: <https://git-scm.com/download/win>. Sem Git, dá para baixar o
   ZIP do repositório no GitHub e descompactar na pasta desejada.

3. **Internet na primeira vez**: o instalador baixa o FFmpeg (cerca de 110 MB) e a fonte Poppins. O
   modelo de legendas automáticas (cerca de 470 MB) só é baixado no primeiro uso das legendas, e o
   modelo de recorte de pessoa (RVM, 15 a 100 MB conforme o modelo) no `setup` ou no primeiro uso do
   `matte`.

### 2.2 Baixar e instalar

```powershell
# 1. baixe o projeto (ou descompacte o ZIP) numa pasta, por exemplo D:\DMaker
git clone https://github.com/DougFSA/DMaker.git D:\DMaker
cd D:\DMaker

# 2. rode o instalador: cria o ambiente Python, instala as dependências, baixa FFmpeg e fontes
.\scripts\setup.ps1

# 3. confira se está tudo certo
.\.venv\Scripts\dmaker.exe doctor
```

O script `scripts/setup.ps1` faz, nessa ordem: cria `.venv` (com `py -3 -m venv .venv`, ou `python -m
venv .venv` se `py` não existir), instala o pacote em modo editável com os extras de desenvolvimento e
legendas (`pip install -e ".[dev,captions]"`), roda `dmaker setup` (baixa FFmpeg e Poppins) e por fim
`dmaker doctor` para mostrar o diagnóstico.

Se o PowerShell recusar rodar o script (mensagem sobre política de execução, `execution policy`), rode
antes, uma vez só:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

`dmaker doctor` confere e mostra: versão do FFmpeg e se o libass está presente (sem ele, texto e
legendas não funcionam); os filtros necessários (`xfade`, `acrossfade`, `loudnorm`,
`sidechaincompress`, `ass`, `tile`, `lut3d`); os encoders de hardware disponíveis (NVENC, AMF, QSV) e
qual seria usado com `"encoder": "auto"`; as fontes Poppins, Bahnschrift e Arial; as marcas instaladas
em `assets/brands/`; se o `faster-whisper` (legendas automáticas) e o `mcp` (servidor para IAs) estão
instalados; e onde ficam as pastas de cache, saída e projetos.

Dica: para não digitar `.\.venv\Scripts\dmaker.exe` toda vez, ative o ambiente uma vez por sessão do
PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

A partir daí basta `dmaker <comando>`. **Nunca use o Python global** nem um `dmaker` instalado fora
desse ambiente virtual: o projeto só funciona com as dependências de `.venv`.

### 2.3 Onde fica cada coisa

| Pasta | Conteúdo | No controle de versão? |
| --- | --- | --- |
| `bin/ffmpeg/` | FFmpeg e ffprobe baixados pelo `setup` | Não (ignorado pelo git) |
| `assets/fonts/` | Fonte Poppins (licença OFL) | Sim |
| `assets/brands/<nome>/` | `brand.json` de cada marca (cores, fontes, logos, vocabulário) | Sim |
| `cache/mez/` | Mezaninos (trechos já processados), com chave por conteúdo | Não |
| `cache/proxy/` | Proxies 540p para a prévia ao vivo na interface | Não |
| `cache/waveform/` | Formas de onda calculadas para as faixas de áudio | Não |
| `cache/jobs/<job>/` | Grafo do ffmpeg, ASS gerado, comandos, áudio de transcrição de cada render | Não |
| `cache/models/` | Modelos baixados (OmniVoice, Kokoro, Demucs, Whisper, RVM); veja e gerencie com `dmaker models list` ou a aba Modelos | Não |
| `projects/<nome>/` | `spec.json` de cada projeto, mais `captions.auto.json`/`.srt` e `sync.json` gerados | Sim (spec), gerados não |
| `output/` | Vídeos renderizados (finais e preview) e thumbnails | Não |
| `templates/*.json` | Specs de exemplo parametrizadas | Sim |
| `layouts.json` (raiz) | Layouts salvos da interface (dados de quem usa, não do projeto) | Não |

### 2.4 Atualizar

```powershell
cd D:\DMaker
git pull
.\scripts\setup.ps1
```

Rodar o `setup.ps1` de novo é seguro: ele só recria o que faltar e reinstala as dependências do
`pyproject.toml`. Use `dmaker setup --force` isoladamente se quiser forçar o download do FFmpeg e das
fontes de novo (por exemplo, depois de uma atualização de versão do FFmpeg).

---

## 3. Conceitos

### 3.1 Projeto e spec.json

Um **projeto** é uma pasta em `projects/<nome>/` com um arquivo `spec.json`: a descrição completa do
vídeo (fontes, cortes, sobreposições, legendas, áudio, formato de saída). Tudo no DMaker gira em torno
dessa spec: criar um projeto é gerar esse arquivo (na mão, por template ou por uma IA); validar,
renderizar e exportar leem esse arquivo; editar pela interface ou por uma operação pontual (`edit_project`)
grava de volta nele. A spec é validada por um modelo Pydantic (`Project`, em
`src/dmaker/domain/spec.py`): um campo desconhecido ou um valor do tipo errado é rejeitado na hora, com
uma mensagem dizendo o quê.

Exemplo mínimo:

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
    { "type": "progress-bar" }
  ],
  "captions": { "source": "auto", "language": "pt" },
  "audio": { "music": { "src": "trilha.mp3", "volume": 0.18, "ducking": true }, "normalize": "two-pass" }
}
```

A referência completa de todos os campos está na seção 7.3 (resumo) e no recurso `dmaker://guide`
(ferramenta MCP `dmaker_guide`), que é a fonte de verdade para escrever uma spec na mão.

### 3.2 Presets (plataformas)

Um **preset** define o formato de saída: tamanho de tela, taxa de quadros, limite de duração da
plataforma e a zona segura (a área que a interface de cada rede cobre com legenda, avatar ou botões,
onde o DMaker evita colocar texto importante). `dmaker presets` lista todos com os números exatos; o
resumo:

| id | tamanho | limite | uso |
| --- | --- | --- | --- |
| `instagram/reels` | 1080x1920 | 180 s | reels (padrão para vertical) |
| `instagram/stories` | 1080x1920 | 60 s | stories |
| `instagram/feed-portrait` | 1080x1350 | 90 s | post 4:5 |
| `instagram/feed-square` | 1080x1080 | 90 s | post 1:1 |
| `instagram/feed-landscape` | 1080x608 | 90 s | post horizontal |
| `facebook/reels` | 1080x1920 | 90 s | reels no Facebook |
| `facebook/stories` | 1080x1920 | 20 s | stories no Facebook |
| `facebook/feed-portrait`, `feed-square`, `feed-landscape` | conforme a proporção | sem limite prático | posts e anúncios |
| `youtube/shorts` | 1080x1920 | 180 s | shorts |
| `youtube/video` | 1920x1080 | sem limite | vídeo longo |
| `youtube/video-4k` | 3840x2160 | sem limite | vídeo longo em 4K |
| `tiktok/video` | 1080x1920 | 600 s | TikTok |
| `whatsapp/status` | 1080x1920 | 30 s | status do WhatsApp |
| `linkedin/feed-square`, `linkedin/feed-landscape` | 1080x1080 / 1920x1080 | 600 s | posts no LinkedIn |

Atalhos de nome aceitos onde um preset é pedido: `reels`, `stories`, `shorts`, `youtube`, `feed`,
`square`, `tiktok`, `status`, `linkedin`.

### 3.3 Marca (brand)

Uma **marca** (`"brand": "medlycare"` na spec) aplica automaticamente cores, fonte, logos e regras de
texto de um `assets/brands/<nome>/brand.json`, sem precisar escrever esses valores à mão em cada
projeto. Existem três marcas instaladas: `default` (tema neutro, fundo escuro, destaque amarelo nas
legendas), `medlycare` (ver seção 8) e `pascom-sjb` (identidade da paróquia, com cartões de layout fixo
para casamentos, ver seção 3.9). `dmaker doctor` lista as marcas instaladas; a ferramenta MCP `brands`
devolve cores, fonte, logos e regras de cada uma.

### 3.4 Trechos (timeline)

A `timeline` é a lista, em ordem, do que aparece no vídeo. Três tipos:

- **`clip`**: um trecho de vídeo, com `src` (arquivo) ou `source` (fonte de uma sessão multicâmera) e
  `start`/`end` em segundos, `speed`, `volume`, reenquadramento e cor.
- **`image`**: uma foto ou print, com `duration` e `motion` (Ken Burns: `zoom-in`, `zoom-out`,
  `pan-left`, `pan-right`).
- **`card`**: um cartão gerado no visual da marca (título, subtítulo, variante clara ou escura), ou,
  para marcas com `card_layouts` próprio (como a `pascom-sjb`), um layout fixo por nome.

Cada trecho pode ter uma `transition` de entrada (como ele chega, vindo do trecho anterior: `cut`,
`fade`, `dissolve`, `wipeleft/right/up/down`, `slideleft/right/up/down`, `zoomin`, `circleopen` etc.,
nomes do `xfade` do FFmpeg, mais as de movimento do DMaker: `crosszoom` (zoom de passagem), `whippan`
(chicote com borrão), `blurslide` (desfoque deslizando), `filmburn` (queima de filme) e `lightleak`
(vazamento de luz)), reenquadramento (`reframe`, ver seção 7.3) e ajuste de cor. A `transition` aceita
ainda uma `curve` (`linear`, `ease` ou `spring`) que muda o ritmo da troca: a mola corre, passa um pouco
do ponto e assenta. Para ver o que cada transição faz, rode `dmaker transitions list` e
`dmaker transitions sheet <nome>` (folha de contato em `output/transitions`), ou abra a tela
**Transições** da interface nova.

### 3.5 Sobreposições (overlays)

Ficam por cima da timeline principal, com seu próprio intervalo de tempo (`start`/`end`):

- **texto**, com um `role` que já define aparência e posição: `hook` (gancho grande no topo), `title`,
  `subtitle`, `cta` (pílula na cor da marca), `lower-third` (nome e cargo), `custom`;
- **imagem**, para logo (`src: "logo"`/`"logo:symbol"`) ou qualquer PNG;
- **vídeo** (picture-in-picture): uma segunda fonte de vídeo sobre a linha do tempo, em retângulo,
  cantos redondos ou círculo, com borda e sombra;
- **barra de progresso** (`progress-bar`), fina, na cor de destaque do tema.

### 3.6 Legendas automáticas

`captions.source: "auto"` transcreve a fala com Whisper (local, sem enviar nada para fora da máquina) e
gera `projects/<nome>/captions.auto.json` (com a confiança de cada palavra) e um `.srt`. O estilo padrão
é `karaoke`: destaque palavra a palavra, como nos Reels. O modo `rounded` põe uma caixa de fundo arredondada atrás de cada linha, no estilo do TikTok, sem perder o destaque da palavra ativa; os textos sobrepostos pedem o mesmo desenho com `box_shape: "rounded"`, e o raio e a margem da caixa vêm da marca. `captions.vocabulary` e `.replacements`
corrigem nomes próprios e termos técnicos que o Whisper costuma errar (a marca já traz os seus, que se
somam aos do projeto). Alternativa: apontar `captions.source` para um `.srt` já pronto.

### 3.7 Áudio: música, faixas externas e normalização

`audio.music` toca uma trilha de fundo, com `ducking` (abaixa quando detecta voz) e `volume` (0.1 a 0.3
costuma bastar). `audio.tracks` são faixas externas (um gravador de mesa de som, por exemplo) que seguem
os cortes da timeline e se misturam ao áudio dos clipes. `audio.normalize: "two-pass"` (padrão) mede e
ajusta o loudness para -14 LUFS em duas passadas, o alvo comum das redes sociais.

### 3.8 Fontes de sessão e multicâmera

Para eventos com mais de uma câmera ou um gravador separado, `sources` declara cada fonte do mesmo
evento; `sync: "auto"` descobre, por correlação de áudio, em que instante do relógio da câmera principal
cada uma começa. Clipes com `source` (em vez de `src`) usam esse tempo comum da sessão: trocar de câmera
é só trocar o nome da fonte. Câmeras que gravam em vários arquivos (a Canon corta a cada 30 minutos, por
exemplo) usam `parts` (a lista dos arquivos, em ordem) em vez de `src`; o pipeline encadeia as partes
pelo áudio sozinho. Detalhes e exemplos completos na seção 7.6.

### 3.9 Cartões por layout de marca

Uma marca com identidade visual própria (como a `pascom-sjb`, placa floral e fontes cursivas) pode
definir cartões fixos no `brand.json` em vez do cartão genérico do tema: campos `layout` e `fields` em
vez de `title`/`subtitle`. É o mecanismo por trás dos cartões de abertura, créditos e encerramento do
template `casamento-pascom`. Referência completa (elementos `text`, `lines`, `blocks`, `image`) no
`dmaker://guide`.

### 3.10 Proxies

Vídeos em formatos que o navegador não decodifica nativamente (HEVC, ProRes, alguns MOV de câmera)
tocam na prévia da interface por um **proxy**: uma cópia leve, 540p em H.264, gerada em segundo plano em
`cache/proxy/` só para a prévia, sem afetar o render final (que sempre lê o arquivo original). O comando
`dmaker proxies <projeto>` gera os proxies faltantes e mostra o status de cada fonte.

### 3.11 Cache

O DMaker guarda resultados intermediários para reeditar rápido: **mezaninos** (`cache/mez/`, um trecho
já cortado, reenquadrado e codificado no tamanho final, por hash de conteúdo: mudar um campo que não
afeta aquele trecho não invalida o cache), proxies e formas de onda (seção 3.10 e 6.4), e por job
(`cache/jobs/<job>/`) o grafo de filtros, o ASS gerado e os comandos usados naquele render, para
depuração. `dmaker clean` limpa mezaninos, proxies e formas de onda; `dmaker clean --jobs` limpa também
o histórico de jobs.

### 3.12 Jobs

Um **job** é um render ou exportação rodando (ou já terminado) em segundo plano, com progresso e log por
etapa. Pela CLI, pelo MCP ou pela própria interface, todo job aparece na interface gráfica (ela sobe
sozinha se não estiver aberta); `job_status`/`list_jobs` (MCP) ou o painel **Jobs** da barra lateral
acompanham. Ver seção 3.13 e a tabela de comandos MCP na seção 4.

### 3.13 Saídas

Os vídeos renderizados (finais e prévias) e as thumbnails ficam em `output/`, nomeados
`<projeto>__<preset>.mp4` (final) ou `<projeto>__<preset>__preview.mp4` (prévia). A aba **Saídas** da
barra lateral da interface lista todos, com tamanho e o botão para abrir a pasta.

---

## 4. Usando com o Claude (Claude Code)

### 4.1 Por que abrir a sessão em `D:\DMaker`

O Claude Code lê automaticamente três coisas quando a sessão está na pasta do projeto: o `CLAUDE.md`
(convenções do projeto), a skill `dmaker` em `.claude/skills/dmaker/SKILL.md` (o roteiro de como operar
o editor a partir de um pedido) e o `.mcp.json` (que liga o servidor MCP do DMaker às ferramentas do
Claude). Fora dessa pasta, nada disso carrega sozinho: o Claude não vai saber que o DMaker existe nem
como chamá-lo.

### 4.2 Como pedir

Basta descrever o que você quer, em português, como pediria a um editor de vídeo humano:

> "Faz um reel de 30 s desse vídeo, legenda automática, logo do MedlyCare no canto, gancho 'Chega de
> agenda no papel' e CTA no final. Depois exporta para Shorts."

Ou pelo comando de barra `/dmaker` seguido do pedido, se a skill estiver configurada como slash command
no seu Claude Code.

### 4.3 O que a IA faz por baixo

Sempre nessa ordem (é o fluxo descrito na skill `dmaker`):

1. **Entende o pedido**: plataforma, duração alvo, fontes de vídeo/foto/música, se tem fala (legenda),
   se é MedlyCare ou pessoal.
2. **Olha os templates disponíveis** (`list_templates`): a maioria dos pedidos já cabe num template
   pronto (produto, depoimento, stories, vlog, tutorial, casamento).
3. **Cria o projeto**: de preferência com `new_from_template` (template + parâmetros); sem um template
   que sirva, inspeciona as fontes com `probe_media` (nunca chuta duração ou resolução) e escreve a spec
   na mão com `save_project`.
4. **Valida** (`validate_project`): duração final, avisos de limite de plataforma e de regra da marca.
5. **Gera um preview** (`render_project` com `preview=true`): a interface gráfica abre sozinha para você
   acompanhar o progresso.
6. **Confere com QA** (`qa_report`): checagens automáticas em texto (zona segura, ritmo de leitura,
   contraste, sobreposições, legendas). Só olha imagem (`contact_sheet`/`frames`, que custam tokens)
   se o relatório apontar algo ou você pedir para ver.
7. **Corrige o que precisar** (`edit_project` para cortar, mover, aparar, duplicar ou mudar um campo;
   `fix_captions` para uma palavra errada na legenda) e repete a partir do passo 5.
8. **Render final** (`render_project`) e, se você pedir outros formatos, **exporta**
   (`export_project`). Entrega o caminho do arquivo `.mp4`.

### 4.4 Exemplos de pedidos bons

- "Reel de produto do MedlyCare com esses 3 prints da agenda, título 'Sua agenda organizada em um
  clique' e CTA de teste grátis."
- "Depoimento desse vídeo da Dra. Helena: corta os primeiros 5 segundos de silêncio, gancho 'Chega de
  perder paciente por falta de retorno', legenda automática."
- "Story rápido: esse print de fundo, pergunta 'Chegou sem hora marcada?' no topo e o texto da fila de
  espera embaixo."
- "Vlog pessoal com esses 4 vídeos da viagem, em sequência, título 'Fim de semana em Ubatuba' e essa
  trilha."
- "Tutorial: essa gravação de tela com a webcam em círculo no canto inferior direito, título 'Como
  montar a agenda no MedlyCare'."
- "Casamento com as duas câmeras dessa pasta: monta o corte automático da cerimônia inteira e depois eu
  reviso."

### 4.5 Como acompanhar

Por padrão, **todo render** (pela IA, pela CLI ou pela própria interface) aparece na interface gráfica:
se ela não estiver aberta, sobe sozinha em segundo plano e o navegador abre direto no projeto e no job,
com a barra de progresso e a etapa em execução. Isso vale tanto para o Claude Code quanto para o
`dmaker agent` (seção 5). Peça para não abrir (`show_ui=false`) só se você realmente não quiser ver.

### 4.6 Como pedir ajustes

Depois de ver o preview, ajustes pontuais também são um pedido em português:

- "Corta o trecho 2 em 5 segundos" (vira um `split`).
- "Troca a música por essa outra." (`set_field` em `audio.music.src`).
- "Tira o travessão dessa legenda." (`fix_captions`, ou corrigir o texto na spec).
- "Aumenta o logo um pouco." (`set_field` em `overlays.N.width`).

A IA usa `timeline_view` para achar o índice e o tempo certos antes de aplicar a operação, então não é
preciso saber o formato interno da spec para pedir o ajuste.

### 4.7 O que continua sendo decisão humana ou da IA

O software não decide sozinho cortes, ritmo (quando cada trecho troca) ou qual câmera aparece em cada
momento: isso é trabalho de edição, não do DMaker. A exceção é o corte automático de cerimônia
(`multicam` + `plan_multicam`, seção 3.8 e 7.6): ele dá um ritmo plausível por fase reconhecida na fala,
mas o ajuste fino (por exemplo, qual casal fica de frente para qual câmera) ainda é feito com
`edit_project` depois de conferir o resultado.

### 4.8 Dicas de economia de tokens

- Prefira `new_from_template` a escrever a spec inteira: o template já cobre validação e formato.
- Rode `qa_report` antes de `contact_sheet`/`frames`: as duas últimas devolvem imagens (caras em
  tokens) e só valem a pena quando o relatório de texto apontar um problema específico.
- `read_captions`/`transcribe_media` têm um modo compacto por padrão (resumo mais só as legendas
  suspeitas): use `mode="full"`/`full=true` apenas quando precisar mesmo do texto inteiro, palavra por
  palavra.
- Deixe o `dmaker agent` (seção 5) cuidar de renders repetidos e exportações depois que o corte já
  estiver aprovado, para não gastar uma sessão de IA maior em tarefa mecânica.

### 4.9 MCP em outras ferramentas

O DMaker expõe tudo isso como um servidor MCP por stdio, então qualquer cliente MCP pode operar o editor
(Claude Desktop, Cursor, Windsurf, ou outra sessão de Claude Code). Subir o servidor manualmente:

```powershell
.\.venv\Scripts\dmaker.exe mcp
```

O projeto já traz `.mcp.json` configurado para o Claude Code. Para o Claude Desktop, adicione em
`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "dmaker": { "command": "D:\\DMaker\\.venv\\Scripts\\dmaker.exe", "args": ["mcp"] }
  }
}
```

### 4.10 Ferramentas MCP

| Ferramenta | O que faz |
| --- | --- |
| `dmaker_guide` | Manual completo (spec, presets, multicâmera, picture-in-picture, receitas). Leia primeiro. |
| `spec_schema` | JSON Schema da spec de projeto. |
| `presets` | Formatos de saída por plataforma, com zona segura e limite de duração. |
| `brands` | Marcas disponíveis, com cores, fonte, logos e regras. |
| `probe_media` | Duração, tamanho, fps, áudio e orientação de arquivos. |
| `save_project` | Valida e salva uma spec inteira em `projects/<nome>/spec.json`. |
| `list_templates` | Templates disponíveis com os parâmetros de cada um. |
| `new_from_template` | Cria um projeto a partir de um template e parâmetros (caminho preferido). |
| `get_project` | Lê a spec de um projeto existente. |
| `validate_project` | Confere arquivos, calcula a duração final e lista avisos. |
| `edit_project` | Aplica uma edição pontual (cortar, mover, aparar, duplicar, mudar um campo). |
| `timeline_view` | Vista multitrilha da linha do tempo, com índices e tempos já calculados. |
| `plan_multicam` | Planeja o corte automático de um bloco `multicam` (transcreve, reconhece fases, monta os clipes). |
| `autocut`, `list_cuts`, `undo_cut` | Cortam pausas, vícios e frases repetidas de uma gravação falada (projeto novo com a lista do que saiu), listam os cortes e devolvem um deles ao projeto. |
| `validate_batch`, `run_batch`, `resume_batch`, `pause_batch`, `batch_status` | Lote: vários vídeos de uma planilha (CSV, XLSX ou JSON), um por linha, sobre um modelo. Validam a planilha antes de renderizar, rodam num job, pausam, retomam sem refazer o que já saiu e devolvem o relatório do que saiu e do que falhou. |
| `list_projects` | Projetos existentes em `projects/`. |
| `render_project` | Renderiza (prévia ou final); abre a interface para acompanhar por padrão. |
| `export_project` | Exporta o mesmo projeto para vários presets de uma vez. |
| `job_status` / `list_jobs` | Situação de um render em segundo plano, local ou na interface. |
| `quick_edit` | Edição rápida de um único vídeo, sem escrever spec. |
| `sync_sources` | Descobre pelo áudio o deslocamento de cada câmera/gravador em relação à principal. |
| `transcribe_media` | Transcreve um vídeo ou áudio isolado (fora de um projeto). |
| `read_captions` | Lê as legendas automáticas de um projeto (resumo por padrão). |
| `fix_captions` | Corrige palavras erradas nas legendas automáticas. |
| `contact_sheet` | Grade de quadros do vídeo inteiro numa imagem (custa tokens de imagem). |
| `qa_report` | Relatório de QA em texto (zona segura, ritmo, contraste, legendas, e a saída renderizada). |
| `frames` | Quadros em instantes específicos, como imagens (custa tokens de imagem). |
| `render_card_preview` | Gera um cartão isolado para aprovar o design antes do render. |
| `clean_cache` | Limpa o cache de trechos intermediários. |

Recursos: `dmaker://guide` (o mesmo manual de `dmaker_guide`) e `dmaker://schema` (o mesmo JSON Schema
de `spec_schema`). Prompt: `editar-video`, um roteiro pronto para transformar um pedido em um render.

---

## 5. Usando com LLM local (Ollama)

Para tarefas mecânicas (criar projeto por template, renderizar, ler o relatório de QA, corrigir
legendas, exportar) dá para usar um modelo pequeno rodando na própria máquina, sem depender de nenhuma
sessão de IA em nuvem: `dmaker agent` liga um modelo do [Ollama](https://ollama.com) às ferramentas do
servidor MCP.

### 5.1 Requisitos

- [Ollama](https://ollama.com) instalado e no ar (`ollama serve`, ou o aplicativo do Ollama aberto).
- O modelo baixado:

  ```powershell
  ollama pull gpt-oss:20b
  ```

- 16 GB ou mais de RAM livres. Sem GPU, a inferência roda na CPU e é lenta: minutos por resposta num
  pedido que envolve várias chamadas de ferramenta.

### 5.2 Como usar

```powershell
.\.venv\Scripts\dmaker.exe agent                                          # conversa no terminal
.\.venv\Scripts\dmaker.exe agent --once "liste os templates disponíveis"  # um pedido só, sem abrir o chat
.\.venv\Scripts\dmaker.exe agent --model gpt-oss:20b --url http://127.0.0.1:11434 --num-ctx 16384
```

Opções: `--model` (padrão `gpt-oss:20b`), `--url` (endereço do servidor Ollama; padrão a variável
`DMAKER_OLLAMA_URL` ou `http://127.0.0.1:11434`), `--num-ctx` (tamanho do contexto em tokens, padrão
16384), `--timeout` (espera máxima por resposta, padrão 1800 s, generoso porque um modelo de 20b em CPU
demora), `--once` (executa um único pedido e sai, sem entrar no modo de conversa).

No modo de conversa: `/sair` encerra, `/limpar` reinicia o histórico (a conversa some, mas nada que já
foi salvo em disco é desfeito), `/ferramentas` lista as ferramentas que o agente pode usar. Cada chamada
de ferramenta aparece numa linha discreta (`-> render_project(...)`) com o resultado resumido logo
abaixo, para acompanhar o que ele está fazendo.

### 5.3 O que funciona bem

Criar projeto a partir de um template, validar, renderizar (prévia e final), ler `qa_report`, corrigir
legendas com `fix_captions` e exportar. Também funciona o casamento padrão da PASCOM: o template
`casamento-pascom` (duas pastas de câmera, nomes dos casais e data) seguido de `plan_multicam`, que
transcreve a câmera do altar, reconhece as fases do rito pela fala e monta o corte alternando as
câmeras.

### 5.4 O que não funciona bem (deixe para o Claude ou uma pessoa)

Decidir cortes e ritmo na mão, escolher qual câmera fica de frente para qual pessoa, escrever uma spec
do zero e aplicar as regras finas de texto da marca: o agente local não tem julgamento para essas
decisões, e o conjunto de ferramentas liberado para ele nem inclui operações de multicâmera manual ou
picture-in-picture (só o caminho automático via `plan_multicam`).

### 5.5 Ferramentas disponíveis ao agente

O agente local usa um subconjunto curado das ferramentas do servidor MCP (`AGENT_TOOLS`, em
`src/dmaker/agent/tools.py`), pensado para caber num modelo pequeno e não abrir espaço para operações
que exigem mais julgamento:

```
list_templates, new_from_template, plan_multicam, list_projects, get_project, validate_project,
render_project, export_project, qa_report, edit_project, timeline_view, read_captions, fix_captions,
probe_media, presets, brands, job_status
```

Fora desse conjunto (cortes finos na mão, picture-in-picture, edição de marca): trabalho para o Claude
Code ou para uma pessoa.

### 5.6 Limites de velocidade em CPU

Sem GPU, cada resposta do modelo (mesmo só decidindo qual ferramenta chamar) pode levar de dezenas de
segundos a minutos, e um pedido com várias etapas (criar projeto, validar, renderizar) soma esse tempo a
cada chamada. Para tarefas com prazo curto ou muitas iterações de ajuste fino, prefira o Claude Code.

---

## 6. Usando manualmente pela interface gráfica

### 6.1 Abrir

```powershell
cd D:\DMaker
.\.venv\Scripts\dmaker.exe ui
```

Abre em <http://127.0.0.1:8765> (a porta muda com `--port`; `--no-browser` não abre o navegador
sozinho). Deixe a janela do PowerShell aberta enquanto usa: `Ctrl+C` encerra o servidor.

### 6.2 Tour pela tela

**Barra superior**: nome do projeto aberto (com um indicador **não salvo** quando há mudanças
pendentes), o seletor **Tela** (layouts, seção 6.9), os botões **Salvar**, **Validar**, o campo **Só os
trechos** (de/até, para um render parcial), **Preview**, **Render final** e **Exportar**.

**Barra lateral**, com três seções:

- **Projetos**: botão **Novo projeto** (abre o modal de criação, seção 6.3) e a lista dos projetos
  existentes, com preset, marca e número de trechos; clicar num nome abre esse projeto.
- **Jobs**: os renders em andamento ou recentes, com progresso; **Limpar concluídos** remove da lista
  os já terminados (feitos ou com erro).
- **Saídas**: os arquivos já renderizados, com formato, se é prévia ou final, e o tamanho em MB.

**Abas do centro**: **Linha do tempo** (o editor multitrilha, aberto por padrão), **Propriedades** (os
mesmos campos em formulário), **JSON** (a spec como texto puro), **Preview** (assistir ao resultado
renderizado, QA e extração de quadros) e **Legendas** (corrigir o texto das legendas automáticas).

### 6.3 Criar um projeto

No modal **Novo projeto**: **Nome**, **Template** (a lista de `templates/*.json`, ou "Do zero, escolher
arquivos" para um projeto sem template), **Preset** e **Marca**, o botão **Escolher arquivos...** para
as fontes de vídeo/imagem, e as caixas **Gerar legendas automáticas** e **Incluir logo**. **Criar**
grava a spec e abre o projeto na aba Linha do tempo.

### 6.4 Linha do tempo

Um editor multitrilha no estilo Shotcut: um player em cima e as trilhas embaixo (arraste a alça entre os
dois para redimensionar). De cima para baixo:

| Trilha | Conteúdo |
| --- | --- |
| `V2`, `V3`... | Sobreposições de vídeo (picture-in-picture) |
| `TX` | Sobreposições de texto |
| `GR` | Sobreposições de imagem e a barra de progresso |
| `V1` | Os trechos principais: vídeo, imagem ou cartão |
| `A1` | Áudio de cada trecho da `V1` |
| `A2`... | Faixas de áudio externas sincronizadas |
| `MUS` | Música de fundo |
| `CC` | Legendas |

Clique ou arraste na régua para mover o cursor; clique num item para selecionar (`Ctrl` para selecionar
vários); arraste o meio de um item para mover (reordena na `V1`, desloca no tempo nas sobreposições) e
as bordas para aparar, com encaixe (snap) nas bordas de outros itens.

A barra de ferramentas da linha do tempo tem: **Cortar no cursor**, **Remover** (com ripple), **Lift**
(remove sem deixar lacuna na `V1`), **Duplicar**, **Aparar entrada até o cursor**, **Aparar saída até o
cursor**, **Snap** (alternar encaixe), o indicador de que a `V1` é sempre ripple, os botões de zoom
(**Afastar**, **Aproximar**, **Ajustar à janela**), o timecode do cursor, **Mostrar/ocultar filtros**,
**Mostrar/ocultar mídia** e **Mostrar atalhos** (`?`). Cortar, mover, aparar, duplicar e remover são
"ripple": a `V1` nunca fica com buracos.

**Player**: mostra uma prévia ao vivo aproximada, sem precisar renderizar: toca o trecho sob o cursor,
as sobreposições de texto e imagem, e o picture-in-picture, mas **não mostra** transições, Ken Burns,
legendas nem correção de cor (isso só sai no render). Vídeos em formatos que o navegador não decodifica
(HEVC, ProRes...) tocam por um proxy leve gerado em segundo plano (seção 3.10); enquanto o proxy não
fica pronto, aparece um aviso na barra de ferramentas. As trilhas de áudio (`A1`, `A2`..., `MUS` e os
PiPs com som) mostram a forma de onda, calculada e guardada em cache na primeira vez que cada arquivo
aparece na linha do tempo.

**Painéis laterais ocultáveis** (botões `F`/`M` na barra de ferramentas, ou o `×` na barra de título de
cada painel; o estado é lembrado entre sessões):

- **Filtros** (esquerda): os grupos de campos do item selecionado (ou do projeto, se nada estiver
  selecionado) que já saem do padrão, prontos para editar. O botão **+** lista os grupos ainda não
  aplicados (reenquadrar, cor, velocidade, transição, posição, forma, estilo do texto...) por tipo de
  item; **Remover** num grupo devolve os campos ao padrão. Edição em campo de texto/número tem um
  pequeno atraso antes de salvar; select e checkbox aplicam na hora. A tabela 6.5 resume os grupos por
  tipo de item.
- **Mídia** (direita): as fontes sincronizadas e os arquivos já usados na linha do tempo, com miniatura
  e duração. Arraste um item para a `V1` para inserir um trecho na posição solta, ou para uma trilha de
  vídeo acima da `V1`/`TX`/`GR` para criar uma sobreposição (picture-in-picture ou imagem) começando
  naquele instante; duplo clique acrescenta no fim da `V1`. Os botões **Texto**, **Cartão**, **Logo** e
  **Música** criam cada um no cursor (cartão vai para o fim da `V1`; música substitui a música de fundo
  do projeto).

### 6.5 Painel Filtros: grupos por tipo de item

| Tipo de item | Grupos disponíveis |
| --- | --- |
| Clipe (`clip`) | Reenquadrar, Cor, Velocidade, Áudio, Fade, Transição de entrada, Rótulo |
| Imagem (`image`) | Reenquadrar, Cor, Movimento, Duração, Fade, Transição de entrada, Rótulo |
| Cartão (`card`) | Movimento, Duração, Texto, Estilo, Fade, Transição de entrada, Rótulo |
| Vídeo, PiP (`video`) | Tempo, Posição, Tamanho, Forma, Opacidade, Animação, Áudio |
| Texto (`text`) | Texto, Tempo, Posição, Animação, Estilo |
| Imagem, sobreposição (`image-overlay`) | Origem, Tempo, Posição, Tamanho, Opacidade/Fade |
| Barra de progresso (`progress-bar`) | Barra de progresso (cor, altura, posição, opacidade da trilha) |
| Faixa de áudio (`track`) | Faixa de áudio (volume) |
| Música (`music`) | Música (arquivo, volume, início, loop, ducking), Fade |
| Legendas (`captions`) | Legendas (origem, idioma, modelo, dispositivo, deslocamento), Estilo |
| Projeto (nada selecionado) | Saída (preset, qualidade, encoder, fps, guias), Áudio geral (ganho de voz, normalização, LUFS alvo, silenciar clipes) |

### 6.6 Player de prévia: o que mostra e o que só aparece no render

| Aparece na prévia ao vivo | Só aparece no render |
| --- | --- |
| Corte, ordem e duração dos trechos | Transições (fade, wipe, slide...) |
| Sobreposições de texto e imagem | Movimento de câmera (Ken Burns) em fotos e cartões |
| Picture-in-picture (posição, forma, borda) | Legendas automáticas |
| Áudio dos clipes, música e faixas externas | Correção de cor, matting (troca de fundo) |
| Proxy 540p para vídeos que o navegador não decodifica | Codificação final, thumbnail |

### 6.7 Mudo, oculto e bloqueio por trilha

Como no Shotcut, o cabeçalho de cada trilha tem: `M` (mudo, nas trilhas de áudio: `A1`, `A2`...,
`MUS`), `H` (ocultar, em `V2`, `V3`..., `TX`, `GR` e `CC`; a `V1` não pode ser ocultada, é a linha do
tempo principal) e um cadeado (bloqueia seleção e arraste dos itens da trilha, em qualquer uma). O
estado fica salvo na spec (campo `tracks`, por id de trilha) e vale tanto para a prévia ao vivo quanto
para o **render final**: uma trilha muda ou oculta na interface não aparece no vídeo exportado. O
bloqueio só existe na interface, o render ignora.

### 6.8 Propriedades e JSON

A aba **Propriedades** tem os campos "clássicos" em formulário: **Saída** (preset, qualidade, encoder),
**Fontes sincronizadas (multicâmera)** (adicionar fonte, sincronizar), **Linha do tempo** (adicionar
trecho: clipe, imagem, cartão), **Sobreposições** (adicionar: texto, imagem, vídeo/PiP, barra de
progresso), **Legendas** e **Áudio**. A aba **JSON** mostra a mesma spec como texto puro, para quem
prefere editar direto (com **Aplicar** para validar e salvar).

### 6.9 Legendas (editor)

Com legendas automáticas geradas, a aba **Legendas** mostra uma tabela (Início, Fim, Texto) para
corrigir palavra por palavra; **Salvar legendas** grava a correção. Gere o preview de novo depois de
salvar para ver o texto corrigido no vídeo.

### 6.10 Preview, Render e Exportar

**Validar** mostra a duração final e os avisos (limite de plataforma, regra de marca, fontes ausentes).
**Preview** gera uma versão rápida em baixa resolução para conferir corte e texto de verdade (com
transições e legendas, ao contrário da prévia ao vivo do player). O painel **Andamento** mostra cada
etapa do render e a barra de progresso em tempo real; ao terminar, o vídeo aparece na aba **Preview**
para assistir, com:

- **Relatório de QA**: as mesmas checagens em texto da seção 4.3, direto na interface.
- **Grade de quadros**: uma grade com vários instantes do vídeo, para revisar de uma vez.
- **Quadro em t=** + **Gerar**: extrai um quadro isolado num instante específico.
- **Abrir pasta**: abre `output/` no explorador de arquivos.

**Render final** gera a versão de entrega (qualidade completa); **Exportar** roda o mesmo projeto para
outros presets de uma vez (por exemplo, Reels e Shorts a partir da mesma spec).

### 6.11 Organização da tela

Como no menu **Layout** do Shotcut:

- **Arrastar**: segure a barra de título de um painel (Player, Filtros, Linha do tempo ou Mídia) e
  solte sobre outro para trocar os dois de lugar.
- **Redimensionar**: arraste os divisores entre o player e a linha do tempo, entre os painéis laterais
  e o centro, ou entre a barra lateral e o resto da tela.
- **Ocultar**: o `×` na barra de título de cada painel oculta e mostra (os atalhos `F`/`M` continuam
  valendo para Filtros/Mídia).
- **Trocar de layout**: o seletor **Tela**, na barra superior, tem os layouts embutidos (tabela abaixo)
  e os que você salvar. **Salvar layout como...** guarda a organização atual com um nome; **Excluir
  layout atual** remove um layout salvo (layouts embutidos não podem ser excluídos); **Restaurar
  padrão** volta para Edição.

| Layout embutido | O que muda |
| --- | --- |
| Edição (padrão) | Disposição normal: Player, Filtros, Linha do tempo e Mídia nos quatro cantos; Andamento recolhido |
| Efeitos | Painel de Filtros mais largo; Mídia e Andamento ocultos |
| Áudio | Linha do topo (player) mais baixa, para dar espaço às faixas de áudio |
| Player | Linha do topo (player) bem mais alta |
| Revisão | Linha do topo baixa e o painel de Andamento visível |

O layout em uso fica salvo no navegador (localStorage) e é aplicado ao abrir a página de novo; os
layouts salvos com nome ficam no servidor, em `layouts.json` na raiz do projeto (arquivo de dados de
quem está usando, fora do controle de versão).

### 6.12 Atalhos de teclado

Inspirados no Shotcut; a lista completa está sempre disponível pela tecla `?`, onde também dá para
clicar numa tecla e trocá-la (a próxima combinação apertada vira o novo atalho; um botão **Restaurar
padrões** desfaz tudo). As trocas ficam salvas no navegador (localStorage), não na spec do projeto, e um
atalho só funciona quando o foco não está num campo de formulário (para não atrapalhar quem está
digitando).

**Reprodução**

| Tecla | Ação |
| --- | --- |
| Espaço | Reproduzir ou pausar |
| `K` | Pausar |
| `J` | Retroceder (repetir acelera 2x, 4x, 8x) |
| `L` | Avançar (repetir acelera 2x, 4x, 8x) |

**Navegação**

| Tecla | Ação |
| --- | --- |
| Seta esquerda | Um quadro para trás |
| Seta direita | Um quadro para frente |
| `Alt` + seta esquerda | Edição anterior |
| `Alt` + seta direita | Próxima edição |
| `Home` | Ir ao início |
| `End` | Ir ao fim |
| `Page Up` | Voltar 1 segundo |
| `Page Down` | Avançar 1 segundo |

**Edição**

| Tecla | Ação |
| --- | --- |
| `S` | Cortar no cursor |
| `X` ou `Delete` | Remover (ripple) |
| `Z` | Lift (remove sem deixar lacuna na V1) |
| `I` | Aparar entrada até o cursor |
| `O` | Aparar saída até o cursor |
| `Ctrl+D` | Duplicar |
| `Ctrl+A` | Selecionar tudo |
| `Ctrl+R` | Alternar rótulo de ripple |
| `Ctrl+M` | Mudo na trilha atual (a do item selecionado, ou a que o mouse está sobre) |
| `Ctrl+H` | Ocultar a trilha atual |
| `Ctrl+L` | Bloquear a trilha atual |

**Mídia**

| Tecla | Ação |
| --- | --- |
| `A` | Acrescentar a mídia selecionada (painel Mídia) no fim da V1 |
| `V` | Inserir a mídia selecionada no cursor |

**Visualização**

| Tecla | Ação |
| --- | --- |
| `=` | Aproximar (zoom) |
| `-` | Afastar (zoom) |
| `0` | Ajustar à janela |
| `Ctrl+P` | Alternar encaixe (snap) |

**Geral**

| Tecla | Ação |
| --- | --- |
| `Ctrl+Z` | Desfazer |
| `Ctrl+Y` ou `Ctrl+Shift+Z` | Refazer |
| `Ctrl+S` | Salvar |
| `Escape` | Limpar seleção |
| `?` | Mostrar esta lista (clique numa tecla para trocar) |

**Como rebindar**: abra a lista de atalhos (`?`), clique na combinação que quer trocar e, em seguida,
pressione a nova combinação de teclas; ela é gravada na hora, sem precisar recarregar a página. Um
conflito com outro atalho não é bloqueado (dois atalhos podem usar a mesma tecla), então confira antes
de trocar. **Restaurar padrões** apaga todas as trocas salvas e volta à tabela acima.

---

## 7. Usando manualmente pela linha de comando

Todos os comandos abaixo são `.\.venv\Scripts\dmaker.exe <comando>` (sempre esse executável, nunca o
Python global). Use `dmaker <comando> --help` para ver as opções na hora, com a versão instalada.

### 7.1 Referência de comandos

**Ambiente**

| Comando | O que faz |
| --- | --- |
| `doctor` | Verifica FFmpeg, libass, filtros, encoders de hardware, fontes, marcas e dependências opcionais. Opção `--no-hw` pula o teste de encoders de hardware. |
| `setup` | Baixa FFmpeg, a fonte Poppins e o modelo de recorte de pessoa. `--force` baixa de novo mesmo se já existir. |

**Descoberta**

| Comando | O que faz | Exemplo |
| --- | --- | --- |
| `presets [plataforma]` | Lista os formatos de saída, com zona segura e limite. | `dmaker presets instagram` |
| `probe <arquivos...>` | Duração, tamanho, fps e áudio de vídeos, imagens ou áudios. | `dmaker probe video.mp4 foto.jpg` |
| `templates` | Lista os templates com os parâmetros de cada um. | `dmaker templates` |

**Projetos**

| Comando | O que faz | Exemplo |
| --- | --- | --- |
| `new <nome>` | Cria `projects/<nome>/spec.json` a partir de arquivos fonte. Opções: `--preset`, `--src` (repetível), `--brand`, `--captions/--no-captions` (padrão liga), `--logo/--no-logo`. | `dmaker new meu-reel --preset instagram/reels --src a.mp4 b.mp4 --brand medlycare` |
| `new-from-template <template> <nome>` | Cria o projeto a partir de um template e parâmetros. Opções: `--param chave=valor` (repetível; listas separadas por vírgula), `--params-json`. | `dmaker new-from-template reel-medlycare-produto meu-reel --param titulo="Sua agenda organizada" --param prints="C:\1.png,C:\2.png"` |
| `plan <nome>` | Planeja o corte automático de um bloco `multicam`: transcreve, reconhece as fases da cerimônia e substitui o bloco pelos clipes concretos. | `dmaker plan meu-casamento` |
| `autocut <gravação>` | Corta as pausas, os vícios de fala e as frases repetidas de uma gravação falada: cria um projeto com os clipes já cortados e mostra a lista do que saiu (tempo e motivo). Opções: `--name`, `--intensity suave\|normal\|agressiva`, `--min-pause`, `--breath`, `--preset`, `--brand`, `--captions/--no-captions`, `--overwrite`. | `dmaker autocut entrevista.mp4 --intensity normal` |
| `cuts <nome>` e `uncut <nome> <número>` | Lista os cortes do `autocut` e devolve um deles ao projeto (as legendas acompanham). | `dmaker uncut entrevista-corte 3` |
| `batch validate <template> <planilha>` | Confere a planilha contra o modelo sem renderizar nada: campo faltando, arquivo inexistente, texto que não cabe e travessão, cada um com linha e coluna. Opção: `--name-column`. Sai com erro se alguma linha tem problema. | `dmaker batch validate stories-medlycare semana.csv --name-column titulo` |
| `batch run <template> <planilha>` | Valida, cria um projeto por linha e renderiza tudo em `output/<lote>/`. Com linha inválida não começa, a não ser com `--skip-invalid`. Opções: `--lote`, `--name-column`, `--preview`, `--preset`, `--replace`. Ctrl+C interrompe sem perder o que já saiu. | `dmaker batch run stories-medlycare semana.csv --name-column titulo --lote semana` |
| `batch resume <lote>` | Continua o lote: renderiza o que falta, o que falhou e o projeto que você corrigiu; o que já saiu e continua igual não é refeito. Opções: `--rows 2,4`, `--force`. | `dmaker batch resume semana` |
| `batch pause <lote>` e `batch status [lote]` | Pede a um lote em andamento (em outra janela) que pare depois do vídeo atual; mostra o relatório de um lote (o que saiu, o que falhou e por quê) ou a lista de lotes. | `dmaker batch status semana` |
| `validate <spec>` | Valida a spec, confere arquivos e mostra a duração final e avisos. | `dmaker validate projects\meu-reel\spec.json` |

**Render**

| Comando | O que faz | Opções principais |
| --- | --- | --- |
| `render <spec>` | Renderiza no formato da plataforma. Abre a interface por padrão. | `--preview` (rápido, baixa resolução), `--dry-run` (só mostra os comandos ffmpeg), `--force` (ignora cache), `--out` (arquivo de saída), `--preset` (sobrescreve o da spec), `--guides/--no-guides` (zonas seguras), `--no-captions`, `--quiet`, `--segments 12-20` (render parcial), `--no-ui` (não usa a interface) |
| `export <spec> <presets...>` | Exporta o mesmo projeto para vários formatos de uma vez. | `--preview`, `--no-ui` |

Exemplos:

```powershell
.\.venv\Scripts\dmaker.exe render projects\meu-reel\spec.json --preview
.\.venv\Scripts\dmaker.exe render projects\meu-reel\spec.json
.\.venv\Scripts\dmaker.exe export projects\meu-reel\spec.json youtube/shorts facebook/reels
```

**Ferramentas**

| Comando | O que faz | Opções principais |
| --- | --- | --- |
| `captions <video>` | Transcreve com faster-whisper e gera `.srt` (linhas curtas) e `.json` (tempo por palavra). | `--lang` (padrão pt), `--model` (tiny/base/small/medium/large-v3), `--out`, `--max-words`, `--max-chars`, `--device` (cpu/cuda) |
| `sync <principal> <outras...>` | Descobre pelo áudio em que instante do relógio da fonte principal cada outra fonte começa. | `--master-stream`, `--stream` |
| `thumbnail <video>` | Extrai um quadro como imagem de capa. | `--at` (instante em segundos), `--out` |
| `sheet <video>` | Grade de quadros do vídeo inteiro numa imagem. | `--cols`, `--rows`, `--width` |
| `qa <spec>` | Relatório de QA em texto (zona segura, ritmo, contraste, legendas; com `--output`, também a saída renderizada). | `--output <mp4>` |
| `frames <video> <instantes...>` | Extrai quadros em instantes específicos, em segundos. | `--out-dir`, `--width` |
| `card <titulo>` | Gera um cartão PNG isolado no visual da marca, para conferir o design. | `--subtitle`, `--brand`, `--preset`, `--variant` (light/dark), `--out` |
| `quick <video>` | Edição rápida de um único vídeo: corte, formato e opcionais. | `--preset`, `--start`, `--end`, `--reframe` (auto/crop/pad/blur/brand), `--brand`, `--captions`, `--logo`, `--hook`, `--cta`, `--music`, `--preview`, `--out` |
| `clean` | Limpa `cache/mez`, `cache/proxy` e `cache/waveform`. | `--jobs` (limpa também `cache/jobs`) |
| `proxies <nome>` | Gera os proxies 540p para a prévia ao vivo na interface e mostra o status. | |

Exemplo de edição rápida sem escrever spec:

```powershell
.\.venv\Scripts\dmaker.exe quick video.mp4 --preset reels --start 3 --end 33 --captions --logo --brand medlycare --hook "Chega de agenda no papel" --cta "medlycare.com.br"
```

**Serviços**

| Comando | O que faz | Opções principais |
| --- | --- | --- |
| `ui` | Abre a interface gráfica. | `--port` (padrão 8765), `--no-browser` |
| `mcp` | Sobe o servidor MCP por stdio. | |
| `agent` | Opera o DMaker por um modelo local do Ollama (seção 5). | `--model`, `--url`, `--num-ctx`, `--timeout`, `--once` |

### 7.2 Fluxo típico

```powershell
.\.venv\Scripts\dmaker.exe presets                                                # ver os formatos
.\.venv\Scripts\dmaker.exe probe video.mp4 foto.jpg                               # inspecionar as fontes
.\.venv\Scripts\dmaker.exe new meu-reel --preset instagram/reels --src a.mp4 b.mp4 --brand medlycare
.\.venv\Scripts\dmaker.exe validate projects\meu-reel\spec.json
.\.venv\Scripts\dmaker.exe render projects\meu-reel\spec.json --preview           # conferir rápido
.\.venv\Scripts\dmaker.exe sheet output\meu-reel__instagram-reels__preview.mp4    # grade de quadros
.\.venv\Scripts\dmaker.exe qa projects\meu-reel\spec.json                         # relatório de QA
.\.venv\Scripts\dmaker.exe render projects\meu-reel\spec.json                     # final
.\.venv\Scripts\dmaker.exe export projects\meu-reel\spec.json youtube/shorts facebook/reels
```

Ou, a partir de um template (mais rápido para os casos já cobertos, ver seção 7.4):

```powershell
.\.venv\Scripts\dmaker.exe templates
.\.venv\Scripts\dmaker.exe new-from-template reel-medlycare-produto meu-reel `
    --param titulo="Sua agenda organizada em um clique" `
    --param prints="C:\prints\1.png,C:\prints\2.png,C:\prints\3.png" `
    --param cta_titulo="Teste grátis por 3 meses"
```

### 7.3 Escrever a spec na mão (resumo)

Para os casos sem template pronto, escreva `projects/<nome>/spec.json` diretamente. Resumo dos campos
principais (a referência completa, com todos os valores possíveis de cada um, está em
`src/dmaker/resources/guide.md`, lida pela ferramenta MCP `dmaker_guide` ou o recurso `dmaker://guide`):

- **`output`**: `preset`, `quality` (`high` padrão, `max`, `medium`, `draft`), `encoder` (`x264`
  padrão, ou `auto` para hardware), `fps`, `thumbnail_at`, `path`.
- **`brand`**: nome de uma marca em `assets/brands/`.
- **`timeline`**: lista de `clip`, `image` ou `card` (seção 3.4), cada um com `transition`, `reframe` e
  `color` opcionais.
- **`overlays`**: lista de texto, imagem, vídeo (picture-in-picture) e `progress-bar` (seção 3.5).
- **`captions`**: `source` (`auto` ou caminho de `.srt`), `language`, `model`, `style` (seção 3.6).
- **`audio`**: `music`, `tracks`, `normalize` (seção 3.7).
- **`sources`**: fontes de uma sessão multicâmera, com `sync` (seção 3.8 e 7.6).
- **`multicam`**: bloco de corte automático de cerimônia, expandido por `plan_multicam` (seção 7.6).

Tempos são sempre em segundos; caminhos relativos resolvem a partir da pasta da spec (prefira caminhos
absolutos com barra `/`). Depois de escrever, sempre `dmaker validate` antes de renderizar.

### 7.4 Templates parametrizados

Em vez de escrever a spec inteira, monte um projeto a partir de um template pronto passando só o que
muda de vídeo para vídeo (comando `new-from-template`, seção 7.1, ou `new_from_template` no MCP).

| Template | Descrição | Parâmetros principais |
| --- | --- | --- |
| `reel-medlycare-produto` | Reel de produto MedlyCare: abertura, capturas de tela com movimento, CTA. | `titulo`, `subtitulo`, `prints` (obrigatório), `cta_titulo`, `cta_subtitulo`, `musica` (opcional), `legendas` |
| `reel-medlycare-depoimento` | Reel de depoimento: um corte do vídeo com gancho, crédito e CTA. | `video`, `nome`, `cargo`, `hook` (obrigatórios), `cta` |
| `stories-medlycare` | Story de uma dica: captura de tela de fundo, gancho, texto, CTA. | `titulo`, `texto`, `print` (obrigatório) |
| `pessoal-vlog-reel` | Reel pessoal de vlog ou viagem: vídeos em sequência, título, trilha. | `videos` (obrigatório), `titulo`, `musica` |
| `youtube-longo` | Vídeo longo para YouTube: abertura, gravação principal, CTA. | `titulo`, `video` (obrigatório) |
| `casamento-multicam` | Cerimônia multicâmera sincronizada por áudio (cortes ajustados à mão depois). | `cam_principal`, `cam_secundaria`, `audio_externo` (obrigatórios), `nomes`, `data` |
| `tutorial-tela-webcam` | Tutorial com tela gravada e webcam em picture-in-picture. | `tela`, `webcam` (obrigatórios), `titulo`, `subtitulo`, `nome`, `cargo` |
| `explicativo` | Vídeo explicativo em formato de reel: a gravação do apresentador num quadro arredondado embaixo, a área de cima livre para a imagem ou o infográfico de cada assunto, legenda sobre o quadro e o fundo trocando a cada assunto. | `gravacao`, `assuntos` (obrigatórios; cada assunto leva `fim`, `fundo` e `imagem`), `legendas`, `legenda_modo`, `foco`, `marca` |
| `casamento-pascom` | Casamento comunitário padrão da PASCOM: duas câmeras com corte automático pela fala, cartões da marca `pascom-sjb` e trilha na abertura e no encerramento. | `camera_altar`, `camera_lateral` (pastas, obrigatórios), `nomes`, `data` (obrigatórios), mais celebrante, cerimonial, cidade, igreja, diácono, músicos, trilha, início, fim |

Formato de um arquivo de template (para criar um novo): duas chaves de metadados no topo,
`description` e `params` (cada parâmetro com `description`, `default` opcional, `type` e `required`),
removidas do resultado final. Placeholders `"{{nome}}"` substituem um valor inteiro (mantendo o tipo:
número, lista, booleano) ou interpolam dentro de um texto maior; `$for` expande um item de array por
elemento de uma lista; `$if` remove um item ou uma chave quando o valor não é verdadeiro. Referência
completa e receitas em [`templates/README.md`](../templates/README.md). Todos os templates existentes
são validados como `Project` a cada mudança no código (`tests/test_templates.py`), com os parâmetros
obrigatórios preenchidos por valores fictícios.

**Lote: vários vídeos de uma planilha.** Para uma série ("procedimento da semana", o mesmo anúncio por
clínica ou cidade), uma planilha com uma linha por vídeo gera um projeto e um vídeo por linha sobre um
template. Exemplo de planilha para `stories-medlycare` (CSV com `;`, como o Excel brasileiro exporta):

```
titulo;texto;print
Dica um;A fila de espera organiza quem chega;imagens/dica1.png
Dica dois;Agenda online para o paciente;imagens/dica2.png
```

- O nome de cada coluna casa com o parâmetro do template sem diferenciar maiúscula, acento ou espaço
  (`Título`, `titulo` e `TITULO` servem). Coluna que não casa é ignorada, com aviso. Caminhos relativos
  partem da pasta da planilha. Aceita `.csv`, `.json` (lista de objetos) e `.xlsx`; para ler `.xlsx`,
  `pip install -e ".[lote]"`.
- A validação roda antes de tudo e não renderiza nada: aponta linha, coluna e motivo de campo vazio,
  arquivo inexistente, texto que não cabe e travessão (a regra da marca vale para o texto da planilha).
  Com linha inválida o lote não começa; `--skip-invalid` segue sem elas, e o relatório diz por que cada
  uma ficou de fora.
- Cada linha vira um projeto em `projects/<lote>-<nome>`: para corrigir um vídeo, edite esse projeto e
  rode `dmaker batch resume <lote>`, que refaz só ele. O vídeo sai em `output/<lote>/<nome>.mp4`, com o
  nome vindo da coluna escolhida em `--name-column`. O relatório fica em `output/<lote>/relatorio.txt`.
- Pausar (`dmaker batch pause`, ou o botão na interface) vale depois do vídeo em andamento. Retomar não
  refaz o que já saiu. Na interface nova, a tela **Lote** faz o mesmo passo a passo, com a validação em
  tabela, a confirmação para seguir sem as linhas com problema e o progresso de cada vídeo.

### 7.5 Depuração de um render

- `dmaker render ... --dry-run` mostra os comandos ffmpeg sem rodar.
- Grafo de filtros em `cache/jobs/<job>/graph.pretty.txt`, o texto e as legendas em ASS em
  `overlay.ass`, os comandos completos em `cmd.txt` (todos dentro da pasta do job usado no render).
- Um erro do ffmpeg chega com as últimas linhas do `stderr` e o comando completo.
- `dmaker qa` roda as checagens sem renderizar de novo; com `--output`, confere também um vídeo já
  renderizado (duração, resolução, quadros pretos, silêncio, loudness).

### 7.6 Multicâmera passo a passo

1. Declare as fontes do mesmo evento em `sources`, com `sync: "auto"` nas que não são a principal:

   ```json
   "sources": {
     "cam1": { "src": "cam1.mp4" },
     "cam2": { "src": "cam2.mp4", "sync": "auto" },
     "gravador": { "src": "altar.wav", "sync": "auto" }
   }
   ```

   `dmaker sync cam1.mp4 cam2.mp4 altar.wav` mostra o deslocamento e a confiança de cada fonte antes de
   gravar na spec, se preferir conferir à mão; confiança abaixo de 4 merece uma conferência visual.

2. Escreva a timeline com `source` (não `src`) e tempos da sessão: trocar de câmera é só trocar o nome.

   ```json
   "timeline": [
     { "type": "clip", "source": "cam1", "start": 120, "end": 150 },
     { "type": "clip", "source": "cam2", "start": 150, "end": 200, "transition": { "type": "cut" } }
   ]
   ```

3. Faixas externas (gravador de mesa de som, lapela) entram em `audio.tracks`, seguem os cortes
   automaticamente e se misturam ao áudio das câmeras.

4. Câmera que grava em vários arquivos (a própria câmera corta a cada 30 minutos, ou o celular
   pausou): use `parts` no lugar de `src`, com a lista de arquivos em ordem; o pipeline encadeia pelo
   áudio sozinho, mesmo que um clipe atravesse a fronteira entre dois arquivos.

   ```json
   "sources": { "cam1": { "parts": ["cam1_0001.mp4", "cam1_0002.mp4", "cam1_0003.mp4"] } }
   ```

5. Para revisar um trecho sem renderizar tudo: `dmaker render spec.json --preview --segments 12-20`.

6. Corte automático de cerimônia (bloco `multicam`, usado pelo template `casamento-pascom`): depois de
   criar o projeto, rode `dmaker plan <nome>` (ou `plan_multicam` no MCP) para transcrever a câmera de
   áudio, reconhecer as fases do rito (entrada, liturgia, votos, alianças, assinatura, saída) e
   substituir o bloco pelos clipes concretos, alternando as câmeras pela cadência configurada. Depois:
   `validate`, `render --preview` para conferir, ajustar com `edit_project` se precisar, e só então o
   render final. O formato completo do bloco `multicam` (câmeras, cadência, fases, janela de início e
   fim) está no `dmaker://guide`.

Cronograma realista: mezaninos rodam a cerca de 1x o tempo real e o render final em 1080p também, então
um vídeo de 1 hora leva perto de 2 horas do início ao fim.

---

## 8. Marca MedlyCare

### 8.1 O que o tema faz sozinho

Com `"brand": "medlycare"` na spec, cores, fonte e logos vêm do tema automaticamente: não é preciso
escrever valores de cor ou caminho de logo na mão. Paleta: teal escuro `#0C535A` (cor primária), verde
`#75B9A2` (destaque) e menta `#B2E1CF`, sempre em Poppins. Os logos (lockup horizontal, símbolo, versões
claras e escuras) ficam em `assets/brands/medlycare/`. Sobre um cartão ou um fundo `brand` (fonte
inteira sobre fundo gerado no visual do tema), o texto muda de cor sozinho: cor da marca em fundo claro,
branco em fundo escuro. O vocabulário e as substituições de legendas da marca (nomes próprios que o
Whisper costuma errar) já vêm prontos e se somam ao que o projeto adicionar.

### 8.2 Regras

- **Nunca travessão nem meia-risca** em texto na tela: use vírgula, ponto ou dois-pontos no lugar.
  `dmaker validate`/`validate_project` avisa quando encontra um.
- **CTA sempre `medlycare.com.br`**; a oferta atual é teste grátis de 3 meses, sem cartão.
- Tom: abre pela dor do profissional, frases curtas, sem superlativo vazio, sem prometer o que o
  produto não faz. Só anunciar o que já está em produção, não o que está em desenvolvimento.
- Ritmo típico de um reel de produto (15 a 30 s): cartão de abertura com a dor (3 s), de 2 a 4 telas do
  produto em reenquadramento `brand` com legenda de seção (3 a 4 s cada), cartão escuro de CTA (4 s), com
  o gancho sempre nos 3 primeiros segundos.

As regras completas de comunicação (tom, vocabulário, o que pode e o que não pode ser anunciado) estão
na skill `medlycare-marketing`; este manual cobre só o que se aplica dentro da spec do DMaker.

### 8.3 Vocabulário das legendas

`captions.vocabulary` e `captions.replacements` na spec somam com o vocabulário e as substituições já
embutidos no tema da marca (nomes próprios do produto, termos do setor de saúde); use esses campos para
corrigir um nome que o tema ainda não conhece, em vez de mexer no `brand.json`.

---

## 9. Solução de problemas

| Sintoma | O que fazer |
| --- | --- |
| "FFmpeg/ffprobe não encontrados" | Rode `dmaker setup`; se persistir, confira se `bin/ffmpeg/bin/ffmpeg.exe` existe, ou defina `DMAKER_FFMPEG_DIR` apontando para uma instalação já existente. |
| Vídeo HEVC (ou ProRes, MOV de câmera) não toca na prévia da interface | Normal: o navegador não decodifica esses formatos direto. A interface gera um proxy 540p em segundo plano (`cache/proxy`); espere o aviso sumir da barra de ferramentas, ou rode `dmaker proxies <projeto>` manualmente. O render final sempre usa o arquivo original, não o proxy. |
| Legenda automática errou uma palavra (nome próprio, termo técnico) | `fix_captions(nome, {"errado": "certo"})` (MCP) ou pela aba **Legendas** da interface; some `vocabulary`/`replacements` em `captions` na spec para não errar de novo. Gere o preview outra vez para ver a correção. |
| Render muito lento | Use `--preview` para iterar; em produção, `"quality": "high"` (padrão) já é mais rápido que `"max"`; `"encoder": "auto"` usa hardware se `dmaker doctor` detectar um (mais rápido, qualidade um pouco menor); confira também se o cache de mezaninos não foi limpo sem necessidade. |
| Interface com código antigo (subiu antes de uma mudança) | Ela mesma detecta e reinicia sozinha no próximo render, desde que não haja um job em andamento; com um job rodando, ela avisa e segue com a versão antiga até terminar. Sem isso, feche a janela do PowerShell (`Ctrl+C`) e rode `dmaker ui` de novo. |
| Job com erro | O painel Andamento (interface) ou `job_status` (MCP) mostram a mensagem; erros de ffmpeg vêm com as últimas linhas do `stderr` e o comando completo, para reproduzir com `--dry-run`. |
| "Extra inputs are not permitted" ao validar ou salvar | A spec tem um campo que o modelo não reconhece (nome errado ou digitado a mais): a validação da spec rejeita campos extras de propósito, para pegar erros de digitação cedo. Confira o nome do campo contra `dmaker://guide` ou `spec_schema`. |
| Porta ocupada (8765 já em uso) | `dmaker ui --port 8770` (outra porta), ou defina `DMAKER_UI_URL` apontando para onde a interface já está rodando, para a CLI e o MCP a encontrarem em vez de tentar subir outra. |
| Cache grande demais ou resultado preso em uma versão antiga de um trecho | `dmaker clean` (mezaninos, proxies, formas de onda); `dmaker clean --jobs` limpa também o histórico de jobs; `dmaker render --force` ignora o cache só naquele render. |
| Disco cheio por causa dos modelos de IA | `dmaker models list` (ou a aba Modelos da interface) mostra cada modelo com o tamanho real, a licença e o que depende dele, e o que sobrou em `cache/models` sem uso. `dmaker models remove <id>` apaga um modelo (avisa antes quais funções deixam de funcionar), `dmaker models prune` apaga as sobras, `dmaker models download <id>` baixa de volta. Ambos perguntam antes; `--yes` pula a pergunta. |

---

## 10. Anexos

### 10.1 Estrutura de pastas

```
DMaker/
  src/dmaker/
    domain/       spec (modelo Pydantic), presets, brand, timeline, templates, multicam, tracks
    media/        ffmpeg (comando + runner injetável), probe, fonts, audiosync, matting (recorte de pessoa)
    text/         ass, overlays (texto e legendas), captions (cues/SRT), transcribe (Whisper)
    visuals/      cards, motion (Ken Burns sub-pixel), reframe_image, geometry, pip
    filtergraph/  grafos ffmpeg como funções puras (reframe, timeline, overlays, pip, audio, encode, mezzanine)
    pipeline/     etapas do render (context, sources, sync, segments, captions, textlayer, assembly,
                  renderer), serviços (projects, jobs, qa, lint, layout, timeline_view, edits, remote,
                  multicam_plan, proxies, build)
    ui/           servidor FastAPI (server.py) e página estática (static/, vanilla JS)
    agent/        llm.py (OllamaChat), tools.py (McpToolHost), prompt.py, loop.py: operador local
    cli.py        adaptador Typer         mcp_server.py   adaptador MCP
  tests/          unitários (funções puras, pipeline com ffmpeg/Whisper falsos), integração (ffmpeg real)
  assets/         fonts/ (Poppins) e brands/<nome>/ (brand.json + logos)
  templates/      specs de exemplo parametrizadas
  projects/       seus projetos: <nome>/spec.json (+ captions.auto.json/.srt e sync.json gerados)
  projects/_lotes/  estado de cada lote (uma linha da planilha por vídeo); os projetos do lote ficam ao lado
  output/         renders finais e thumbnails; um lote sai em output/<lote>/ (ignorado pelo git)
  cache/          mezaninos, proxies, formas de onda, jobs, modelos (ignorado pelo git)
  bin/ffmpeg/     FFmpeg baixado pelo setup (ignorado pelo git)
  scripts/setup.ps1  bootstrap
  docs/MANUAL.md  este manual
```

### 10.2 Formato de `layouts.json`

Guardado na raiz do projeto (fora do controle de versão), um objeto com um layout nomeado por chave.
Cada layout:

```json
{
  "Meu layout": {
    "version": 1,
    "areas": { "top-center": "player", "top-left": "filters", "bottom": "timeline", "top-right": "media" },
    "sizes": { "row-top": 0.42, "col-left": 240, "col-right": 240, "col-sidebar": 300 },
    "hidden": ["progress"]
  }
}
```

- `areas`: mapa de posição (`top-left`, `top-center`, `top-right`, `bottom`) para o painel que ocupa
  (`player`, `filters`, `media`, `timeline`).
- `sizes`: `row-top` (fração da altura do player, 0.1 a 0.85), `col-left`/`col-right` (largura em
  pixels dos painéis laterais, 160 a 560) e `col-sidebar` (largura da barra lateral, 200 a 520).
- `hidden`: lista de painéis ocultos (`player`, `filters`, `media`, `timeline`, `progress`).

Um layout com uma posição, painel ou tamanho fora do esperado é normalizado silenciosamente (entradas
inválidas descartadas, tamanhos fora da faixa cortados para o limite mais próximo) em vez de dar erro.

### 10.3 Variáveis de ambiente

| Variável | Efeito | Padrão |
| --- | --- | --- |
| `DMAKER_HOME` | Raiz do projeto (onde ficam `bin/`, `assets/`, `cache/`, `projects/`, `output/`). Use se rodar o DMaker fora da pasta do repositório. | Pasta do `pyproject.toml` (instalação editável), senão a pasta atual |
| `DMAKER_FFMPEG_DIR` | Onde procurar `ffmpeg.exe`/`ffprobe.exe` antes de `bin/ffmpeg` e do PATH do sistema. | (nenhum; usa `bin/ffmpeg`) |
| `DMAKER_UI_URL` | Endereço onde a interface gráfica está ou deve subir, usado pela CLI e pelo MCP para mandar renders para lá. Útil com a porta padrão ocupada ou a interface já rodando em outro lugar. | `http://127.0.0.1:8765` |
| `DMAKER_OLLAMA_URL` | Endereço do servidor Ollama usado por `dmaker agent`. | `http://127.0.0.1:11434` |

### 10.4 Onde ficam os logs

Não há um arquivo de log único: cada render em segundo plano guarda seu próprio rastro em
`cache/jobs/<job>/` (grafo de filtros em `graph.pretty.txt`, texto e legendas em `overlay.ass`, os
comandos ffmpeg completos em `cmd.txt`), e o progresso e as mensagens de etapa de um job ficam
acessíveis enquanto o processo está de pé, pela interface (painel Andamento) ou pelo MCP
(`job_status`/`list_jobs`). Erros de renderização são impressos no terminal (CLI) ou devolvidos na
resposta da ferramenta (MCP), com as últimas linhas do `stderr` do ffmpeg.
