# Gerar sons: tom, ruído, tons de discagem, metrônomo e bipe de censura

Tarefa `gerar-sons` do manual do DMaker. Cria um som do zero (tom, varredura, ruído, tons de telefone, metrônomo, corda, tambor ou amostras de um texto), solto em arquivo ou na linha do tempo, e bipa uma palavra para censurá-la.

## Quando usar

Bipe de censura sobre um palavrão, tom de teste para calibrar o volume, ruído rosa de fundo, metrônomo para editar no ritmo, toque de telefone num vídeo de humor, silêncio para abrir espaço numa trilha.

**Pedidos que levam a esta tarefa:**
- "Bipa a palavra 'droga' na entrevista"
- "Gera um tom de 1 kHz a -6 dB de 2 segundos para eu calibrar"
- "Põe um metrônomo a 120 BPM por 30 segundos no começo do vídeo"

## O que perguntar antes

- Para **bipar**: o projeto e o item onde a palavra foi dita (`target`: `timeline.N`, `overlays.N`, `audio.voiceover.N` ou `audio.narration.N`). A palavra sai da transcrição local (Whisper, sem rede); item com mais de 15 minutos pede `search_from` e `search_to`, e palavra repetida pede `occurrence`.
- Para **gerar**: o tipo (`audio_generators` lista os nove) e os parâmetros; o que faltar fica no padrão. Sem `duration` vale a que o gerador pede, ou 1 s; o teto é de 10 minutos por som.
- O nível é o `amplitude_db` do gerador mais o `volume` do item: não se nivela contra a voz como os sons da biblioteca. O bipe nasce a -12 dBFS. Se um pedaço da palavra escapar, use `margin` (0.03).
- Numa narração sintetizada o silêncio do bipe apaga a marca d'água inaudível do trecho; ela não é reaplicada (decisão de 03/11).

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `audio_generators`: ver os parâmetros e as faixas de um gerador
   Argumentos de exemplo: `{"type": "rhythm_track"}`
2. `audio_generate`: um tom de teste solto, em arquivo
   Argumentos de exemplo: `{"generator": "tone", "params": {"frequency_hz": 1000, "amplitude_db": -6}, "duration": 2, "out": "output/tom-1khz.wav"}`
3. `edit_project`: um metrônomo de 30 s no projeto
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "generated_add", "generator": "rhythm_track", "params": {"tempo_bpm": 120, "beats": 60}, "start": 0}}`
4. `edit_project`: bipar a palavra, achada na transcrição do item
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "censor_beep", "target": "audio.voiceover.0", "word": "droga"}}`
5. `edit_project`: bipar um intervalo conhecido, sem transcrever
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "censor_beep", "target": "audio.voiceover.0", "start": 12.4, "end": 12.9}}`
6. `undo_edit`: desfazer o bipe
   Argumentos de exemplo: `{"name": "entrevista"}`

## Equivalente na CLI

```powershell
dmaker audio generators
dmaker audio generate tone --param frequency_hz=1000 --param amplitude_db=-6 --duration 2 --out output/tom-1khz.wav
dmaker audio generated add projects/entrevista/spec.json rhythm_track --param tempo_bpm=120 --param beats=60 --start 0
dmaker audio censor projects/entrevista/spec.json audio.voiceover.0 --word droga
dmaker undo projects/entrevista/spec.json
```

## Como conferir

Medido no WAV: o tom de 1 kHz a -6 dBFS tem pico de -6,000 dBFS e 1000,00 Hz; o ruído rosa, -2,99 dB por oitava; o DTMF "123" é lido por Goertzel; a 120 BPM há uma batida a cada 0,500 s. No bipe, o item fica a -96,6 dBFS no intervalo da palavra, a fala em volta é idêntica à original e o Whisper não a transcreve mais.

## Erros comuns

- **"Não achei ... na transcrição"**: veja os trechos parecidos que a mensagem lista, ou diga `start` e `end`.
- **"aparece N vezes"**: diga `occurrence` (1, 2...).
- **"diga o que bipar"**: faltou `word`, `region` ou `start` e `end`.
- **"frequency_hz"** (ou outro campo fora da faixa): `audio_generators` mostra a faixa.
- **"há valores fora de -1 a 1"**: ligue `normalize` no Importar Amostras.
- **"já existe; use overwrite"**: escolha outro destino ou use `overwrite`.
