# Cortar os clipes no ritmo da música

Tarefa `cortar-no-ritmo` do manual do DMaker. Acha as batidas da música e anda o corte entre cada par de clipes para a batida mais perto, sem mudar a duração do vídeo.

## Quando usar

Você quer que as trocas de imagem caiam nos tempos da música. O Achar Batidas marca as batidas (limiar sobre a energia, com distância mínima entre elas) e diz o andamento em BPM; o **cortar no ritmo** propõe, para cada fronteira entre clipes, a batida mais perto dentro de uma tolerância.

**Pedidos que levam a esta tarefa:**
- "Acha as batidas da música"
- "Corta os clipes no ritmo da música"
- "Qual é o andamento dessa música?"

## O que perguntar antes

- Música no projeto (`audio.music`). A análise vale para o trecho que toca no vídeo.
- Só andam as fronteiras entre dois **clipes de vídeo** e sem transição; as outras ficam como estão, com o motivo na lista.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `audio_analyze`: marcar as batidas no grupo batidas e ver o andamento
   Argumentos de exemplo: `{"name": "clipe-musical", "analyzer": "beats", "target": "audio.music"}`
2. `cut_on_beat`: propor o corte de cada fronteira na batida mais perto
   Argumentos de exemplo: `{"name": "clipe-musical", "tolerance": 0.2}`
3. `cut_on_beat`: andar os cortes
   Argumentos de exemplo: `{"name": "clipe-musical", "tolerance": 0.2, "apply": true}`

## Equivalente na CLI

```powershell
dmaker audio analyze run projects\clipe-musical\spec.json beats --target audio.music
dmaker audio analyze cut-on-beat projects\clipe-musical\spec.json --tolerance 0.2
dmaker audio analyze cut-on-beat projects\clipe-musical\spec.json --apply
```

`--group` usa as batidas de um grupo de marcadores que já existe, no lugar da análise. `--source grid` usa os tempos do andamento do projeto (`audio.tempo`) no lugar das batidas medidas: o corte cai exatamente na grade (ver "Pôr a música no andamento do projeto").

## Como conferir

Numa faixa de 120 BPM há uma batida a cada 0,5 s (±20 ms). Depois de `--apply`, `dmaker validate` mostra a mesma duração e a lista diz quanto cada corte andou; um clipe cujo arquivo acaba antes da batida avisa que o corte parou.

## Erros comuns

- **"nenhuma batida a menos de ... s"**: aumente a `tolerance` ou baixe o limiar do Achar Batidas (`threshold_percent`).
- **"há uma transição entre os trechos"**: troque a transição por corte seco para essa fronteira andar.
- **"um trecho só"**: o cortar no ritmo precisa de pelo menos dois clipes.

---
