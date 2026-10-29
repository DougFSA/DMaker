# Pôr efeitos sonoros num instante do vídeo

Tarefa `efeitos-sonoros` do manual do DMaker. Põe sons curtos (whoosh, pop, clique, riser, impacto) num instante marcado, ou na entrada de um texto, uma imagem ou uma transição.

## Quando usar

A entrada de um infográfico, a troca de fundo ou o fim de uma contagem pedem um som. Os sons são sintetizados pelo próprio DMaker e ficam em `assets/sfx`, então funcionam sem internet.

**Pedidos que levam a esta tarefa:**
- "Põe um whoosh quando o gráfico entrar"
- "Quero um som de impacto aos 31 segundos"

## O que perguntar antes

- Em que segundo do **vídeo final** o som toca (`at`), ou qual elemento o dispara (texto, imagem, vídeo, transição).
- Qual som: `whoosh`, `whip`, `pop`, `click`, `riser`, `impact` ou `ding`, ou o caminho de um arquivo seu.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `edit_project`: marcar os efeitos nos instantes
   Argumentos de exemplo: `{"name": "meu-reel", "op": {"type": "set_field", "path": "audio.sfx", "value": [{"sound": "whoosh", "at": 12.4}, {"sound": "impact", "at": 31.0, "volume": 1.2}]}}`
2. `validate_project`: avisar de efeito depois do fim do vídeo
   Argumentos de exemplo: `{"name_or_path": "meu-reel"}`
3. `render_project`: ouvir na prévia
   Argumentos de exemplo: `{"name_or_path": "meu-reel", "preview": true}`

## Equivalente na CLI

```powershell
dmaker sfx list
dmaker validate projects\meu-reel\spec.json
```

`dmaker sfx list` mostra a biblioteca; `dmaker sfx build` sintetiza os sons de novo. Na spec: `"audio": {"sfx": [{"sound": "whoosh", "at": 12.4}]}`; no texto, imagem ou vídeo, `"sound": true` toca o som padrão do tipo (`pop` em texto e imagem, `whoosh` em vídeo e transição) na entrada.

## Como conferir

O efeito entra com atraso exato (12,40 s toca em 12,40 s) e fica 6 dB abaixo do pico da voz. A loudness final continua no alvo. O render parcial (`--segments`) ignora `audio.sfx`.

## Erros comuns

- **"som desconhecido"**: o nome não é da biblioteca nem um arquivo existente; confira com `dmaker sfx list`.
- **Aviso de efeito depois do fim**: o `at` passa da duração do vídeo.
- **Muito baixo ou alto**: ajuste `volume` (0 a 1,5; o padrão 1 é a referência).
