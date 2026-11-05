# Dar ambiente e voz de efeito: eco, reverb, distorção, modulação e vocoder

Tarefa `eco-reverb-e-modulacao` do manual do DMaker. Dá ambiente a uma narração seca, faz voz de telefone ou de rádio, põe eco numa vinheta e transforma a voz em robô, como efeitos do item, sem mexer no arquivo original.

## Quando usar

A narração foi gravada sem sala, a vinheta pede eco, a voz tem de parecer de telefone ou de rádio antigo, ou o locutor vira um robô.

**Pedidos que levam a esta tarefa:**
- "Dá um ambiente de sala pequena na narração"
- "Põe um eco de 0,3 segundo na vinheta"
- "Deixa a voz de telefone"
- "Faz a voz virar um robô"

## O que perguntar antes

- O projeto (`name`) e o item (`target`): `audio.voiceover.N`, `audio.narration.N`, `audio.music`, `timeline.N` ou `audio.master`. A **ordem conta**.
- **Eco** (`echo`): `delay_seconds` e `decay`. **Atraso** (`delay`): `delay_type`, `echoes`, `decay_db`, `pitch_semitones`. **Reverb** (`reverb`): sala, reverberância, amortecimento, `wet_db` e `dry_db`; as predefinições do Audacity (`reverb_small_room_bright`, `reverb_cathedral`...) saem prontas, e as de uso são `phone_voice`, `old_radio_voice`, `room_narration` e `ethereal_music`.
- **Distorção**, **Phaser**, **Tremolo**, **Wahwah** e **Vocoder** (`carrier` gerado, uma dente de serra por padrão).
- **Vocoder na harmonia de outra trilha:** `carrier_track` (`MUS`, `A1`...); sem a trilha, ou com ela muda ou fora do solo, usa a gerada.
- O item **mantém a duração**: a cauda do eco e do reverb é cortada no fim. `extend_tail` a estica, só em voz gravada e em música.
- Distorção, Phaser, Wahwah e Vocoder não valem em `audio.master`.
- Na narração sintetizada, Vocoder, Distorção e Phaser apagam a marca d'água inaudível, e ela não é reaplicada (decisão de 03/11).

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `audio_effects`: ver os parâmetros e as faixas do reverb
   Argumentos de exemplo: `{"type": "reverb"}`
2. `edit_project`: dar ambiente de sala pequena à narração
   Argumentos de exemplo: `{"name": "abertura", "op": {"type": "audio_effect", "action": "preset", "target": "audio.voiceover.0", "preset": "room_narration"}}`
3. `edit_project`: pôr um eco de 0,3 s na vinheta
   Argumentos de exemplo: `{"name": "abertura", "op": {"type": "audio_effect", "action": "add", "target": "audio.voiceover.1", "effect": {"type": "echo", "delay_seconds": 0.3, "decay": 0.5}}}`
4. `edit_project`: transformar a voz em robô
   Argumentos de exemplo: `{"name": "abertura", "op": {"type": "audio_effect", "action": "add", "target": "audio.voiceover.2", "effect": {"type": "vocoder"}}}`

## Equivalente na CLI

```powershell
dmaker audio effect add projects/abertura/spec.json audio.voiceover.1 echo --param delay_seconds=0.3 --param decay=0.5
dmaker audio effect add projects/abertura/spec.json audio.voiceover.0 reverb --param room_size=30 --param wet_db=-12
```

Tudo entra no histórico (`dmaker undo`).

## Como conferir

Rode `dmaker validate` e ouça a prévia. Medido: o eco de 0,3 s com decaimento 0,5 de um clique de 0,8 deu 0,400 aos 300 ms; o RT60 da sala pequena clara foi de 0,40 s e o da catedral, 4,99 s; o tremolo de 5 Hz a 50% deu envoltória de 5,01 Hz e fundo de 0,509 do topo; o Whisper reconheceu a frase depois do vocoder. Nenhum efeito padrão nem predefinição passa de 0 dBFS sobre fala a -1 dBFS.

## Erros comuns

- **"O efeito Eco muda a duração do item e não vale aqui"**: desligue o `extend_tail`, ou use voz gravada ou música.
- **"O efeito Vocoder trabalha sobre as amostras do item"**: ponha-o no item de voz, não em `audio.master`.
- **A fala some no vocoder**: aumente `noise_level` (as consoantes não têm harmônico) ou `bands`.
- **O som estoura depois do reverb ou do eco**: baixe `wet_db` e `dry_db`.
