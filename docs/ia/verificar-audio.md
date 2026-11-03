# Verificar se um áudio foi gerado pelo DMaker

Tarefa `verificar-audio` do manual do DMaker. Diz se um arquivo de áudio ou vídeo tem voz gerada por IA pelo DMaker, lendo a etiqueta de procedência e, sem ela, a marca d'água inaudível do áudio.

## Quando usar

Você recebeu um arquivo e quer saber se a voz foi sintetizada pelo DMaker, ou quer conferir que uma narração sua saiu marcada. Só detecta o que o DMaker gerou: gravação de pessoa e música nunca são marcadas.

**Pedidos que levam a esta tarefa:**
- "Esse áudio foi gerado pelo DMaker?"
- "Confere se a narração está marcada como voz de IA"

## O que perguntar antes

- O arquivo (`.wav`, `.mp3`, `.m4a`, `.mp4`...). Um arquivo recodificado por uma rede social perde a etiqueta, mas a marca d'água do áudio pode sobreviver.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `verify_watermark`: ler a etiqueta de procedência
   Argumentos de exemplo: `{"path": "C:/videos/video.mp4", "check_audio": false}`
2. `verify_watermark`: analisar também a marca d'água do áudio
   Argumentos de exemplo: `{"path": "C:/videos/video.mp4", "check_audio": true}`

## Equivalente na CLI

```powershell
dmaker voice verify video.mp4
dmaker voice verify video.mp4 --audio
```

## Como conferir

A resposta tem três níveis. **Encontrada**: o detector reagiu e a assinatura "DM" de 16 bits confere em 15 ou mais bits. **Indício, inconclusivo**: o detector reagiu mas a assinatura não confere (é o que música e tons puros provocam; não prova nada). **Não encontrada**. Só "encontrada" conta como detecção. A etiqueta diz também em que trechos do arquivo a voz gerada entra (`trechos=33.10-34.42`), o que acha uma narração curta num vídeo longo; `--audio` analisa o áudio mesmo quando há etiqueta (cerca de meio segundo por segundo).

## Erros comuns

- **"Não encontrada" num vídeo que você sabe que usa voz do DMaker**: o arquivo foi recodificado (perdeu a etiqueta) ou a narração é curta num vídeo longo; rode com `--audio`.
- **"Indício"**: não conclui nada; tente o arquivo original.
- **Marca ausente nos meus áudios**: `DMAKER_WATERMARK=0` ou `--no-watermark` desligam a marca; confira o ambiente.

---
