# Editar o áudio na onda: selecionar, tocar, aplicar efeito e desenhar

Tarefa `editar-na-onda` do manual do DMaker. Abre um item de áudio numa onda grande, como o Audacity: seleciona com o mouse, toca em loop, aplica um efeito com prévia e comparação do antes e depois, desenha o envelope e as amostras, e desfaz com Ctrl+Z.

## Quando usar

Você quer ver o som, ouvir só um trecho, silenciar uma tosse, normalizar uma frase ou consertar um estalo olhando a onda, em vez de escrever tempos. Tudo vira uma edição comum da spec (os efeitos e operações das outras tarefas desta seção), que o desfazer e o Salvar do editor conhecem.

**Pedidos que levam a esta tarefa:**
- "Quero ver a onda da voz gravada e ouvir só um trecho dela"
- "Aplica o Normalizar só na segunda frase e me deixa ouvir antes e depois"
- "Silencia essa tosse"
- "Põe um marcador nesse trecho"

## O que perguntar antes

- **Interface nova, Editor.** Duplo clique num item de áudio da linha do tempo (o som do clipe, a voz gravada, a narração, a música ou uma faixa externa), ou escolha o item e clique em **Editar áudio**. O painel **Áudio** abre **no lugar da linha do tempo**, e **Voltar à linha do tempo** a traz de volta. Ele não é um painel do layout, para não mexer nos layouts salvos nem na interface clássica (que não o tem).
- Mostra o som **como ele soa**, com os efeitos e o volume do item (um som **mono** aparece nos dois canais, 3 dB abaixo, como na mixagem). Um áudio de **1 hora** abre em uns 2 s (WAV; os comprimidos mostram o andamento) e, com os picos em cache, em milésimos de segundo. O tempo da onda é o do **item**. Numa **faixa externa** valem os efeitos, mas não silenciar, cortar, dividir nem marcar.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `edit_project`: normalizar só a seleção, como a janela de efeito do painel
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "audio_effect", "action": "add", "target": "audio.voiceover.0", "effect": {"type": "normalize", "peak_db": -1, "start": 7.2, "end": 9.2}}}`
2. `edit_project`: silenciar a tosse (Ctrl+L no painel)
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "audio_silence", "target": "audio.voiceover.0", "start": 12.5, "end": 14.5}}`
3. `edit_project`: pôr um marcador na região (Ctrl+B no painel)
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "marker_add", "start": 20, "end": 24, "text": "frase"}}`
4. `edit_project`: ouvir só a voz gravada (o botão S do cabeçalho da trilha)
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "track_set", "track": "VO", "solo": true}}`
5. `undo_edit`: desfazer a última edição (Ctrl+Z no painel)
   Argumentos de exemplo: `{"name": "entrevista"}`

## Equivalente na CLI

Não existe tela de onda na linha de comando: o painel faz a edição de sempre, e a CLI a oferece pelos mesmos comandos.

```powershell
dmaker audio effect add projects/entrevista/spec.json audio.voiceover.0 normalize --param peak_db=-1 --start 7.2 --end 9.2
dmaker audio silence projects/entrevista/spec.json audio.voiceover.0 --start 12.5 --end 14.5
dmaker audio track projects/entrevista/spec.json VO --solo
dmaker markers add projects/entrevista/spec.json --start 20 --end 24 --text frase
dmaker undo projects/entrevista/spec.json
```

## Como conferir

Medido: o **Normalizar** de uma seleção de 2 s leva o pico dela a -1,00 dBFS, e o render do mesmo projeto soa igual à prévia (diferença máxima de -84 dBFS). Espaço toca exatamente a seleção, e o loop volta ao começo na mesma amostra em que o fim chega.

## Erros comuns

- **"Selecione um trecho na onda"**: Silenciar, Cortar e o efeito com intervalo pedem uma seleção.
- **"Dividir o som vale para a voz gravada"**: nos outros itens, a divisão é o corte da linha do tempo (S).
- **"Prévia aproximada"**: o efeito mede o item inteiro e o item é longo; selecione um trecho e a prévia fica igual ao render.
- **O Desenho não deixa desenhar**: aproxime o zoom até as amostras virarem pontos, e confira se o áudio está a 48 kHz.
