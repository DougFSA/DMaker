# Equalizar e filtrar o som: graves e agudos, EQ gráfico, passa-alta e Notch

Tarefa `equalizar-som` do manual do DMaker. Muda o timbre de um item de áudio ou da mistura: graves e agudos, EQ por bandas ou por uma curva, corte do ronco e do zumbido, e predefinições suas.

## Quando usar

Gravação de celular com grave embolado, ronco de ar-condicionado, zumbido de 60 Hz da rede elétrica, voz abafada, ou um som que precisa parecer telefone ou rádio.

**Pedidos que levam a esta tarefa:**
- "Tira o ronco de ar-condicionado da entrevista, abaixo de 80 Hz"
- "Tem um zumbido de 60 Hz na gravação, tira com os harmônicos"
- "A voz está abafada, dá mais brilho nos agudos"
- "Salva esse ajuste de equalização para usar nos outros vídeos"

## O que perguntar antes

- O projeto (`name`) e o item: `timeline.N`, `overlays.N`, `audio.voiceover.N`, `audio.narration.N`, `audio.tracks.N`, `audio.music` ou `audio.master`. A **ordem** da cadeia conta.
- O zumbido da rede é de 60 Hz no Brasil e de 50 Hz em outros países.
- O EQ por Curva aceita até 40 pontos. O filtro do EQ Gráfico e do EQ por Curva (8191 amostras) não separa bandas coladas abaixo de uns 60 Hz.
- Numa narração sintetizada a equalização pode apagar a marca d'água inaudível da voz; ela não é reaplicada (decisão de 03/11).

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `audio_effect_response`: conferir a curva sem renderizar
   Argumentos de exemplo: `{"effect": {"type": "highpass", "frequency_hz": 80, "slope_db": 24}}`
2. `edit_project`: cortar o ronco abaixo de 80 Hz
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "audio_effect", "action": "add", "target": "audio.voiceover.0", "effect": {"type": "highpass", "frequency_hz": 80, "slope_db": 24}}}`
3. `edit_project`: tirar o zumbido de 60 Hz e os harmônicos
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "audio_effect", "action": "preset", "target": "audio.voiceover.0", "preset": "hum_60hz"}}`
4. `audio_effect_presets`: guardar a cadeia com um nome
   Argumentos de exemplo: `{"action": "save", "label": "Voz de celular limpa", "effects": [{"type": "highpass", "frequency_hz": 80, "slope_db": 24}]}`
5. `undo_edit`: desfazer
   Argumentos de exemplo: `{"name": "entrevista"}`

## Equivalente na CLI

```powershell
dmaker audio effect add projects/entrevista/spec.json audio.voiceover.0 highpass --param frequency_hz=80 --param slope_db=24
dmaker audio effect preset projects/entrevista/spec.json audio.voiceover.0 hum_60hz
dmaker audio effect response highpass --param frequency_hz=80 --param slope_db=24
dmaker audio preset save "Voz de celular limpa" --effect '{"type": "highpass", "frequency_hz": 80, "slope_db": 24}'
dmaker audio preset list
```

## Como conferir

No render pela CLI: o passa-alta de 80 Hz a 24 dB derruba o tom de 40 Hz em 24,1 dB e muda o de 1 kHz em menos de 0,1 dB; o Notch de 60 Hz derruba o tom de 60 Hz em mais de 50 dB e a voz muda menos de 0,02 dB; o EQ Gráfico com +6 dB em 3,15 kHz mede +5,6 dB na banda de um terço de oitava; o gráfico difere do som no máximo 0,1 dB nos filtros e 0,6 dB no EQ por pontos.

## Erros comuns

- **"slope_db"**: a inclinação é de 6 em 6 dB por oitava, de 6 a 48.
- **"dois pontos na mesma frequência"**: arraste um dos pontos do EQ por Curva.
- **"gains_db"**: o EQ Gráfico tem exatamente 31 ganhos, de -20 a +20 dB.
- **"não consegui ler a macro"**: o arquivo dessa predefinição em `assets/macros` foi estragado à mão; corrija o JSON (o DMaker nunca o sobrescreve sozinho, e as outras seguem funcionando).
