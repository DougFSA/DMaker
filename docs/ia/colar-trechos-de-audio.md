# Copiar, colar, dividir e juntar trechos de áudio

Tarefa `colar-trechos-de-audio` do manual do DMaker. Copia um trecho do som de um item e cola noutro instante como uma voz gravada nova, divide e junta vozes gravadas e apara fora da seleção, tudo apontando para o mesmo arquivo, sem copiá-lo.

## Quando usar

Repetir uma frase em outro ponto, tirar uma fala do meio de uma gravação, separar uma voz em duas para tratar cada metade, ficar só com um trecho de uma gravação longa.

**Pedidos que levam a esta tarefa:**
- "Copia os 3 segundos da fala que começam em 20 s e cola em 40 s"
- "Duplica essa fala logo depois"
- "Divide a voz gravada em 25 segundos"
- "Junta as duas metades de novo"
- "Fica só com o trecho de 5 a 40 segundos da gravação"

## O que perguntar antes

- O item de origem (`target`) e os tempos em segundos do **vídeo final** (`marker:<texto>` vale). Copia-se de um clipe, PiP, voz gravada ou música; a narração, a faixa externa e a mistura não são arquivos para copiar.
- O trecho colado é uma **voz gravada nova** (`audio.voiceover`), com o volume, o pan e os efeitos do original recortados para o trecho.
- **Dividir e juntar** valem só para a voz gravada. Juntar exige duas vozes vizinhas do mesmo arquivo com trechos seguidos; senão recusa dizendo o motivo.
- Um efeito que troca o tempo do som (Repetir, Reverter, Cortar) impede dividir, aparar e copiar: tire-o antes.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `edit_project`: copiar 3 s de fala e colar em outro ponto
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "audio_paste", "target": "audio.voiceover.0", "start": 20, "end": 23, "at": 40}}`
2. `edit_project`: dividir a voz gravada em 25 s
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "audio_split", "target": "audio.voiceover.0", "at": 25}}`
3. `edit_project`: juntar de novo as duas metades
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "audio_join", "target": "audio.voiceover.0"}}`
4. `edit_project`: ficar só com o trecho de 5 a 40 s
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "audio_trim", "target": "audio.voiceover.0", "start": 5, "end": 40}}`

## Equivalente na CLI

```powershell
dmaker audio paste projects/entrevista/spec.json audio.voiceover.0 --start 20 --end 23 --at 40
dmaker audio duplicate projects/entrevista/spec.json audio.voiceover.0
dmaker audio split projects/entrevista/spec.json audio.voiceover.0 --at 25
dmaker audio join projects/entrevista/spec.json audio.voiceover.0
dmaker audio trim projects/entrevista/spec.json audio.voiceover.0 --start 5 --end 40
```

## Como conferir

Veja os itens na `timeline_view` (trilha **VO**) e ouça a prévia. Medido: a fala colada tem correlação acima de 0,99 com o trecho original e o mesmo nível; dividir e juntar de novo devolve a spec idêntica.

## Erros comuns

- **"troca o tempo do som de lugar"**: o item tem Repetir, Reverter ou Cortar; tire o efeito (`audio_effect remove`) antes.
- **"não são seguidos"** ou **"não se encostam"** ao juntar: os trechos do arquivo ou da linha do tempo não se continuam.
- **Copiar de um clipe com velocidade diferente de 1** é recusado: o item novo tocaria na velocidade normal.
- **"só vale para a voz gravada"**: no clipe o corte é o `split`, que corta imagem e som juntos.
