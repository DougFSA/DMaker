# Reparar o som de um item: silenciar, cortar, envelope, canais e deslocar

Tarefa `reparar-o-som` do manual do DMaker. Mexe no som de qualquer item como o Audacity mexe numa seleção (silenciar, cortar, desenhar o volume, mexer nos canais, deslocar no tempo, ganho e pan da trilha), sem tocar na imagem nem no arquivo.

## Quando usar

Uma tosse no meio da fala, a música que precisa subir no fim, a lapela que gravou só de um lado, uma câmera com o som atrasado.

**Pedidos que levam a esta tarefa:**
- "Silencia de 12 a 14 segundos do clipe 1"
- "Faz a música subir de -12 dB para 0 dB entre 50 e 55 segundos"
- "A lapela gravou só no canal esquerdo, usa só ele nos dois lados"
- "O som da câmera está 0,12 s atrasado"

## O que perguntar antes

- O projeto (`name`) e o item (`target`): `timeline.N` (o som do clipe), `overlays.N` (PiP), `audio.voiceover.N`, `audio.narration.N`, `audio.tracks.N` (faixa externa), `audio.music` ou `audio.master` (a mistura).
- Os tempos (`start`, `end`) são segundos do **vídeo final**, como na `timeline_view`; vale `marker:<texto>`, e `region: "marker:<texto>"` pega começo e fim de uma região.
- Silenciar, cortar, o envelope e os canais são **efeitos** na cadeia do item: o arquivo, a imagem e a duração do vídeo não mudam.
- No item preso à imagem (clipe, PiP) e na narração, **cortar** tira o intervalo, o resto recua e o fim completa com silêncio; na voz gravada e na música o item encolhe. A faixa externa e a mistura não se cortam (silencie o intervalo).

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `edit_project`: silenciar a tosse
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "audio_silence", "target": "timeline.1", "start": 12, "end": 14}}`
2. `edit_project`: subir a música no fim
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "audio_envelope", "target": "audio.music", "points": [{"at": 50, "db": -12}, {"at": 55, "db": 0}]}}`
3. `edit_project`: usar o canal esquerdo da lapela nos dois lados
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "audio_channels", "target": "timeline.0", "mode": "left"}}`
4. `edit_project`: atrasar o som da câmera 0,12 s
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "audio_shift", "target": "timeline.0", "delta": 0.12}}`
5. `edit_project`: baixar a música 6 dB e levá-la um pouco para a esquerda
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "track_set", "track": "MUS", "gain_db": -6, "pan": -0.3}}`

## Equivalente na CLI

```powershell
dmaker audio silence projects/entrevista/spec.json timeline.1 --start 12 --end 14
dmaker audio cut projects/entrevista/spec.json audio.voiceover.0 --start 30 --end 32
dmaker audio envelope projects/entrevista/spec.json audio.music --point 50=-12 --point 55=0
dmaker audio channels projects/entrevista/spec.json timeline.0 left
dmaker audio shift projects/entrevista/spec.json timeline.0 --delta 0.12
dmaker audio split-stereo projects/entrevista/spec.json audio.voiceover.0
dmaker audio track projects/entrevista/spec.json MUS --gain-db -6 --pan -0.3 --solo
```

## Como conferir

Ouça a prévia da linha do tempo (mesmo grafo do render) ou renderize com `dmaker render --preview`. Medido: o trecho silenciado fica em zero exato, sem estalo; o envelope de 0 a -12 dB entre 10 e 12 s desce 3 dB a cada 0,5 s; com `pan` -1 o canal direito fica mudo; a lapela com `left` sai igual nos dois lados.

## Erros comuns

- **"a fonte deste trecho tem várias partes"**: as edições por intervalo não valem em clipe de fonte com `parts`; o `audio_channels` sem intervalo vale.
- **A música repete o envelope**: a cadeia da música vale no arquivo, antes do loop; se a música dá a volta, o envelope dá a volta junto.
- **Cortar o meio de uma narração sintetizada** desloca o resto e pode apagar a marca d'água inaudível depois do corte; a etiqueta de procedência continua.
