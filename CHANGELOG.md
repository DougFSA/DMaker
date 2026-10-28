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

- **DMK-36**: manual completo por tarefa, com versão para IA local, busca e ajuda por pergunta. O `docs/MANUAL.md` foi refeito organizado por tarefa ("Fazer um Reel a partir de uma gravação", "Narrar um roteiro com a minha voz", "Dublar um vídeo para outro idioma", "Corrigir uma palavra errada sem regravar", "Verificar se um áudio foi gerado pelo DMaker", 29 no total), cada uma com os três caminhos (pela IA, pela interface e pela CLI, ou a frase dizendo que um não existe), mais glossário, índice "Quero fazer X, onde está?", a seção "O que entrou nesta versão" e capturas de tela de projetos sintéticos em `docs/img`; o README encolheu e aponta para ele. A referência dos comandos da CLI, das ferramentas MCP e dos campos da spec é gerada do código entre marcadores: `dmaker manual build` regenera (idempotente; `--check` só confere) e os testes reprovam manual desatualizado, comando, ferramenta ou campo novo sem documentação, exemplo que cita o que não existe e vídeo ou áudio dentro de `docs/`. `dmaker manual export [--pdf] [--html] [--out]` gera o PDF (Chromium do Playwright, atrás do protocolo `Browser` em `media/browser.py`, que a composição em HTML vai reaproveitar) e o HTML de página única, com imagens embutidas e sumário com links, em `output/manual`. A versão para IA local sai do manual e do código (nunca à parte): `docs/ia` tem um arquivo curto por tarefa (no máximo 1.500 tokens estimados), sempre no mesmo molde (quando usar e frases de pedido, o que perguntar, as ferramentas MCP na ordem com argumentos que o teste valida contra o esquema do servidor, o equivalente na CLI, como conferir, erros comuns), mais o índice `llms.txt`; a pasta vai junto no pacote instalado (`setup.py` copia para `dmaker/resources/manual`) e o manual explica como carregá-la no Open WebUI e no LM Studio. Ferramenta MCP nova `search_manual` (busca BM25 por palavras, sem embeddings, devolve seção, texto e a tarefa sugerida) e `dmaker ajuda "pergunta"`, que responde em português com o modelo local e a busca, cita a seção e oferece executar a tarefa pelo agente local quando ele já tem todas as ferramentas dela (as demais ficam para os kits por tarefa do agente). Bateria fixa de 10 perguntas em `tests/data/manual_perguntas.json`, com teste lento atrás de `DMAKER_MANUAL_EVAL=1` e a rede bloqueada para tudo que não é localhost.
- **DMK-30**: acabamento visual com looks prontos por nome e efeitos de câmera e de filme, tudo pelo ffmpeg, sem LUT nem arquivo de terceiros. `"look": "cinema"` no projeto aplica o acabamento a todos os trechos (vídeo, foto e cartão); os padrões são `cinema`, `quente`, `frio`, `pb-contraste` e `vintage`, e a marca define os seus em `looks` no `brand.json` (com o mesmo nome, o da marca vale no lugar do padrão). O `look` do trecho vence o do projeto, `"nenhum"` desliga, e um trecho com `color` próprio mantém a cor dele. Em `color` entram os efeitos avulsos `grain` (granulação de filme animada, sempre igual a cada render), `light_leak` (vazamento de luz gerado pelo próprio DMaker, reaproveitando o gerador das transições), `glow` (brilho suave) e `aberration` (aberração cromática), e `vignette` passa a aceitar uma intensidade de 0 a 1 (`true` continua gerando o mesmo filtro). A receita do mezanino mudou (`MEZZ_VERSION` m7: o cache de trechos é refeito). `dmaker looks list`, `dmaker looks sheet <nome|all>` e a tela "Looks" da interface nova mostram cada look ao lado da mesma cena sem acabamento. A granulação custa tamanho de arquivo (o x264 gasta bits nela): +17% numa cena de muito detalhe com `grain` 0.25 e uns 3 a 4 MB a cada 10 s numa cena parada; o guia traz os números.
- **DMK-32**: lote de vídeos a partir de uma planilha (`dmaker batch validate|run|resume|pause|status`, ferramentas MCP `validate_batch`, `run_batch`, `resume_batch`, `pause_batch`, `batch_status` e a tela "Lote" da interface nova): uma linha por vídeo, sobre um modelo de projeto, em CSV (UTF-8 ou o ANSI do Excel, separador `,` ou `;`), XLSX ou JSON. O nome de cada coluna casa com o parâmetro do modelo sem diferenciar maiúscula, acento ou espaço, e o valor da célula é convertido para o tipo do parâmetro. A validação roda antes de tudo, sem renderizar nada, e aponta linha, coluna e motivo de campo obrigatório vazio, arquivo inexistente (caminho relativo parte da pasta da planilha), texto que não cabe no espaço (as mesmas medidas do QA) e travessão (a regra da marca vale para o texto da planilha); linha com problema só fica de fora se a pessoa mandar seguir sem ela (`--skip-invalid`, `skip_invalid`, ou o passo de confirmação na tela). Cada linha vira um projeto salvo (`projects/<lote>-<nome>`, para corrigir e renderizar de novo só aquele) e um vídeo em `output/<lote>/<nome>.mp4`, com o nome vindo da coluna escolhida. O lote roda como um job, um vídeo por vez, grava o estado de cada linha em `projects/_lotes/<lote>.json` e pode ser pausado (vale depois do vídeo em andamento) e retomado: o que já saiu com a mesma spec não é refeito, e se o processo cair a retomada refaz só o vídeo que estava no meio. Relatório final do que saiu, do que falhou e por quê, na CLI, no MCP, na tela e em `output/<lote>/relatorio.txt`.
- **DMK-23**: modelo de projeto "explicativo" (`templates/explicativo.json`; `new_from_template`, `dmaker new-from-template explicativo ...`): vídeo de reel com a gravação do apresentador num quadro de cantos arredondados embaixo, uma área livre em cima para a imagem (ou, depois, o infográfico) de cada assunto, legenda curta sobre a parte de baixo do quadro e o fundo trocando a cada assunto (escuro, claro, bege, cor ou imagem). Recebe a gravação (vertical ou horizontal: o quadro corta preenchendo, sem distorcer, com `foco` para o rosto) e a lista de assuntos (`fim`, `fundo`, `imagem`, emendados); a gravação é uma sobreposição de vídeo contínua, então a troca de fundo nunca corta a fala. O quadro e a área de cima ficam dentro da zona segura do Reels. Para isso a spec ganhou regiões nomeadas (`regions`: retângulos em fração do quadro) e `region: "<nome>"` em sobreposições de texto, imagem e vídeo, que se encaixam na região sem conta de pixel (nome inexistente é erro claro na validação; projeto sem `regions` não muda); a região "topo" é onde os infográficos entram. Também: cartão de cor lisa (`card.flat`, sem exigir título), `x`/`y` na sobreposição de imagem, `focus` no corte do picture-in-picture, `captions.style.follow_background` (legenda que ignora o tom do fundo), parâmetros de template com `example`, campo de objeto (`{{item.campo}}`) e preparador de parâmetros (`prepare`) no motor de templates, e aviso quando o vídeo de uma sobreposição é mais curto que o intervalo pedido. A medição de loudness passa a contar o áudio das sobreposições de vídeo: antes uma gravação que vinha só numa sobreposição era medida como silêncio e saía sem normalizar, e nos projetos com picture-in-picture a normalização ignorava a voz dele.
- **DMK-33**: legendas no estilo TikTok: novo modo `captions.style.mode: "rounded"`, em que cada linha ganha uma caixa de fundo do tamanho dela, de cantos arredondados, e as caixas de linhas de larguras diferentes se emendam com curvas suaves (desenho vetorial, nítido em qualquer resolução); o destaque da palavra ativa continua por cima da caixa. Os textos sobrepostos (gancho, título, CTA) ganham o mesmo desenho com `style.box_shape: "rounded"`. Raio e margem da caixa vêm da marca (`style.rounded_box_radius` e `style.rounded_box_padding` do `brand.json`, padrão 28 px na base 1080). O modo `boxed` segue como era.
- **DMK-27**: cortar automaticamente as pausas, os vícios de fala e as frases repetidas de uma gravação falada (`dmaker autocut`, ferramenta MCP `autocut` e o botão "Cortar gravação" em Projetos). O resultado é um projeto de clipes comuns da mesma gravação (a spec não ganha modo de corte; só `audio_fade` por clipe, um fade de áudio de 10 ms sem escurecer a imagem), com as legendas seguindo a fala cortada, e a lista do que saiu (tempo e motivo) para conferir antes de renderizar: `dmaker cuts`, `list_cuts` e o cartão "Cortes automáticos" do projeto, onde cada corte tem "Desfazer" (`dmaker uncut`, `undo_cut`). Intensidades: suave (só pausas), normal (pausas e vícios) e agressiva (também falsos começos e frases repetidas, ficando com a última tomada). O "né" só é vício quando fecha a frase antes de uma pausa (o "não é" no meio da frase fica); "é" e "tipo" só quando isolados por pausa ou arrastados. O tempo das palavras é ajustado à energia do áudio e cada borda cai no vale de energia mais próximo; a duração de cada clipe é um múltiplo do quadro para as legendas não saírem do compasso. O corte muda a receita do mezanino (`MEZZ_VERSION` m6): o cache de trechos é refeito no primeiro render.
- **DMK-25**: efeitos sonoros curtos num instante da linha do tempo. A spec ganhou `audio.sfx` (lista de `{sound, at, volume}`) e o campo opcional `sound` nas sobreposições de texto, imagem e vídeo e na transição: `true` toca o som padrão do tipo (pop em texto e imagem, whoosh em vídeo e transição), um nome escolhe o som, e `{sound, volume, offset}` ajusta o nível e antecipa ou atrasa o som; sem o campo nada toca (o som automático é opt-in), e a entrada de sobreposição que a spec vier a ter no futuro (infográfico, composição) entra no plano só por declarar `sound`. A biblioteca (whoosh, whip, pop, click, riser, impact, ding) é sintetizada pelo próprio DMaker em `assets/sfx` (ruído filtrado com envelope e varredura, tons com queda de afinação, parciais de sino, semente fixa), com o pico de cada arquivo em -3 dBFS para o `volume` valer o mesmo em todos, origem e licença no `assets/sfx/LICENSES` e nada baixado: o render funciona sem internet. `dmaker sfx list` mostra a biblioteca e `dmaker sfx build` a gera de novo; um som próprio entra por caminho (relativo à pasta do projeto). Na mixagem cada efeito entra com atraso exato em amostras (12,40 s toca em 12,40 s, medido por correlação cruzada no áudio do render), é somado depois do ducking e antes do loudnorm (a música não abaixa por causa dele e a loudness final continua no alvo) e fica abaixo da voz: o render mede a voz sozinha e põe o pico do efeito 6 dB abaixo do pico que a voz terá na saída, já contando o limite de -1,5 dBTP do loudnorm; com `volume` 1,5, o máximo, ainda sobram 2,5 dB. Projeto sem efeitos gera exatamente o mesmo grafo de áudio de antes (e o render parcial por `segments` ignora `audio.sfx`).
- **DMK-29**: transições de movimento e curva de tempo. Cinco transições novas, montadas pelo próprio DMaker e registradas por extensão ao lado dos 48 tipos do xfade: `crosszoom` (zoom de passagem: a imagem amplia e desfoca e a próxima entra do mesmo zoom), `whippan` (chicote com borrão de movimento proporcional à velocidade), `blurslide` (desfoque deslizando), `filmburn` (queima de filme) e `lightleak` (vazamento de luz; a luz vem de um gerador próprio, sem arquivo de terceiros, que o acabamento visual também vai usar). Todas aceitam `transition.curve`: `linear` (padrão: as transições antigas geram o mesmo grafo de sempre), `ease` ou `spring` (mola: corre, passa um pouco do ponto e assenta). A curva é uma função pura; nas cinco novas ela dirige o zoom, o deslocamento, o raio do desfoque e a intensidade da luz, e nas do xfade remapeia o tempo da troca (na mola o progresso é limitado a 1, porque uma cortina não anda além da borda). A troca roda só sobre os quadros da janela de transição, o resto do vídeo passa intacto. Prévia: `dmaker transitions list` e `dmaker transitions sheet <nome|all>` (folha de contato de cada transição entre dois clipes de teste, em cache), rota `/api/transitions` e a tela **Transições** da interface nova, com a folha de cada uma e seletor de curva. Ficam de fora o som na troca (DMK-25) e o giro 3D e a folha virando (composição em HTML, DMK-26).

### Fixed

- **DMK-37**: o play da linha do tempo na interface clássica não tocava o som que vem da mesa e das faixas externas. A vista mandava cada faixa de `audio.tracks` como um item corrido de 0 ao fim, sem fatiar pelos cortes, e o player tocava só o primeiro item de cada trilha (a música com vários spans perdia as outras janelas), buscava tempo negativo quando o gravador entrava depois da câmera, abria sempre o primeiro arquivo de uma fonte em `parts` e ignorava volume de faixa, volume da música, `mute_clips` e o mudo da A1. Agora a vista fatia cada faixa por clipe com a mesma conta do render (`pipeline/track_slices.py`, usada também pelo mezanino: arquivo, ponto no arquivo, atraso e velocidade do clipe), aponta V1, A1 e faixas para a parte que grava cada instante, e o player toca em cada trilha só o item do instante, num `<audio>` por trilha, com o volume do item e os mudos aplicados; os proxies passam a cobrir todas as partes.

### Pré-requisitos na máquina

- **DMK-36**: para exportar o manual em PDF, rodar `pip install -e ".[docs]"` (extra novo `docs`, que traz o Playwright) e `python -m playwright install chromium` (baixa o Chromium, cerca de 120 MB). O HTML de página única, a busca e o `dmaker ajuda` não precisam disso; o `dmaker ajuda` com resposta de modelo precisa do Ollama no ar com `gpt-oss:20b` (ou outro modelo com `--model`).
- **DMK-32**: para ler planilha `.xlsx` no lote, rodar `pip install -e ".[dev,captions,lote]"` (extra novo `lote`, que traz o `openpyxl`); CSV e JSON não precisam de nada. Quem usa a interface nova roda `cd frontend; npm run build` de novo para a tela "Lote" aparecer.
- **DMK-27**: rodar `pip install -e ".[dev,captions]"` de novo: o extra `captions` agora trava o PyAV em `av>=11,<16`, porque o faster-whisper abre o áudio com o parâmetro `metadata_errors`, removido no PyAV 16 (com a versão nova a transcrição falha com TypeError). O corte automático usa a transcrição do Whisper `small`, que baixa na primeira vez, como as legendas.

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
