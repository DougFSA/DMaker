# Controlar o volume: compressor, limitador, noise gate e loudness

Tarefa `volume-e-dinamica` do manual do DMaker. Aperta a diferença entre o som forte e o fraco, segura os picos num teto, fecha o chiado entre as frases e iguala o volume de duas falas, sem mexer no arquivo original.

## Quando usar

A narração varia de volume, duas gravações têm volumes muito diferentes, ou o som estoura no vídeo final.

**Pedidos que levam a esta tarefa:**
- "Deixa a voz do podcast mais uniforme e com volume de podcast"
- "Iguala o volume das duas narrações em -16 LUFS"
- "Segura os picos para nada passar de -1 dB"

## O que perguntar antes

- O projeto (`name`) e o item (`target`): `timeline.N`, `overlays.N`, `audio.voiceover.N`, `audio.narration.N`, `audio.music`, `audio.tracks.N` ou `audio.master`. O **Noise Gate** trabalha sobre as amostras do item e não vale no `audio.master`.
- Os parâmetros são os do Audacity 3.6. Onde a faixa dele passa da do filtro do ffmpeg, vale a do filtro: razão de 1 a 20:1 (acima disso use o Limitador), joelho de 0 a 18 dB, compensação de 0 a 36 dB.
- O **Limitador** garante o teto em **dBTP** (pico verdadeiro). O **Compressor** e a **Normalização de loudness** não limitam: se o ganho subir, ponha o Limitador por último.
- As predefinições `podcast_voice`, `reels_voice` e `hold_peaks` põem uma cadeia pronta, cada efeito separado e editável.
- Compressor, gate e limitador mudam a voz sintetizada e podem apagar a marca d'água inaudível dela, como a Redução de ruído. É uma decisão registrada; a etiqueta de procedência continua.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `edit_project`: gate leve, compressor 3:1, -16 LUFS e limitador a -1 dBTP
   Argumentos de exemplo: `{"name": "episodio", "op": {"type": "audio_effect", "action": "preset", "target": "audio.voiceover.0", "preset": "podcast_voice"}}`
2. `audio_effect_action`: sugerir o limiar do gate pelo trecho mais quieto
   Argumentos de exemplo: `{"name": "episodio", "effect": "noise_gate", "action": "analyze_noise", "target": "audio.voiceover.0"}`
3. `edit_project`: comprimir 4:1 a partir de -20 dB
   Argumentos de exemplo: `{"name": "episodio", "op": {"type": "audio_effect", "action": "add", "target": "audio.voiceover.0", "effect": {"type": "compressor", "threshold_db": -20, "ratio": 4}}}`
4. `qa_report`: conferir a saída
   Argumentos de exemplo: `{"name_or_path": "episodio"}`

## Equivalente na CLI

```powershell
dmaker audio effect preset projects/episodio/spec.json audio.voiceover.0 podcast_voice
dmaker audio effect action projects/episodio/spec.json noise_gate analyze_noise --target audio.voiceover.0
dmaker audio effect add projects/episodio/spec.json audio.voiceover.0 compressor --param threshold_db=-20 --param ratio=4
```

Tudo entra no histórico (`dmaker undo`).

## Como conferir

Renderize e rode `dmaker qa`, ou use **Medir** no item. Medido em sinal de teste: o compressor 4:1 a -20 dB baixou a LRA de uma fala de 15,3 para 9,8 LU; o limitador com teto de -1 dBTP não deixou nenhum dos seis sinais de teste passar do teto; o gate fechou o chiado em 12,0 e 24,0 dB (a redução pedida) e os 20 ms iniciais de cada palavra ficaram iguais; duas falas de -11,0 e -29,3 LUFS normalizadas a -16 mediram -16,0.

## Erros comuns

- **O gate corta o fim das palavras**: suba `hold_ms` e `release_ms`, ou baixe o limiar. **Analisar ruído** dá um ponto de partida (o limiar do gate é de pico, uns 11 dB acima do RMS do chiado).
- **O som ficou baixo depois do compressor**: suba `makeup_db`, ou normalize o loudness no fim.
- **O gate não aparece no master**: ele trabalha sobre as amostras do item; ponha-o na voz.
