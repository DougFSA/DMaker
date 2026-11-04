# Fazer fades: curva, fade parcial e fade de estúdio

Tarefa `fades` do manual do DMaker. Abre e fecha o som de um item com a curva que você escolher, abaixa sem chegar ao silêncio e fecha como fim de música de rádio, sem mexer no arquivo original.

## Quando usar

O som precisa entrar e sair com jeito, a música deve abaixar para 40% e não sumir, ou o fim do vídeo pede um fade de estúdio.

**Pedidos que levam a esta tarefa:**
- "Faz um fade out de 3 segundos na música, em curva de seno"
- "Abaixa a música para 40% a partir de 20 segundos, sem sumir"
- "Fecha o fim do vídeo como música de rádio, com os agudos sumindo junto"

## O que perguntar antes

- O projeto (`name`) e o item (`target`): `timeline.N` (o som do clipe), `overlays.N`, `audio.voiceover.N`, `audio.narration.N`, `audio.music`, `audio.tracks.N` ou, para o fim da mistura, `audio.master`.
- **Fade In e Fade Out** (`fade_in`, `fade_out`): a `duration` conta da borda do item; com `start` e `end` o fade ocupa o intervalo e a duração não conta. As curvas são `linear`, `logarithmic` (abre depressa e achata), `exponential` (quase mudo até o fim), `sine` (S suave) e `quadratic`. O fade da música (`fade_in` e `fade_out` de `audio.music`) e o `audio_fade` do clipe seguem como sempre.
- **Fade Ajustável** (`adjustable_fade`): `start_gain` e `end_gain` em `percent` ou `db`, a `shape` e o `mid_adjust` (de -100 a 100: positivo demora a abrir, negativo abre logo). As predefinições (`fade_linear_in`, `fade_cosine_out`, `fade_s_curve_in`, `fade_partial`, `fade_soft_down`...) são pontos de partida: cada uma põe um Fade Ajustável editável.
- **Studio Fade Out** (`studio_fade_out`): o volume fecha em curva quadrática e um passa-baixa desce de 20 kHz até o `final_cutoff` (200 Hz) em oitavas iguais. Até o fade começar o som passa intacto. Vale no item e no `audio.master`.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `edit_project`: fade out de 3 segundos na música, em S
   Argumentos de exemplo: `{"name": "reels", "op": {"type": "audio_fade", "target": "audio.music", "side": "out", "duration": 3, "curve": "sine"}}`
2. `edit_project`: Fade Ajustável de 100% a 40%
   Argumentos de exemplo: `{"name": "reels", "op": {"type": "audio_effect", "action": "preset", "target": "audio.music", "preset": "fade_partial"}}`
3. `edit_project`: fecha a mistura como fim de música de rádio
   Argumentos de exemplo: `{"name": "reels", "op": {"type": "audio_effect", "action": "add", "target": "audio.master", "effect": {"type": "studio_fade_out", "duration": 3}}}`
4. `qa_report`: conferir a saída
   Argumentos de exemplo: `{"name_or_path": "reels"}`

## Equivalente na CLI

```powershell
dmaker audio fade projects/reels/spec.json audio.music out 3 --curve sine
dmaker audio effect preset projects/reels/spec.json audio.music fade_partial
dmaker audio effect add projects/reels/spec.json audio.master studio_fade_out --param duration=3
```

Tudo entra no histórico (`dmaker undo`).

## Como conferir

Renderize e rode `dmaker qa`. Medido em sinais de teste: o Fade Ajustável de 100% a 40% terminou 7,7 dB abaixo do começo, sem nunca passar de 40% do nível para baixo; as cinco curvas saíram monotônicas, distintas e a no máximo 0,02 da conta pura; o Studio Fade Out ficou 78 dB abaixo de um fade linear de mesma duração na energia acima de 5 kHz no fim do fade.

## Erros comuns

- **O fade de um item com intervalo não termina onde eu queria**: com `start` e `end` o fade ocupa o intervalo inteiro e a `duration` não conta.
- **A alça de fade não aparece**: ela existe nas trilhas A1, VO, NAR e MUS. Uma faixa externa (A2...) é uma janela de um arquivo longo; ponha o fade nela pelo bloco de efeitos.
- **O fade ficou brusco no fim**: a curva `exponential` fica quase muda até o fim; troque por `sine` ou `linear`.
