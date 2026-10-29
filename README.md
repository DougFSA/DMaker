# DMaker

Editor de vídeos curtos **por comando**: você descreve a edição (para uma IA, pela interface ou pela linha de comando) e o DMaker monta, legenda, narra, dubla e renderiza no formato certo de cada plataforma: Instagram (Reels, Stories, Feed), Facebook, YouTube (Shorts e vídeo longo, 1080p ou 4K), TikTok, WhatsApp Status e LinkedIn.

**Manual completo, organizado por tarefa: [docs/MANUAL.md](docs/MANUAL.md).** Procure ali "Quero fazer X, onde está?". Cada tarefa mostra os três caminhos (pela IA, pela interface e pela CLI). Para modelo local pequeno, sem internet, há a versão em arquivos curtos em [docs/ia](docs/ia/llms.txt), a busca `search_manual` e o comando `dmaker ajuda "sua pergunta"`.

## O que ele faz

- Corta, junta e acelera trechos; transições (inclusive de movimento), looks de cinema e efeitos sonoros.
- Reenquadra para qualquer formato; cartões, textos com papéis prontos, logo e barra de progresso.
- **Legendas automáticas** palavra a palavra (também em caixa arredondada, estilo TikTok), a partir de transcrição local.
- **Cortar pausas e vícios** de uma gravação falada; **vídeo explicativo**; **lote** de vídeos a partir de uma planilha.
- **Voz local**: narrar um roteiro com a sua voz (clonada com autorização), corrigir uma palavra dita errada sem regravar, trocar a voz, separar voz e fundo, **dublar** para outro idioma. Toda voz gerada sai com marca d'água inaudível e etiqueta de procedência.
- Multicâmera sincronizada pelo áudio, picture-in-picture e troca de fundo sem tela verde.
- Operado por **Claude** (servidor MCP), por um **modelo local** (Ollama), pela **interface** (`dmaker ui`) ou pela **CLI**.

Base aberta e local: [FFmpeg](https://ffmpeg.org), [libass](https://github.com/libass/libass), [faster-whisper](https://github.com/SYSTRAN/faster-whisper), Pillow, OmniVoice, Kokoro, Demucs e Ollama. Nada é enviado para a internet depois do primeiro download dos modelos.

## Instalação rápida (Windows)

Precisa de Python 3.11 ou mais novo e de internet na primeira vez (FFmpeg, ~110 MB, e a fonte). No PowerShell:

```powershell
git clone https://github.com/DougFSA/DMaker.git D:\DMaker
cd D:\DMaker
.\scripts\setup.ps1
.\.venv\Scripts\Activate.ps1
dmaker doctor
```

Passo a passo, extras (voz, lote, PDF) e atualização: capítulo "Instalação" do [manual](docs/MANUAL.md).

## Primeiros passos

```powershell
dmaker ui                                   # a interface, em http://127.0.0.1:8765
dmaker quick gravacao.mp4 --captions --hook "Três erros ao gravar em casa"
dmaker ajuda "como dublo um vídeo para inglês?"
dmaker manual export                        # o manual em PDF e HTML de página única, em output/manual
```

Com o Claude Code aberto nesta pasta, basta pedir em português: "faz um reel de 30 segundos desse vídeo, com legenda e logo". O servidor MCP (`dmaker mcp`) já vem ligado pelo `.mcp.json`.

## Para quem desenvolve

- Regras e arquitetura: [CLAUDE.md](CLAUDE.md). Testes: `.venv\Scripts\python -m pytest`; lint: `ruff check src tests` e `ruff format src tests`.
- O manual é a única parte escrita à mão da documentação. A referência dos comandos, das ferramentas MCP e dos campos da spec, o índice de tarefas e a pasta `docs/ia` são **gerados** do código: depois de mudar algo que o usuário vê, atualize a tarefa em `docs/MANUAL.md` e rode `dmaker manual build` (um teste reprova se o manual está desatualizado).
- Referência da spec para a IA: `src/dmaker/resources/guide.md` (ferramenta MCP `dmaker_guide`).
