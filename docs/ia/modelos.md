# Ver, baixar e apagar os modelos de IA

Tarefa `modelos` do manual do DMaker. Mostra cada modelo de IA que o DMaker baixa (tamanho no disco, licença, para que serve), baixa antes de precisar, apaga o que não usa e limpa as sobras.

## Quando usar

O disco está enchendo, você vai trabalhar sem internet e quer baixar tudo antes, ou quer saber a licença de cada modelo. Os modelos baixam sozinhos na primeira vez que uma função precisa deles.

**Pedidos que levam a esta tarefa:**
- "Quanto espaço os modelos ocupam?"
- "Baixa o modelo de voz antes de eu ficar sem internet"
- "Apaga os modelos que eu não uso"

## O que perguntar antes

- Confira o espaço livre do disco antes de baixar os grandes (o OmniVoice tem cerca de 3 GB).
- Apagar um modelo desliga as funções que dependem dele; o aviso diz quais. Perguntar antes de apagar.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `models`: ver estado, tamanho, licença e uso de cada modelo
   Argumentos de exemplo: `{"action": "list"}`
2. `models`: baixar um modelo em segundo plano
   Argumentos de exemplo: `{"action": "download", "model_id": "omnivoice"}`
3. `models`: apagar um modelo (só com a confirmação do usuário)
   Argumentos de exemplo: `{"action": "remove", "model_id": "kokoro-int8", "confirm": true}`

## Equivalente na CLI

```powershell
dmaker models list
dmaker models download omnivoice
dmaker models remove kokoro-int8
dmaker models prune
```

`remove` e `prune` perguntam antes (`--yes` pula a pergunta). Os modelos: `omnivoice`, `kokoro-fp32`, `kokoro-int8`, `demucs-htdemucs`, `audioseal`, `diarization-sherpa`, `openvoice-v2`, `rvm-resnet50`, `rvm-mobilenetv3` e os `whisper-*` (tiny a large-v3).

## Como conferir

`dmaker models list` mostra o estado (`instalado`, `parcial` ou `ausente`) e o tamanho medido em disco; um modelo `parcial` ficou pela metade e `download` completa. Na interface nova, é a coluna **Estado** da tela **Modelos**: **baixado**, **incompleto** (o mesmo que `parcial`) ou **não baixado** (`ausente`). Os modelos ficam em `cache/models`.

## Erros comuns

- **Download parou**: rode `download` de novo, que retoma e confere que ficou inteiro (hash). Na interface nova, o motivo aparece em vermelho na linha do modelo; clique em **Continuar download**.
- **Uma função parou de funcionar**: apagou o modelo dela; baixe de novo.
- **Sobrou pasta em `cache/models`**: é sobra de um modelo antigo; `prune` apaga. Na interface nova, é o cartão **Sobras**, com **Apagar sobras**.
- **Apagar sobras está desligado ou o servidor recusa**: há um download em andamento; espere terminar.

---
