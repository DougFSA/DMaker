# Mudar o tom, a velocidade e o andamento, e esticar o som

Tarefa `tempo-e-afinacao` do manual do DMaker. Afina uma voz sem mudar a duração, encaixa uma música num tempo sem mudar o tom, faz o efeito de disco que perde a rotação e estica um som até virar uma textura etérea, sem mexer no arquivo original.

## Quando usar

A voz ficou grossa ou fina, a música precisa durar menos sem soar mais aguda, o fim deve "parar" como um vinil, ou a abertura pede uma música esticada e etérea.

**Pedidos que levam a esta tarefa:**
- "Sobe a voz gravada 2 semitons, sem mudar a duração"
- "Leva a música de 120 para 128 BPM sem mudar o tom"
- "Estica a música 8 vezes (Paulstretch) para a abertura"

## O que perguntar antes

- O projeto (`name`) e o item (`target`): `audio.voiceover.N` ou `audio.music`; o Mudar Tom vale também em `timeline.N`, `overlays.N`, `audio.narration.N` e `audio.master`.
- **Mudar Tom** (`change_pitch`, sem mudar a duração): `mode` é `semitones` (`semitones`, `cents`), `notes` (`from_note`, `from_octave`, `to_note`, `to_octave`) ou `percent`; `preserve_formants` guarda o timbre da voz.
- **Mudar Velocidade e Tom** (`change_speed`, o vinil): `mode` é `percent` ou `rpm` (`rpm_from`, `rpm_to`: 33⅓ é 33,3333, 45, 78).
- **Mudar Andamento** (`change_tempo`, sem mudar o tom): `mode` é `percent`, `bpm` (`bpm_from`, `bpm_to`) ou `duration` (`length_from`, `length_to`).
- **Esticar Gradualmente** (`sliding_stretch`): `tempo_start`, `tempo_end` (em %), `pitch_start`, `pitch_end` (em semitons), em linha reta do início ao fim.
- **Paulstretch** (`paulstretch`): `stretch_factor` (8 transforma 5 s em 40 s) e `time_resolution` (a janela, 0,25 s). A saída vai até 20 minutos.
- Os quatro que mudam a duração só valem em voz gravada e em música; no clipe e no PiP, a velocidade é o `speed` do clipe. Tom e tempo na narração podem apagar a marca d'água inaudível, e ela não é reaplicada (decisão de 03/11).

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `edit_project`: levar a música de 120 a 128 BPM
   Argumentos de exemplo: `{"name": "abertura", "op": {"type": "audio_effect", "action": "add", "target": "audio.music", "effect": {"type": "change_tempo", "mode": "bpm", "bpm_from": 120, "bpm_to": 128}}}`
2. `edit_project`: subir a voz 2 semitons
   Argumentos de exemplo: `{"name": "abertura", "op": {"type": "audio_effect", "action": "add", "target": "audio.voiceover.0", "effect": {"type": "change_pitch", "semitones": 2, "preserve_formants": true}}}`
3. `timeline_view`: ver a duração nova dos itens
   Argumentos de exemplo: `{"name": "abertura"}`

## Equivalente na CLI

```powershell
dmaker audio effect add projects/abertura/spec.json audio.music change_tempo --param mode=bpm --param bpm_from=120 --param bpm_to=128
dmaker audio effect add projects/abertura/spec.json audio.music paulstretch --param stretch_factor=8
dmaker validate projects/abertura/spec.json
```

Tudo entra no histórico (`dmaker undo`).

## Como conferir

Rode `dmaker validate`: o aviso traz a duração nova. Medido em sinais de teste: +2 semitons em 440 Hz deu 493,88 Hz, com 0 ms de mudança na duração; de 120 para 128 BPM a duração ficou em 0,9375 e o tom em 440,00 Hz; de 45 para 33⅓ RPM o tom e a velocidade caíram a 0,7407; o Paulstretch 8x de 5 s deu 40,0 s, sem estalo.

## Erros comuns

- **"O efeito Mudar Andamento muda a duração do item e não vale aqui"**: ele está num clipe, PiP, narração ou no master. Ponha-o na voz gravada ou na música, ou use o `speed` do clipe.
- **"Paulstretch: a saída teria 25.0 minutos e o teto é de 20"**: use um fator menor, ou um trecho mais curto (`start`, `end`).
- **O Paulstretch de uma nota só "pisca"**: um tom puro oscila de nível ao ser esticado; use um som com mais timbre.
