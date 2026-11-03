# Importar áudio bruto

Tarefa `importar-bruto` do manual do DMaker. Converte um arquivo de áudio sem cabeçalho (PCM bruto, de um gravador ou de um programa) num WAV na pasta do projeto e o põe como voz gravada, como o "Importar dados brutos" do Audacity.

## Quando usar

Você tem um arquivo `.raw`, `.pcm` ou `.sw` que nenhum programa abre sozinho, porque ele não diz como ler os bytes. Aqui você diz: a codificação, a ordem dos bytes, os canais e a taxa de amostragem.

**Pedidos que levam a esta tarefa:**
- "Importa esse PCM de 16 bits, 48 kHz, mono"
- "Esse áudio bruto veio de um gravador; põe no projeto"

## O que perguntar antes

- Como o arquivo foi gravado. A codificação: `s8`, `u8`, `s16`, `u16`, `s24`, `s32`, `f32`, `f64`, `ulaw` ou `alaw`; a ordem dos bytes: `little` (a mais comum no Windows) ou `big`; os canais (1 mono, 2 estéreo) e a taxa em Hz.
- Se o arquivo tem um cabeçalho que você quer pular, quantos bytes (`--offset-bytes`), e se quer só uma parte dele (`--percent`).

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `import_raw_audio`: converter o PCM bruto em WAV e pô-lo como voz gravada
   Argumentos de exemplo: `{"name": "meu-episodio", "src": "C:/audios/gravacao.pcm", "encoding": "s16", "byte_order": "little", "channels": 1, "sample_rate": 48000, "start": 0}`
2. `validate_project`: conferir a duração que o áudio importado deu
   Argumentos de exemplo: `{"name_or_path": "meu-episodio"}`

## Equivalente na CLI

```powershell
dmaker audio import-raw meu-episodio C:\audios\gravacao.pcm --encoding s16 --byte-order little --channels 1 --sample-rate 48000
dmaker audio import-raw meu-episodio C:\audios\outro.raw --encoding f32 --sample-rate 44100 --start 12.5 --name outro
```

Um WAV que já existe só é trocado com `--overwrite`.

## Como conferir

`dmaker validate meu-episodio` mostra a duração. Um PCM de 16 bits, 48 kHz, mono de 2 s vira um WAV de 2 s no mesmo tom (o teste importa um seno de 440 Hz e mede o pico da frequência).

## Erros comuns

- **Só ruído ou chiado**: a ordem dos bytes ou a codificação está errada; tente `--byte-order big` ou outro `--encoding`.
- **Som lento ou rápido**: a taxa ou os canais estão errados (estéreo lido como mono dobra a velocidade aparente).
- **"o arquivo ... já existe na pasta do projeto"**: escolha outro `--name` ou use `--overwrite`.
- **"o arquivo não tem amostras depois do deslocamento inicial"**: o `--offset-bytes` passa do tamanho do arquivo.
