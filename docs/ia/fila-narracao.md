# Narrar um roteiro longo em segundo plano (fila)

Tarefa `fila-narracao` do manual do DMaker. Põe um roteiro longo (audiobook, manual narrado, vários roteiros) numa fila que narra um item por vez, retoma de onde parou e separa por capítulos.

## Quando usar

O roteiro leva horas para narrar, ou são vários, e você não quer travar a tela nem perder o que já saiu se o computador reiniciar.

**Pedidos que levam a esta tarefa:**
- "Narra esse livro em capítulos"
- "Põe esses três roteiros na fila de narração"

## O que perguntar antes

- O roteiro como texto, ou um arquivo `.txt`, `.md` ou `.docx`. Uma linha com `# `, `Capítulo N` ou `Parte N` (no Word, estilo Título ou Heading 1 e 2) abre um capítulo.
- A voz, o título (nome do item e da pasta) e o formato (`wav` ou `mp3`). A estimativa de tempo parte de cerca de 1,4 s por caractere a 16 passos (0,7 s no rascunho) e passa a usar a velocidade medida nesta máquina.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `voice_queue_add`: enfileirar o roteiro
   Argumentos de exemplo: `{"file_path": "C:/roteiros/audiobook.docx", "voice": "narradora", "title": "audiobook", "format": "wav"}`
2. `voice_queue_list`: ver o andamento e o tempo restante
   Argumentos de exemplo: `{}`

## Equivalente na CLI

```powershell
dmaker voice queue add --file audiobook.docx --voice narradora --title audiobook
dmaker voice queue list
dmaker voice queue run
```

`queue run` executa em primeiro plano, um item por vez, e volta quando a fila esvazia; `queue pause <id>`, `queue resume <id>` e `queue cancel <id>` controlam um item.

## Como conferir

Cada item grava em `output/narracoes/<título>/`: um arquivo por capítulo (`NN-<capítulo>.wav`), o `<título>-completo.wav` com 1,5 s de silêncio entre capítulos e o `.srt` do completo. Se o processo cair, o item em andamento volta a pendente e retoma sem ressintetizar as falas que já estão em `cache/voice`.

## Erros comuns

- **Item parado**: nada roda sem executor; abra o `dmaker ui` ou rode `dmaker voice queue run`.
- **Capítulos não separaram**: o título não está no formato (`# Título`, `Capítulo N`, `Parte N`; no Word, estilos de título).
- **Demora**: use o rascunho para conferir e a versão final para entregar.
