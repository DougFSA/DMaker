# Pôr a narração dentro de um vídeo

Tarefa `narracao-no-projeto` do manual do DMaker. Coloca a fala sintetizada como voz do vídeo, direto na spec, e usa o texto falado como legenda, sem gerar o áudio antes.

## Quando usar

O vídeo é feito de cartões e imagens (ou de clipes mudos) e a voz é narrada. A música abaixa sozinha sob a narração e a loudness final a conta.

**Pedidos que levam a esta tarefa:**
- "Narra esse texto sobre os cartões do vídeo"
- "Põe a narração no projeto e usa como legenda"

## O que perguntar antes

- O projeto, o texto (ou um `.txt` relativo à pasta do projeto), a voz e o instante em que a fala começa.
- A voz e o texto são lidos do cache: só a primeira vez sintetiza.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `edit_project`: pôr a narração no projeto
   Argumentos de exemplo: `{"name": "meu-video", "op": {"type": "set_field", "path": "audio.narration", "value": [{"text": "Bem-vindo ao DMaker.", "voice": "narradora", "start": 0.5, "seed": 1}]}}`
2. `edit_project`: usar o texto falado como legenda
   Argumentos de exemplo: `{"name": "meu-video", "op": {"type": "set_field", "path": "captions", "value": {"source": "narration"}}}`
3. `validate_project`: avisar de voz inexistente ou narração que passa do fim
   Argumentos de exemplo: `{"name_or_path": "meu-video"}`
4. `render_project`: gerar a prévia
   Argumentos de exemplo: `{"name_or_path": "meu-video", "preview": true}`

## Equivalente na CLI

```powershell
dmaker validate projects\meu-video\spec.json
dmaker render projects\meu-video\spec.json --preview
```

Na spec: `"audio": {"narration": [{"text": "Bem-vindo ao DMaker.", "voice": "narradora", "start": 0.5, "seed": 1}]}` e `"captions": {"source": "narration"}`. Cada item aceita `text` ou `script`, `voice`, `instruct`, `start`, `volume` (0 a 4), `speed`, `language` e `seed`.

## Como conferir

`dmaker validate` avisa se a voz não existe na biblioteca ou se a narração estimada passa do fim do vídeo; o render avisa se a real passou. Com `--dry-run` nada é sintetizado (usa a estimativa); o render parcial ignora a narração.

## Erros comuns

- **Demora no primeiro render**: está sintetizando; os seguintes usam o cache.
- **Legenda sem destaque**: use `style.mode: "karaoke"` com `source: "narration"`.
- **A música não abaixa**: confira `audio.music.ducking` (padrão ligado).
