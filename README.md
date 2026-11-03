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
- Operado por **Claude** (servidor MCP), por um **modelo local** sem internet (`dmaker agent` e a tela **Agente**), pela **interface** (`dmaker ui`) ou pela **CLI**.

Base aberta e local: [FFmpeg](https://ffmpeg.org), [libass](https://github.com/libass/libass), [faster-whisper](https://github.com/SYSTRAN/faster-whisper), Pillow, OmniVoice, Kokoro, Demucs e Ollama. Nada é enviado para a internet depois do primeiro download dos modelos.

## Usar sem internet (agente local)

O DMaker pode ser operado por conversa com um modelo que roda na sua máquina, sem nenhum serviço na nuvem. Com internet, **uma vez**, baixe o que as funções usam; depois, desligue a rede.

```powershell
dmaker doctor --offline        # lista o que falta baixar e o comando de cada download
ollama pull gpt-oss:20b        # o modelo de linguagem (ou outro, por DMAKER_AGENT_MODEL)
dmaker doctor --offline        # "Tudo pronto: o DMaker funciona sem internet"
dmaker agent                   # conversa no terminal (ou a tela Agente, em dmaker ui)
dmaker agent --once "Dubla este vídeo D:\videos\aula.mp4 para inglês"
```

- **Motor e modelo por configuração**: `DMAKER_AGENT_ENGINE` (`ollama` ou `openai`, para llama.cpp server e LM Studio), `DMAKER_AGENT_MODEL`, `DMAKER_AGENT_URL`. Nada de nome de modelo fixo no código.
- **Kits de ferramentas**: cada pedido cai num kit (edição, legendas, voz, dublagem, correção de fala, multicâmera, composições, lote) e o modelo só vê as ferramentas e o manual curto daquele kit.
- **Proteções**: argumentos conferidos contra o esquema da ferramenta; nenhum caminho de arquivo inventado; confirmação sua antes de render final, apagar e sobrescrever; clonar voz só com a autorização do dono da voz.
- **Medir**: `dmaker agent eval` roda uma bateria de pedidos em português e mostra acerto, passos, tempo e memória por modelo. Máquina de 16 GB de RAM roda o `gpt-oss:20b` (cerca de 14 GB, na CPU cada resposta leva minutos): na bateria de 22 pedidos ele acertou 82%, sem nenhuma ação insegura; modelos de 30 bilhões de parâmetros não cabem.

Detalhes no capítulo "Usando com LLM local (Ollama)" do [manual](docs/MANUAL.md).

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

## Subir a interface (backend e frontend)

O backend é a API local em FastAPI (`src/dmaker/ui/server.py`), que o `dmaker ui` sobe. O frontend é a interface nova em Vue 3 (pasta `frontend/`) e só conversa com essa API. Precisa do `.venv` da instalação acima ativado e do Node.js 20.19 ou 22.12 em diante.

**Para usar**, numa porta só: compile o front e suba o backend, que serve a interface nova em `/` e a clássica em `/classica`.

```powershell
cd frontend
npm ci              # na primeira vez e quando o package-lock.json mudar
npm run build       # gera src/dmaker/ui/dist/ (fica fora do git)
cd ..
dmaker ui           # http://127.0.0.1:8765; --port troca a porta, --no-browser não abre o navegador
```

Sem o build, `/` abre a interface clássica. Depois de um `git pull`, rode `npm run build` de novo: o `dmaker ui` já aberto passa a servir as telas novas sem reiniciar. `Ctrl+C` encerra.

**Para desenvolver o front**, com a tela recarregando a cada mudança, use dois terminais:

```powershell
# terminal 1: o backend, na porta para onde o Vite repassa a API
dmaker ui --port 8773 --no-browser

# terminal 2: o frontend, em http://localhost:5174
cd frontend
npm run dev
```

O `npm run dev` repassa `/api` para `http://127.0.0.1:8773`. Para usar um backend em outra porta: `$env:DMAKER_API = "http://127.0.0.1:8765"; npm run dev`. Mudança no Python pede reiniciar o `dmaker ui`. Antes de dar uma mudança do front por pronta: `npm run lint`, `npm run typecheck`, `npm run test` e `npm run build`.

Bom saber: o `dmaker render`, o `dmaker export` e o servidor MCP mandam o trabalho para a interface aberta e, se não houver nenhuma, sobem uma sozinhos em segundo plano na 8765. Use `--no-ui` para rodar só no terminal, ou `DMAKER_UI_URL` para apontar outro endereço.

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
