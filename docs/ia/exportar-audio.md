# Exportar o áudio de um projeto em WAV, MP3, FLAC e outros formatos

Tarefa `exportar-audio` do manual do DMaker. Grava só o som do projeto, sem imagem nenhuma, em WAV, MP3, FLAC, OGG, Opus, M4A ou AIFF, com as etiquetas do arquivo (artista, título, álbum...) e o volume de saída no alvo que você escolher (redes, podcast ou broadcast).

## Quando usar

Você tem uma narração, uma gravação de podcast ou uma trilha e quer o arquivo de áudio tratado. Um projeto de **saída de áudio** não precisa de trecho de vídeo: a duração vem da voz gravada, da narração e da música. Um projeto de vídeo também exporta só o áudio dele.

**Pedidos que levam a esta tarefa:**
- "Exporta a narração em MP3 de 192 kbps"
- "Me dá o áudio desse projeto em WAV de 24 bits a -16 LUFS"
- "Grava o episódio em MP3 com o artista e o título preenchidos"

## O que perguntar antes

- O formato: `audio/wav`, `audio/mp3`, `audio/flac`, `audio/ogg`, `audio/opus`, `audio/m4a` ou `audio/aiff` (`dmaker audio presets` mostra as opções: 16, 24 ou 32 bits nos formatos sem perda; CBR, VBR ou ABR nos com perda).
- O volume de saída (`--loudness`): `redes` (-14 LUFS), `podcast` (-16) ou `broadcast` (-23, o EBU R128), ou um número. Sem ele vale o `audio.target_lufs` do projeto.
- Para o projeto ser só de áudio, o `output.preset` é um formato de áudio e a `timeline` fica vazia.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `audio_presets`: ver os formatos, os padrões de cada um e os alvos de loudness
   Argumentos de exemplo: `{}`
2. `audio_export`: o episódio inteiro em MP3 de 192 kbps a -16 LUFS
   Argumentos de exemplo: `{"name": "meu-episodio", "preset": "audio/mp3", "loudness": "podcast", "bitrate_k": 192}`
3. `audio_export`: o mesmo em WAV de 24 bits a -14 LUFS
   Argumentos de exemplo: `{"name": "meu-episodio", "preset": "audio/wav", "bit_depth": 24, "loudness": "redes"}`
4. `export_project`: o projeto inteiro em dois formatos de uma vez
   Argumentos de exemplo: `{"name_or_path": "meu-episodio", "presets": ["audio/mp3", "audio/flac"]}`
5. `qa_report`: conferir o loudness e o pico do arquivo gravado
   Argumentos de exemplo: `{"name_or_path": "meu-episodio", "output": true}`

## Equivalente na CLI

```powershell
dmaker audio presets
dmaker audio export projects\meu-episodio\spec.json --preset audio/mp3 --bitrate 192 --loudness podcast
dmaker audio export projects\meu-episodio\spec.json --preset audio/wav --bit-depth 24 --out C:\audios\episodio.wav
```

Na spec: `"output": {"preset": "audio/mp3", "audio_format": {"bitrate_k": 192}, "metadata": {"artist": "Programa", "title": "Episódio 12", "track": "12"}}`. As etiquetas saem em ID3v2.3 no MP3 e em comentários Vorbis no FLAC, OGG e Opus; o AIFF só guarda título, artista e comentário. O arquivo vai para `output\projeto__audio-mp3.mp3`, ou para o `--out`.

## Como conferir

`dmaker validate` mostra o formato e a duração (e explica o que falta quando nada dá duração). O QA do arquivo (`dmaker qa projects\meu-episodio\spec.json --output output\meu-episodio__audio-mp3.mp3`) confere que não há faixa de imagem, a taxa e os canais, o loudness (alvo mais ou menos 1,5 LU) e o pico (até -1 dBTP). Num MP3 o volume medido pode ficar uns décimos de LU abaixo do alvo: é a codificação com perda.

## Erros comuns

- **"informe o formato do arquivo"**: o projeto é de vídeo; passe `--preset audio/mp3` (ou outro).
- **"MP3 é um formato com perda e não tem profundidade de bits"**: o formato recusa a opção que não existe nele (24 bits no MP3, taxa de bits no WAV); tire a opção.
- **O projeto não tem nada que dê duração**: ponha uma voz gravada (`audio.voiceover`), uma narração ou uma música.
- **O arquivo já existe**: o agente e a interface perguntam; pela CLI e pelo MCP ele é trocado.
