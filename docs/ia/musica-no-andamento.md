# Pôr a música no andamento do projeto: BPM, compasso, régua em compassos e loop esticado

Tarefa `musica-no-andamento` do manual do DMaker. Dá um andamento ao projeto (BPM e compasso), mostra a régua em compassos, encaixa os cortes nos tempos, detecta o BPM de uma música ou loop e a estica, sem mudar o tom, para casar com a grade.

## Quando usar

Você monta a trilha de um reel a partir de loops, ou quer cortar o vídeo na batida. Com o **andamento do projeto** (`audio.tempo`) a régua mostra compassos, o Snap atrai para os tempos e o agente escreve `bar:9` no lugar de contar segundos. Com o **BPM da música** (`audio.music.bpm`) ela é esticada até o andamento do projeto. Sem `audio.tempo` nada disso existe e o projeto segue como sempre.

**Pedidos que levam a esta tarefa:**
- "Define o andamento do projeto em 120 BPM"
- "Qual é o BPM dessa música?"
- "Estica esse loop de 100 BPM para o andamento do projeto"

## O que perguntar antes

- Uma música no projeto (`audio.music`), de preferência um loop que começa no primeiro tempo.
- Para esticar é preciso o BPM da música: detecte-o ou informe-o. A razão entre o andamento do projeto e o da música fica entre 0,1 e 10; perto de 1 o som é melhor.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `edit_project`: dar ao projeto o andamento de 120 BPM em 4/4, com o tempo 1 em 0 s
   Argumentos de exemplo: `{"name": "reel-musical", "op": {"type": "tempo_set", "bpm": 120, "time_signature": "4/4", "offset": 0}}`
2. `audio_tempo`: medir o BPM e o primeiro tempo da música e gravá-los
   Argumentos de exemplo: `{"name": "reel-musical", "action": "detect", "apply": true}`
3. `edit_project`: esticar a música até o andamento do projeto, sem mudar o tom
   Argumentos de exemplo: `{"name": "reel-musical", "op": {"type": "music_tempo_set", "stretch_to_tempo": true}}`
4. `audio_tempo`: listar os inícios de compasso
   Argumentos de exemplo: `{"name": "reel-musical", "action": "grid", "level": "bar", "start": 0, "end": 20}`
5. `edit_project`: cortar o primeiro trecho exatamente no compasso 3
   Argumentos de exemplo: `{"name": "reel-musical", "op": {"type": "split", "index": 0, "at": "bar:3"}}`
6. `cut_on_beat`: propor o corte de cada fronteira no tempo mais perto da grade
   Argumentos de exemplo: `{"name": "reel-musical", "source": "grid", "tolerance": 0.2}`

## Equivalente na CLI

```powershell
dmaker audio tempo set projects\reel-musical\spec.json --bpm 120 --time-signature 4/4
dmaker audio tempo detect projects\reel-musical\spec.json --apply
dmaker audio tempo music projects\reel-musical\spec.json --stretch
dmaker audio tempo grid projects\reel-musical\spec.json --level bar
dmaker audio analyze cut-on-beat projects\reel-musical\spec.json --source grid
```

`dmaker audio tempo show` mostra o andamento do projeto e o da música, `clear` tira o do projeto e `music --bpm 100 --beat-offset 0.12` informa à mão o que a detecção mediria. Tudo entra no histórico (`dmaker undo`).

## Como conferir

- Um loop de 100 BPM num projeto de 120 BPM dura 100/120 do que durava, o tom não muda (440 Hz continua 440 Hz) e as batidas caem a cada 0,5 s a menos de 15 ms da grade.
- Numa Faixa de Ritmo gerada a 90, 120 e 128 BPM a detecção erra menos de 1 BPM.

## Erros comuns

- **"precisa do andamento do projeto (audio.tempo)"**: defina o andamento com `tempo_set` antes de usar `beat:<n>`, `bar:<n>` ou `--source grid`.
- **"stretch_to_tempo precisa do andamento da música"**: detecte ou informe o `bpm` da música antes.
- **Confiança baixa**: o ritmo é irregular; informe o BPM de ouvido. Acima de uns 155 BPM a detecção prefere a metade (87 em vez de 174) e traz a outra leitura.
- **"fora do que o esticamento aceita"**: o BPM da música deve estar pela metade ou pelo dobro.
- **A música entra um pouco depois do começo**: é o atraso (menos de um tempo) que põe o primeiro tempo dela na grade. Acerte o `beat_offset`.

---
