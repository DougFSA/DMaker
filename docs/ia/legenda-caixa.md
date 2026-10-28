# Deixar a legenda em caixa arredondada

Tarefa `legenda-caixa` do manual do DMaker. Põe uma caixa de fundo arredondada atrás de cada linha da legenda, no estilo do TikTok, mantendo o destaque da palavra que está sendo falada.

## Quando usar

Você quer a legenda com caixa de fundo (mais legível sobre imagens claras ou movimentadas) em vez do texto solto com contorno. O mesmo desenho vale para gancho, título e chamada.

**Pedidos que levam a esta tarefa:**
- "Faz a legenda ficar em caixa"
- "Quero a legenda arredondada, estilo TikTok"
- "Põe um fundo atrás da legenda"

## O que perguntar antes

- O projeto já tem legendas automáticas (`captions.source` é `auto`, um `.srt` ou `narration`).
- Se quiser cantos mais ou menos redondos, o raio e a margem vêm da marca (`rounded_box_radius` e `rounded_box_padding` no `brand.json`; padrão 28 px na base 1080).

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `edit_project`: trocar o modo da legenda para caixa arredondada
   Argumentos de exemplo: `{"name": "meu-reel", "op": {"type": "set_field", "path": "captions.style.mode", "value": "rounded"}}`
2. `render_project`: gerar a prévia para ver a caixa
   Argumentos de exemplo: `{"name_or_path": "meu-reel", "preview": true}`
3. `qa_report`: conferir que a legenda cabe na zona segura
   Argumentos de exemplo: `{"name_or_path": "meu-reel", "output": false}`

## Equivalente na CLI

```powershell
dmaker new meu-reel --preset instagram/reels --src gravacao.mp4
dmaker render projects\meu-reel\spec.json --preview
```

A CLI não tem um comando que mude só o estilo: edite `projects\meu-reel\spec.json` e ponha `"captions": {"source": "auto", "style": {"mode": "rounded", "max_words": 6, "max_chars": 30}}`; depois rode `dmaker validate projects\meu-reel\spec.json` e o render. Num texto, o campo é `"style": {"box_shape": "rounded"}`.

## Como conferir

Na prévia, cada linha tem a sua caixa, e linhas de larguras diferentes se emendam com curvas suaves; a palavra ativa continua destacada por cima. A cor e a opacidade da caixa seguem `box_color` e `box_alpha`.

## Erros comuns

- **A caixa não aparece**: o modo continua `karaoke`; confira `captions.style.mode`.
- **A legenda ficou grande demais**: reduza `max_words` e `max_chars`, ou `size`.
- **"Extra inputs are not permitted"**: o nome do campo está errado; veja "Campos da spec" na referência.
