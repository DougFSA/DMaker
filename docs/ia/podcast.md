# Fazer um episódio de podcast

Tarefa `podcast` do manual do DMaker. Monta um episódio só de áudio com a gravação entre uma música de abertura e uma de encerramento, normalizado a -16 LUFS e gravado como MP3 com as etiquetas do episódio.

## Quando usar

Você gravou o episódio e quer o arquivo final para publicar, com a vinheta no começo e no fim e o volume no padrão de podcast. A voz passa por uma Redução de ruído automática e moderada (8 dB, `limpeza` ligada por padrão): o perfil é o trecho mais quieto da gravação, e uma gravação sem pausa só de ruído (ou já limpa) sai como entrou.

**Pedidos que levam a esta tarefa:**
- "Faz o episódio 12 do podcast com essa gravação e a vinheta"
- "Monta o MP3 do episódio com abertura, voz e encerramento a -16 LUFS"

## O que perguntar antes

- A gravação (`voz`) e o arquivo da música (`trilha`): os dois são obrigatórios, e o modelo não tem caminho padrão. A abertura toca o começo da música por `abertura` segundos (padrão 8) e o encerramento toca o final dela por `encerramento` segundos (padrão 10). A voz entra depois da abertura.
- As etiquetas do episódio: `artista`, `titulo`, `album`, `faixa`, `ano`, `genero` (padrão Podcast) e `comentario`; o que ficar vazio vale o modelo da marca (`marca`), se ela tiver.
- A limpeza da voz (`limpeza`, padrão ligada): põe um efeito `noise_reduction` automático de 8 dB na voz gravada. `limpeza=false` deixa a voz como foi gravada. Para um chiado forte, pegue um perfil de um trecho só de ruído e ajuste o efeito (tarefa "Tirar o chiado de uma gravação (Redução de ruído)").

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `new_from_template`: criar o projeto do episódio
   Argumentos de exemplo: `{"template": "podcast", "name": "ep12", "params": {"voz": "C:/audios/ep12.wav", "trilha": "C:/audios/tema.mp3", "titulo": "Episódio 12", "artista": "Meu Programa", "faixa": "12"}}`
2. `validate_project`: conferir a duração: abertura, voz e encerramento
   Argumentos de exemplo: `{"name_or_path": "ep12"}`
3. `audio_export`: gravar o MP3 a -16 LUFS com as etiquetas
   Argumentos de exemplo: `{"name": "ep12"}`

## Equivalente na CLI

```powershell
dmaker new-from-template podcast ep12 --param voz=C:\audios\ep12.wav --param trilha=C:\audios\tema.mp3 --param titulo="Episódio 12" --param artista="Meu Programa" --param faixa=12
dmaker audio export ep12
```

Sem `--preset`, vale o formato do modelo (`audio/mp3`); `--param formato=audio/m4a` troca o formato, `--param loudness=-14` o alvo e `--param limpeza=false` desliga a Redução de ruído da voz.

## Como conferir

`dmaker validate ep12` mostra a duração (abertura + voz + encerramento). O arquivo sai em `output\ep12__audio-mp3.mp3` com as etiquetas no `ffprobe` e o volume em -16 LUFS (medido pelo relatório de QA).

## Erros comuns

- **Faltam parâmetros obrigatórios**: o modelo pede `voz` e `trilha`, os dois arquivos de áudio.
- **A música cobre a voz no começo**: a música abaixa sob a voz (ducking); se ainda atrapalha, aumente a `abertura` para a voz entrar depois dela.
- **O episódio ficou longo demais ou curto**: a duração é a da gravação mais a abertura e o encerramento; ajuste os dois.
- **A voz ficou abafada**: a limpeza automática achou "ruído" onde havia som de fundo que faz parte do episódio; passe `limpeza=false` e, se quiser, ponha a Redução de ruído com um perfil que você escolher.
