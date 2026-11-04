# Analisar o áudio: estouro, nível, contraste, espectro e sons

Tarefa `analisar-audio` do manual do DMaker. Mede o som de um item ou da saída final sem mudar nada: acha o que estourou, confere se a fala se destaca da música, desenha o espectro e marca os sons e os silêncios.

## Quando usar

Você quer saber se a voz gravada chega estourada, quanto a fala está acima da música (o critério de acessibilidade pede 20 dB), em que frequência está um zumbido ou onde ficam os silêncios de uma gravação. São as funções do menu **Analisar** do Audacity e **não mudam o som**. O Marcar Sons escreve num **grupo de marcadores com nome próprio** (`sons`); rodar de novo troca só esse grupo, e os marcadores que você criou ficam como estão.

**Pedidos que levam a esta tarefa:**
- "A voz gravada está estourando? Mostra onde"
- "A fala está pelo menos 20 dB acima da música?"
- "Qual é a frequência desse zumbido?"
- "Marca os silêncios da entrevista"

## O que perguntar antes

- O projeto e **de onde vem o som**: um item como ele soa, com os efeitos e o ganho dele (`timeline.N`, `overlays.N`, `audio.voiceover.N`, `audio.narration.N`, `audio.music`, `audio.tracks.N`), a **saída final** já renderizada (`output`, o padrão) ou um arquivo solto (`file`). A narração precisa estar sintetizada.
- Os analisadores (`audio_analyzers` lista os parâmetros): `contrast`, `clipping`, `rms`, `spectrum`, `sounds`, `beats` e `samples`. `start` e `end` recortam o item, em segundos ou `marker:<texto>`.
- O limite é de uns 10 minutos de estéreo; acima disso, escolha um trecho.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `audio_analyzers`: ver os analisadores, os parâmetros e as faixas
   Argumentos de exemplo: `{}`
2. `audio_analyze`: achar os trechos estourados, com início e fim
   Argumentos de exemplo: `{"name": "entrevista", "analyzer": "clipping", "target": "audio.voiceover.0"}`
3. `audio_analyze`: marcar os silêncios no grupo pausas
   Argumentos de exemplo: `{"name": "entrevista", "analyzer": "sounds", "target": "audio.voiceover.0", "params": {"mode": "silences", "threshold_db": -35}, "group": "pausas"}`
4. `audio_analyze`: o espectro, com frequência e dB por linha
   Argumentos de exemplo: `{"name": "entrevista", "analyzer": "spectrum", "target": "audio.voiceover.0", "params": {"size": 4096}, "out": "C:/audios/espectro.csv"}`
5. `qa_report`: conferir o clipping e o contraste entre a fala e a música
   Argumentos de exemplo: `{"name_or_path": "entrevista"}`

## Equivalente na CLI

```powershell
dmaker audio analyze catalog
dmaker audio analyze run projects\entrevista\spec.json clipping --target audio.voiceover.0
dmaker audio analyze run projects\entrevista\spec.json rms --target audio.voiceover.0 --param window=1 --out C:\audios\rms.csv
dmaker audio analyze run projects\entrevista\spec.json spectrum --target audio.voiceover.0 --out C:\audios\espectro.png
dmaker audio analyze run projects\entrevista\spec.json sounds --target audio.voiceover.0 --param mode=silences --group pausas
```

`--target` aceita os itens acima ou `output` (ou `--file`, um arquivo solto). `--mark` e `--no-mark` ligam a gravação dos marcadores, `--group` dá o nome do grupo e `--out` exporta em `.csv`, `.txt`, `.png` (o gráfico do espectro) ou `.json`.

## Como conferir

Um tom de 1 kHz tem o pico do espectro na divisão de 1 kHz. Três estouros inseridos num áudio de teste saem com início e fim certos (±1 ms). Fala a -20 dBFS sobre fundo a -45 dBFS dá 25 dB de contraste e passa; com o fundo a -30 dBFS dá 10 dB e reprova com o aviso. No `qa_report` de um vídeo com a voz estourada, o achado cita o instante em que o estouro começa.

## Erros comuns

- **"não tem saída final renderizada"**: renderize antes, ou escolha um item (`--target`) ou um arquivo (`--file`).
- **"ainda não foi sintetizada"**: a narração precisa estar pronta; renderize o projeto antes.
- **"informe o nome do grupo"**: o grupo vazio é a trilha da pessoa e nunca é trocado; dê um nome com `group`.
- **Nenhum marcador saiu**: o limiar não pegou nada; mude-o (por exemplo, -40 dB).
