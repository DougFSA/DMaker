# Cruzar o som de dois clipes ou de duas trilhas (crossfade)

Tarefa `crossfades` do manual do DMaker. Cruza o som de dois clipes vizinhos sem trocar a imagem, que continua cortando seca (J-cut e L-cut), ou faz uma trilha sumir enquanto outra entra, sem mexer nos arquivos originais.

## Quando usar

A imagem troca num corte seco mas o som do clipe anterior deve continuar um pouco por cima do seguinte (L-cut), ou o do seguinte começar antes da imagem (J-cut); ou a faixa do DJ deve sumir enquanto a música entra.

**Pedidos que levam a esta tarefa:**
- "Cruza o som do clipe 1 com o do clipe 2 por meio segundo, sem trocar a imagem"
- "Faz a faixa do DJ sumir enquanto a música entra, entre 60 e 64 segundos"

## O que perguntar antes

- **Entre clipes** (`audio_crossfade` no clipe que entra): o som cruza por `duration` segundos, metade antes e metade depois do corte, com a **sobra da fonte** além do ponto de saída do clipe anterior e antes do ponto de entrada do seguinte. Sem sobra suficiente o cruzamento encurta para o que houver e o `validate_project` e o render avisam. Só vale em corte seco entre dois clipes de vídeo (com uma transição de imagem, o som já cruza por ela). O som emprestado do vizinho é o da câmera e o das faixas externas dele como foram gravados, sem os efeitos do vizinho; com `audio_offset` ou `audio_mode` diferente de `original` o cruzamento é desligado, com aviso.
- **Entre trilhas** (`audio_crossfade_tracks`): grava um Fade Ajustável de saída num item e um de entrada no outro, no mesmo intervalo, com as curvas casadas (`kind`: `constant_gain`, `constant_power_1`, `constant_power_2` ou `custom`, com `curve` e `mid_adjust`). Os dois itens precisam cobrir o intervalo inteiro. Não muda a mixagem e é um passo só do histórico.
- **Qual tipo escolher**: dois sons **diferentes** (uma fala e outra, uma música e outra) pedem **potência constante** (`constant_power_1`, o padrão, ou `constant_power_2`): as potências somam e o volume não cai no meio. Com dois tons de mesmo nível e frequências diferentes, o nível variou 0,03 dB no meio; o ganho constante afundou 3 dB. O **mesmo som em fase dos dois lados** (dois microfones na mesma fala, um corte contínuo na mesma tomada) pede **ganho constante**: a potência constante **sobe 3 dB** no meio (medido: +3,0 dB) e o ganho constante fica plano (0,0 dB). É física, não defeito.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `edit_project`: cruzar o som do clipe 1 com o do 2 sem trocar a imagem
   Argumentos de exemplo: `{"name": "reels", "op": {"type": "audio_crossfade_clips", "index": 1, "duration": 0.5, "curve": "constant_power_1"}}`
2. `edit_project`: a faixa do DJ some enquanto a música entra
   Argumentos de exemplo: `{"name": "casamento", "op": {"type": "audio_crossfade_tracks", "out_target": "audio.tracks.0", "in_target": "audio.music", "start": 60, "end": 64, "kind": "constant_power_1"}}`
3. `validate_project`: ver os avisos (um crossfade que encurtou)
   Argumentos de exemplo: `{"name_or_path": "reels"}`

## Equivalente na CLI

```powershell
dmaker audio crossfade-clips projects/reels/spec.json 1 0.5 --curve constant_power_1
dmaker audio crossfade-tracks projects/casamento/spec.json audio.tracks.0 audio.music --start 60 --end 64
```

Tudo entra no histórico (`dmaker undo`).

## Como conferir

Renderize e rode `dmaker qa`. Medido com um quadro claro e outro escuro, cada um com um bipe: num corte seco com crossfade de som de 0,5 s a imagem trocou no quadro 120 (4,0 s a 30 quadros por segundo), exatamente no corte, e os dois bipes se cruzaram entre 3,75 e 4,25 s, a 0,71 do nível cada um no corte.

## Erros comuns

- **"O crossfade de som de 0,5 s encurtou para 0,20 s"**: a fonte não tem som o bastante além do corte. Afaste o ponto de saída do clipe anterior ou o de entrada do seguinte do começo e do fim do arquivo.
- **"O crossfade de som é ignorado: o corte tem transição de imagem"**: ponha a transição do clipe em `cut`, ou use só a transição.
- **O volume cai ou sobe no meio do cruzamento**: veja "Qual tipo escolher" acima e troque o tipo.
