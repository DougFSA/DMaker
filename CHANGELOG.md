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

- **DMK-19**: dublagem pode esticar o vídeo nos trechos em que a fala traduzida não cabe, em vez de acelerar ou cortar a voz (modos voz, vídeo e misto)

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
