# Conferir o vídeo antes de publicar

Tarefa `conferir-video` do manual do DMaker. Roda as checagens automáticas em texto (duração, zona segura, ritmo de leitura, contraste, legendas e o arquivo renderizado) sem gastar tempo olhando imagem.

## Quando usar

Antes de entregar qualquer vídeo, e sempre que algo parecer estranho (texto cortado, som baixo, legenda fora do lugar).

**Pedidos que levam a esta tarefa:**
- "Confere se esse vídeo está certo"
- "Tem algum problema nesse projeto antes de eu publicar?"

## O que perguntar antes

- O nome do projeto e, se já renderizou, o vídeo gerado.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `validate_project`: duração final e avisos de limite e de marca
   Argumentos de exemplo: `{"name_or_path": "meu-reel"}`
2. `render_project`: gerar a prévia
   Argumentos de exemplo: `{"name_or_path": "meu-reel", "preview": true}`
3. `qa_report`: conferir o projeto e o arquivo
   Argumentos de exemplo: `{"name_or_path": "meu-reel", "output": false}`
4. `contact_sheet`: só se o QA apontar algo: grade de quadros
   Argumentos de exemplo: `{"video": "C:/dmaker/output/meu-reel__instagram-reels__preview.mp4"}`

## Equivalente na CLI

```powershell
dmaker validate projects\meu-reel\spec.json
dmaker qa projects\meu-reel\spec.json
dmaker qa projects\meu-reel\spec.json --output output\meu-reel__instagram-reels.mp4
dmaker sheet output\meu-reel__instagram-reels__preview.mp4
dmaker frames output\meu-reel__instagram-reels__preview.mp4 2 8 15
```

## Como conferir

O relatório separa o que é do projeto (zona segura, ritmo, contraste, sobreposições, legendas) do que é do arquivo (duração, resolução, quadros pretos, silêncio, loudness perto de -14 LUFS). Cada achado diz onde está.

## Erros comuns

- **Texto fora da zona segura**: mova o texto (`position` ou `region`) ou encurte-o.
- **Loudness longe de -14**: confira `audio.normalize` (padrão `two-pass`).
- **Quadros pretos**: um trecho com `fade_in`/`fade_out` longo, ou um clipe que acaba antes do previsto.

---
