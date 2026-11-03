# Dividir um áudio em vários arquivos

Tarefa `dividir-audio` do manual do DMaker. Exporta um áudio longo em vários arquivos, um por região de marcador, um por trilha de som (os stems) ou só um trecho, como o "Export Multiple" do Audacity.

## Quando usar

Você tem um episódio com capítulos marcados e quer um arquivo por capítulo; ou precisa da voz, da música e dos efeitos separados para mixar em outro programa; ou quer só um pedaço do áudio.

**Pedidos que levam a esta tarefa:**
- "Divide o podcast num arquivo por capítulo, com o nome de cada um"
- "Me dá a narração e a música separadas"
- "Exporta só do marcador Entrevista até o marcador Fim"

## O que perguntar antes

- **Por região**: o projeto precisa de marcadores que sejam regiões (início e fim); veja "Marcar instantes e trechos com marcadores". O nome do arquivo é o texto do marcador sem os caracteres que o Windows não aceita; região sem texto, ou com um texto que outra repete, ganha o número dela (`regiao-03`, `Entrevista-04`). Cada arquivo chega ao alvo de loudness sozinho e leva o título da região e o número da faixa.
- **Pausas** (`--pauses`): o áudio entre as regiões (e antes da primeira) sai em arquivos `pausa-01`, `pausa-02`...
- **Por trilha**: saem `A1` (o som dos trechos), `NAR` (narrações), `VO` (vozes gravadas), `MUS` (música, já abaixada pelo ducking que ela sofre na mixagem) e `SFX` (efeitos), só as que o projeto tem.
- **Só um trecho**: `start` e `end` em segundos ou `marker:<texto>`; `marker:Introdução` nas duas pontas exporta exatamente aquela região.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `markers_regular`: criar uma região a cada 2 minutos, se ainda não há capítulos
   Argumentos de exemplo: `{"name": "meu-episodio", "interval": 120, "prefix": "Parte ", "digits": 2}`
2. `audio_export`: um MP3 por região, com o texto do marcador no nome
   Argumentos de exemplo: `{"name": "meu-episodio", "preset": "audio/mp3", "mode": "regions", "loudness": "podcast"}`
3. `audio_export`: um arquivo por trilha, que somados reproduzem a mixagem
   Argumentos de exemplo: `{"name": "meu-episodio", "preset": "audio/wav", "mode": "stems"}`
4. `audio_export`: só do marcador Entrevista até 5 minutos
   Argumentos de exemplo: `{"name": "meu-episodio", "preset": "audio/flac", "mode": "selection", "start": "marker:Entrevista", "end": 300}`

## Equivalente na CLI

```powershell
dmaker audio export projects\meu-episodio\spec.json --preset audio/mp3 --mode regions --loudness podcast --pauses
dmaker audio export projects\meu-episodio\spec.json --preset audio/wav --mode stems --tracks NAR,MUS --out-dir C:\audios\trilhas
dmaker audio export projects\meu-episodio\spec.json --preset audio/flac --mode selection --start marker:Entrevista --end 300
```

Os arquivos vão para uma pasta `output\projeto__audio-mp3__regioes` (ou `__trilhas`), ou para o `--out-dir`.

## Como conferir

A duração de cada arquivo é a da região, com diferença de milissegundos (um áudio de 10 minutos com 5 regiões sai em 5 arquivos com os tempos certos). Nos stems, todas as trilhas levam o mesmo ganho linear da normalização da mixagem, sem normalização nem limitador próprios, e a soma delas reproduz a mixagem (diferença abaixo de -70 dB nos testes). Os efeitos do master (cadeia de efeitos) são aplicados depois da soma e não entram nas trilhas: elas saem antes deles. Se a normalização da mixagem não é linear (pico ou variação de volume acima do limite), um aviso diz que a soma pode diferir.

## Erros comuns

- **"o projeto não tem regiões"**: marque trechos com início e fim, por exemplo com `markers_regular`.
- **"não existe o marcador ..." ou "há 2 marcadores chamados ..."**: use `marker:grupo/texto` ou renomeie um.
- **"o projeto não tem a trilha ..."**: só as trilhas que têm som saem; a mensagem lista as que existem.
- **Uma região começa depois do fim do áudio**: ela é pulada, com aviso; se passa do fim, é cortada no fim.
