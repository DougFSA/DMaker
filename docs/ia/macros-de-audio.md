# Tratar vários áudios com uma macro: salvar, aplicar a um item e a uma pasta

Tarefa `macros-de-audio` do manual do DMaker. Guarda uma cadeia de efeitos com nome (uma macro), põe a macro num item e a aplica a uma pasta de arquivos de áudio, num trabalho em segundo plano que retoma de onde parou.

## Quando usar

Você trata sempre do mesmo jeito: as 8 narrações de uma série, os áudios de WhatsApp de uma pasta. É o Tools > Macros e o Apply Macro to Files do Audacity.

**Pedidos que levam a esta tarefa:**
- "Limpa todas as narrações dessa pasta do mesmo jeito e deixa em MP3"
- "Salva essa cadeia de efeitos para usar nos próximos episódios"

## O que perguntar antes

- **Macro e predefinição são a mesma coisa**: uma lista de efeitos com nome, que pode levar a saída (`output`, como `{"preset": "audio/mp3"}`), só usada ao aplicar a arquivos. Num item, vira só a cadeia, editável depois.
- **Embutidas**: `clean_narration` (ronco, ruído, compressor, -16 LUFS e limitador), `clean_phone_recording` (a receita de áudio de celular), `mp3_standard` (pico a -1 dBFS, em MP3) e `ends_fade` (fades curtos nas pontas).
- **As suas** ficam uma por arquivo em `assets/macros` (todos os projetos) ou em `assets/brands/<marca>/macros` (só a marca; vale por cima da global), fora do git. O `effect-presets.json` do DMK-54 vira macros no primeiro uso e passa a `effect-presets.json.importado`, nunca apagado.
- Ao aplicar a arquivos, o original nunca muda. O formato vem de `--format` ou da macro. Só os efeitos da macro rodam, sem a normalização final da mistura.
- A retirada de estalos é lenta: 29 s para 8 s de áudio nesta máquina. Numa narração sintetizada, os efeitos podem apagar a marca d'água inaudível da voz (decisão de 03/11).

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `audio_effect_presets`: ver a cadeia da macro embutida
   Argumentos de exemplo: `{"action": "show", "id": "clean_narration"}`
2. `edit_project`: pôr a macro na voz gravada
   Argumentos de exemplo: `{"name": "episodio-12", "op": {"type": "audio_effect", "action": "preset", "target": "audio.voiceover.0", "preset": "clean_narration"}}`
3. `audio_effect_presets`: guardar a cadeia ajustada como macro
   Argumentos de exemplo: `{"action": "save", "label": "Voz da série", "project": "episodio-12", "target": "audio.voiceover.0", "output": {"preset": "audio/mp3"}}`
4. `apply_macro`: tratar a pasta inteira
   Argumentos de exemplo: `{"macro": "voz-da-serie", "inputs": ["D:/series/narracoes"], "out_dir": "D:/series/tratadas"}`
5. `apply_macro`: retomar depois de uma queda
   Argumentos de exemplo: `{"macro": "voz-da-serie", "inputs": ["D:/series/narracoes"], "out_dir": "D:/series/tratadas", "resume": true}`

## Equivalente na CLI

```powershell
dmaker audio macro list
dmaker audio macro save "Voz da série" --from-project episodio-12 --target audio.voiceover.0 --format mp3
dmaker audio macro run clean_narration D:/series/narracoes --out D:/series/tratadas --format mp3
dmaker audio macro run clean_narration D:/series/narracoes --out D:/series/tratadas --format mp3 --resume
dmaker audio macro status D:/series/tratadas
```

O estado fica em `<saída>/.dmaker-macro`, e cada arquivo só ganha o nome final ao terminar. Sem `--resume` tudo é refeito; com ele, só o que falta, o que falhou e o que mudou. Sai com erro se algum arquivo falhou.

## Como conferir

Com arquivos sintéticos: **Limpar narração** baixou o ruído de fundo 13,2 dB e entregou -16,0 LUFS; vinte arquivos de -31,8 a -11,3 LUFS saíram entre -16,20 e -16,00 LUFS; numa pasta de 6, a queda no quarto e o `--resume` refizeram só o 4º, o 5º e o 6º.

## Erros comuns

- **"não traz formato de saída"**: informe o formato (`--format mp3`).
- **"o original não é sobrescrito"**: escolha outra pasta de saída ou outro formato.
- **Um arquivo "falhou"**: o relatório diz o motivo e os outros seguem; corrija e use `--resume`. As subpastas da pasta de entrada não entram.
- **"é o nome de uma predefinição embutida"**: escolha outro nome.
