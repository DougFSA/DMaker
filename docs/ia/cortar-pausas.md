# Cortar as pausas de uma gravação falada

Tarefa `cortar-pausas` do manual do DMaker. Tira as pausas, os vícios de fala e as frases repetidas de uma gravação falada e entrega um projeto de clipes já cortados, com a lista do que saiu.

## Quando usar

Você gravou falando (entrevista, aula, depoimento) e quer o vídeo sem silêncios e "hum", "né", "ééé". Use no lugar de cortar clipe a clipe à mão.

**Pedidos que levam a esta tarefa:**
- "Corta as pausas dessa gravação"
- "Tira os hum e os silêncios do vídeo"
- "Deixa a entrevista mais enxuta"

## O que perguntar antes

- O arquivo (vídeo ou áudio com fala) e o nome do projeto novo.
- A intensidade: `suave` (só pausas), `normal` (pausas e vícios, o padrão) ou `agressiva` (também falsos começos e frases repetidas, ficando com a última tomada).

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `autocut`: criar o projeto cortado
   Argumentos de exemplo: `{"source": "C:/videos/entrevista.mp4", "name": "entrevista-corte", "intensity": "normal"}`
2. `list_cuts`: mostrar o que saiu, com tempo e motivo
   Argumentos de exemplo: `{"name_or_path": "entrevista-corte"}`
3. `undo_cut`: devolver ao projeto o corte número 3
   Argumentos de exemplo: `{"name_or_path": "entrevista-corte", "cut_id": 3}`
4. `render_project`: gerar a prévia
   Argumentos de exemplo: `{"name_or_path": "entrevista-corte", "preview": true}`
5. `qa_report`: conferir o resultado
   Argumentos de exemplo: `{"name_or_path": "entrevista-corte", "output": false}`

## Equivalente na CLI

```powershell
dmaker autocut entrevista.mp4 --name entrevista-corte --intensity normal
dmaker cuts entrevista-corte
dmaker uncut entrevista-corte 3
dmaker render projects\entrevista-corte\spec.json --preview
```

`--min-pause` (padrão 0,5 s) é a pausa acima da qual há corte e `--breath` (0,15 s) o silêncio que sobra de cada lado da fala. `--overwrite` refaz um projeto que já existe.

## Como conferir

`dmaker cuts` lista cada corte com tempo na gravação original, motivo (`silence`, `filler`, `repetition`) e as palavras tiradas. Ouça a prévia nas emendas: cada borda cai no vale de energia mais próximo, sem passar por dentro de uma palavra. As legendas seguem a fala cortada.

## Erros comuns

- **"Nada passou do limite"**: a gravação tem ruído forte ou volume muito baixo; tente `--intensity agressiva` ou uma `--min-pause` menor.
- **O "né" ou o "é" sumiu no meio da frase**: o "né" só sai quando fecha a frase antes de uma pausa; se saiu errado, devolva o corte com `dmaker uncut`.
- **Mexi na linha do tempo e a legenda saiu do lugar**: volte `captions.source` para `"auto"` para transcrever de novo.
