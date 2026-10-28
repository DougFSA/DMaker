# Changelog

Todas as mudanças relevantes do DMaker são registradas aqui.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e o versionamento acompanha as **versões de release** do projeto (mesma numeração
das versões do Jira, projeto DMK, que também dá o nome da tag `vX`).

## Como escrever uma entrada

- **Versão mais recente no topo.** Cabeçalho: `## vX — AAAA-MM-DD`.
- Mantenha um bloco **`## [Não lançado]`** no topo para ir acumulando o que já
  está na `develop` mas ainda não foi para a `main`.
- Agrupe as mudanças nestas seções, nesta ordem (omita as vazias):
  - `### Added`: novas funcionalidades. Épicos grandes agrupam seus cards.
  - `### Changed`: mudanças de comportamento em algo que já existia.
  - `### Fixed`: correção de bug. Diga o **mecanismo/causa**, não só o sintoma.
  - `### Chore`: build, limpeza, dependências, testes, documentação.
  - `### Pré-requisitos na máquina`: o que precisa estar instalado ou baixado
    antes de usar a versão, senão quebra (extra do pip, modelo que baixa na
    primeira vez, `dmaker setup`, modelo do Ollama, variável de ambiente).
- Cada linha começa pela ref do card: `DMK-xxx`. Marque criticidade com `[Crít.]`.
- Uma linha por card sempre que possível; card com facetas (voz + interface +
  CLI) pode descrever as facetas na mesma linha.
- **Chamado novo entra aqui; rodada de redesenvolvimento não.** O redesenvolvimento
  conserta algo que nunca foi lançado. Se ele mudou o que a entrada original
  promete, ajuste a entrada original.
- Feche a versão na `develop` **antes** do merge para a `main`; fechar depois
  duplica a seção.
- Sem travessão em texto de tela e em mensagens; vale para o que as linhas
  descrevem (o cabeçalho de versão é a única exceção, por convenção do formato).

---

## [Não lançado]

### Added

- **DMK-33**: legendas no estilo TikTok: novo modo `captions.style.mode: "rounded"`, em que cada linha ganha uma caixa de fundo do tamanho dela, de cantos arredondados, e as caixas de linhas de larguras diferentes se emendam com curvas suaves (desenho vetorial, nítido em qualquer resolução); o destaque da palavra ativa continua por cima da caixa. Os textos sobrepostos (gancho, título, CTA) ganham o mesmo desenho com `style.box_shape: "rounded"`. Raio e margem da caixa vêm da marca (`style.rounded_box_radius` e `style.rounded_box_padding` do `brand.json`, padrão 28 px na base 1080). O modo `boxed` segue como era.

### Fixed

- **DMK-37**: o play da linha do tempo na interface clássica não tocava o som que vem da mesa e das faixas externas. A vista mandava cada faixa de `audio.tracks` como um item corrido de 0 ao fim, sem fatiar pelos cortes, e o player tocava só o primeiro item de cada trilha (a música com vários spans perdia as outras janelas), buscava tempo negativo quando o gravador entrava depois da câmera, abria sempre o primeiro arquivo de uma fonte em `parts` e ignorava volume de faixa, volume da música, `mute_clips` e o mudo da A1. Agora a vista fatia cada faixa por clipe com a mesma conta do render (`pipeline/track_slices.py`, usada também pelo mezanino: arquivo, ponto no arquivo, atraso e velocidade do clipe), aponta V1, A1 e faixas para a parte que grava cada instante, e o player toca em cada trilha só o item do instante, num `<audio>` por trilha, com o volume do item e os mudos aplicados; os proxies passam a cobrir todas as partes.

## v1 — 2026-10-27

### Added

- **DMK-20** (fase 1): interface nova em Vue com visual próprio, telas de Projetos e Saídas e jobs ao vivo; a interface atual continua em /classica
- **DMK-5**: trocar a voz de uma gravação inteira por uma voz da biblioteca,
  mantendo ritmo, entonação e o fundo (`dmaker voice convert`, ferramenta MCP
  `convert_voice` e seção "Trocar voz" na aba Voz).
- **DMK-4**: dublagem com uma voz clonada por pessoa, separando quem fala (diarização local).
  O novo modo `per_speaker` (padrão da dublagem) descobre quem fala em cada trecho, monta um
  clone por falante a partir do melhor trecho de 3 a 15 s só com a fala dele e dubla cada fala
  com a voz do falante certo; com uma pessoa só vale como `single`. O falante de cada fala
  aparece no `.dub.json`, na tabela da seção Dublar (coluna editável) e em `dub_get`; trocar
  o falante (`dub_update_segment`, `speaker`) refaz só aquela fala. CLI: `dmaker dub prepare
  --speakers N` força o número de pessoas. `per_segment` e `single` seguem como estavam.
- **DMK-7**: voz gerada por IA identificável em dois níveis. (1) Toda fala sintetizada leva uma marca d'água inaudível (AudioSeal) com a assinatura "DM" de 16 bits, a última coisa feita na voz: resiste ao acabamento broadcast da narração, à dublagem com ajuste de andamento, à mixagem com música de fundo e ao AAC do vídeo final. (2) Todo arquivo que o DMaker grava com voz gerada (render com narração, `voice say`, fila de narrações, dublagem e a trilha da voz dublada, correção de fala, troca de voz) leva no contêiner uma etiqueta de procedência, `DMaker: voz gerada por IA (v1); trechos=...`, com os segundos em que a voz entra; é ela que acha uma narração curta dentro de um vídeo longo, o que a marca no áudio sozinha não garante. As duas desligam juntas com `DMAKER_WATERMARK=0` ou `dmaker voice say --no-watermark`. `dmaker voice verify ARQUIVO [--audio]` (e a ferramenta MCP `verify_watermark`) lê a etiqueta primeiro e, sem ela, analisa o áudio (8 alinhamentos) e responde em três níveis: encontrada (o detector reage e a assinatura de 16 bits confere em 15 ou mais), indício, inconclusivo (o detector reage mas a assinatura não confere, o que música e tons puros provocam) e não encontrada. Limite: um vídeo recodificado fora do DMaker perde a etiqueta, e uma narração curta num vídeo longo pode não ser achada pelo áudio.
- **DMK-6**: fila de narrações que roda em segundo plano e retoma de onde parou, com importação de roteiro em txt, md ou docx por capítulos
- **DMK-16**: prévia ao vivo da narração, tocando cada frase assim que fica pronta, com parar sem perder o que já saiu
- **DMK-3**: trilha NAR na linha do tempo da interface, com a duração real das falas já sintetizadas e arrastar para mudar o início
- **DMK-18**: exportar as trilhas separadas da dublagem (voz dublada, fundo e voz original) para mixar em outro editor
- **DMK-19**: dublagem pode esticar o vídeo nos trechos em que a fala traduzida não cabe, em vez de acelerar ou cortar a voz (modos voz, vídeo e misto)
- **DMK-17**: gerenciador de modelos (ver tamanho, licença e uso de cada modelo, baixar, apagar e limpar sobras) na CLI, no MCP e na interface

### Fixed

- **DMK-8**: testes de voz e áudio isolados em pasta temporária (diretórios de dados fixados na
  importação dos módulos e lidos do `cache/` e `output/` reais), suíte estável com síntese real rodando
  ao mesmo tempo. Os dados passam a morar em `DMAKER_DATA_DIR` (padrão: a raiz), e um gancho de auditoria
  reprova qualquer teste que escreva em `cache/`, `output/`, `projects/`, `assets/voices/` ou no léxico real.

### Chore

- **DMK-5, DMK-7, DMK-17**: ligações entre os cards da v1 depois de juntos: a troca de voz passa a levar a
  marca d'água (mesmo `DMAKER_WATERMARK=0`), o Kokoro e o OpenVoice usam o download com hash de
  `media/downloads.py`, o gerenciador de modelos conhece AudioSeal, separação de falantes e OpenVoice (não
  aparecem mais como sobra), as trilhas separadas da dublagem seguem o vídeo esticado e `.claude/worktrees/`
  sai do git.

### Pré-requisitos na máquina

- **DMK-20**: para ver a interface nova, Node.js instalado e `cd frontend; npm ci; npm run build` (gera `src/dmaker/ui/dist/`); sem o build, `dmaker ui` segue com a interface atual em `/`
- **DMK-5**: os pesos do conversor de timbre OpenVoice V2 (MIT, 131 MB) baixam
  sozinhos para `cache/models/openvoice` na primeira troca de voz, com versão e
  SHA-256 fixados. Nenhum pacote novo do pip: o conversor usa o `torch` e o
  `torchaudio` que já precisam estar instalados para a voz (o código de
  inferência está em `src/dmaker/voice/third_party/openvoice`).
- **DMK-4**: `.venv\Scripts\pip install -e .[voice]` instala o `sherpa-onnx` (diarização na
  CPU, sem token nem conta). Na primeira dublagem no modo `per_speaker`, os modelos baixam para
  `cache/models/diarization` (cerca de 34 MB, versão e SHA-256 fixados): segmentação
  pyannote-segmentation-3.0 em ONNX (licença MIT) e embeddings CAM++ do 3D-Speaker (Apache-2.0),
  das releases oficiais do k2-fsa. Sem o `sherpa-onnx`, ou com `DMAKER_DIARIZATION=off`, o padrão
  volta a ser `per_segment`.
- **DMK-7**: pacote `audioseal` no extra `voice` (`.venv\Scripts\pip install -e .[voice]`); os pesos (~90 MB) são baixados na primeira marca ou verificação, para `cache/models/audioseal`.

---

## Linha de base — 2026-10-22

O que já estava na `main` quando o fluxo de `develop` começou (nada abaixo passou
por card no Jira, exceto onde indicado).

### Added

- Editor de vídeos curtos por comando: a partir de uma spec JSON, renderiza com
  FFmpeg para Instagram, Facebook, YouTube, TikTok, WhatsApp e LinkedIn
  (presets com zonas seguras), com marcas (`assets/brands`), cartões, textos,
  música e modelos prontos (`templates/`), incluindo modelo de casamento.
- Legendas automáticas com Whisper (palavra a palavra), multicâmera com
  sincronização por áudio, picture-in-picture e recorte de pessoa sem tela verde.
- Interface gráfica local (`dmaker ui`): linha do tempo, player com proxies de
  prévia, trilhas com forma de onda e telas reorganizáveis.
- Operação por IA: servidor MCP (`dmaker mcp`), operador local com Ollama
  (`dmaker agent`) e relatório de QA em texto; manual completo em `docs/MANUAL.md`.
- **DMK-9 a DMK-15**: estúdio de voz local (narração, clonagem e voz projetada
  com OmniVoice e Kokoro, pronúncia por idioma, isolamento vocal com Demucs,
  correção de fala e dublagem com tradução pelo Ollama). **Em teste manual**,
  já na `main` antes do fluxo de `develop`.

### Chore

- Projetos de vídeo (`projects/`), vozes clonadas (`assets/voices/`) e saídas
  saem do repositório e passam a ser ignorados pelo git.

### Pré-requisitos na máquina

- Python 3.11+ com o `.venv` do projeto e `pip install -e .` (mais as extras
  `captions` e `voice` conforme o uso: `pip install -e .[voice,captions]`; o
  `torch` entra à parte, versão CPU, pelo índice da PyTorch).
- `dmaker setup` para baixar o FFmpeg (`bin/ffmpeg`), a fonte Poppins e o modelo
  de recorte de pessoa.
- Modelos que baixam na primeira vez que o recurso é usado: Whisper, OmniVoice,
  Kokoro e Demucs.
- Modelo do Ollama para tradução na dublagem: `gpt-oss:20b` (ou o que estiver em
  `DMAKER_TRANSLATE_MODEL`).
