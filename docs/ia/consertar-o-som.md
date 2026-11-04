# Consertar cliques, voz estourada e pausas longas

Tarefa `consertar-o-som` do manual do DMaker. Tira estalos, reconstrói a voz que estourou, refaz um estalo curtíssimo e encurta as pausas, sem mexer no arquivo original.

## Quando usar

O áudio tem estalos, a voz estourou no casamento, sobrou um clique que nada pegou, ou a fala tem pausas longas demais.

**Pedidos que levam a esta tarefa:**
- "Tira os estalos desse áudio"
- "Corrige a voz que estourou"
- "Encurta as pausas de 2 segundos para meio segundo"

## O que perguntar antes

- O item (`target`) é o mesmo da tarefa anterior. Cada um é um efeito da cadeia, exceto o Truncar silêncio.
- **Remover cliques** (`click_removal`): `threshold` 200 e `max_spike_width` 20. Abaixo de 200 o detector já está no máximo.
- **Corrigir clipping** (`clip_fix`): `threshold_percent` é o nível em que a onda foi achatada (pico cortado em 70% pede 70) e `reduce_db` baixa o volume depois.
- **Reparar** (`repair`): `start` e `end` do estalo, em segundos do item, no máximo 128 amostras (2,7 ms). Um trecho maior é recusado.
- **Truncar silêncio** (`audio_truncate_silence`) não é um efeito, porque encurta o item: `threshold_db` -20 (de pico), `min_duration` 0,5, `mode` `truncate` (a pausa vira `truncate_to`, 0,5 s) ou `compress` (a duração mínima mais `compress_percent`, 50, do excesso). No **clipe** corta a imagem e o som juntos: a boca continua sincronizada e os marcadores acompanham. Na **voz gravada** é um corte por pausa. Não vale na narração, na música, na faixa externa, no PiP nem no master.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `edit_project`: tirar os estalos
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "audio_effect", "action": "add", "target": "audio.voiceover.0", "effect": {"type": "click_removal"}}}`
2. `edit_project`: reconstruir a voz cortada em 70%
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "audio_effect", "action": "add", "target": "audio.voiceover.0", "effect": {"type": "clip_fix", "threshold_percent": 70}}}`
3. `edit_project`: refazer um estalo de 96 amostras
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "audio_effect", "action": "add", "target": "audio.voiceover.0", "effect": {"type": "repair", "start": 12.3405, "end": 12.3425}}}`
4. `edit_project`: encurtar as pausas para meio segundo
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "audio_truncate_silence", "target": "audio.voiceover.0", "threshold_db": -35, "min_duration": 0.5, "truncate_to": 0.5}}`

## Equivalente na CLI

```powershell
dmaker audio effect add projects/entrevista/spec.json audio.voiceover.0 click_removal
dmaker audio effect add projects/entrevista/spec.json audio.voiceover.0 clip_fix --param threshold_percent=70
dmaker audio effect add projects/entrevista/spec.json audio.voiceover.0 repair --start 12.3405 --end 12.3425
dmaker audio truncate-silence projects/entrevista/spec.json timeline.0 --threshold-db -35 --min-duration 0.5 --truncate-to 0.5
```

`truncate-silence` aceita `--mode compress --compress-percent 50` e `--start`/`--end`. Tudo entra no histórico (`dmaker undo`).

## Como conferir

Renderize e rode `dmaker qa`. Medido em sinal de teste: cliques de 1 a 5 amostras somem e a fala muda -0,05 dB; a voz cortada em 70% fica uns 8 dB mais perto da original; pausas de 2 s viram 0,5 s, com um quadro e o som no mesmo instante antes e depois.

## Erros comuns

- **"nenhum silêncio de pelo menos 0.5 s abaixo de -20 dB"**: o chiado passa do limiar, que é de pico. Suba para -35 ou -30 dB, ou tire o chiado antes.
- **Os estalos ficaram**: suba `max_spike_width`; o que sobrar, o Reparar refaz. Se a fala perdeu consoantes, suba `threshold` e baixe a largura.
- **"o Reparar conserta no máximo 128 amostras"**: selecione só o estalo.
- **A voz ainda estoura**: o `threshold_percent` está acima do nível do corte.
