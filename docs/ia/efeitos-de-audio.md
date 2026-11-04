# Aplicar efeitos de áudio em um item ou no master

Tarefa `efeitos-de-audio` do manual do DMaker. Põe uma cadeia de efeitos (Amplificar, Normalizar, Inverter, Reverter e Repetir) no som de qualquer item ou da mistura inteira, sem mexer no arquivo original.

## Quando usar

O áudio de um clipe, uma narração, uma voz gravada, a música ou o vídeo todo precisa de um tratamento: subir ou descer o volume, deixar o pico num valor, tocar um trecho ao contrário, repetir uma vinheta.

**Pedidos que levam a esta tarefa:**
- "Sobe o volume da entrevista em 6 dB, sem deixar clipar"
- "Normaliza a narração a -1 dB"
- "Toca os 2 primeiros segundos da música de trás para a frente"
- "Repete a vinheta duas vezes"
- "Normaliza a mistura final a -3 dB"

## O que perguntar antes

- O projeto (`name`) e o item: `timeline.N` (clipe), `overlays.N` (PiP), `audio.voiceover.N`, `audio.narration.N`, `audio.tracks.N`, `audio.music` ou `audio.master` (a mistura).
- A **ordem conta**: normalizar depois de amplificar mede o som já amplificado.
- O **Repetir** e os efeitos de tempo que mudam a duração (Mudar Velocidade e Tom, Mudar Andamento, Esticar Gradualmente e Paulstretch) só valem em voz gravada e em música, onde o item pode crescer; nos outros a spec os recusa. O Mudar Tom não muda a duração e vale em qualquer item.
- A normalização final de loudness continua valendo por cima do master.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `audio_effects`: ver os efeitos, os parâmetros e as faixas
   Argumentos de exemplo: `{}`
2. `edit_project`: amplificar a voz gravada em 6 dB sem deixar clipar
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "audio_effect", "action": "add", "target": "audio.voiceover.0", "effect": {"type": "amplify", "gain_db": 6, "prevent_clipping": true}}}`
3. `edit_project`: normalizar a mistura inteira a -3 dBFS
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "audio_effect", "action": "add", "target": "audio.master", "effect": {"type": "normalize", "peak_db": -3}}}`
4. `validate_project`: conferir a duração e os avisos
   Argumentos de exemplo: `{"name_or_path": "entrevista"}`

## Equivalente na CLI

```powershell
dmaker audio effects
dmaker audio effect add projects/entrevista/spec.json audio.voiceover.0 amplify --param gain_db=6 --param prevent_clipping=true
dmaker audio effect add projects/entrevista/spec.json audio.master normalize --param peak_db=-3
dmaker audio effect add projects/entrevista/spec.json audio.music reverse --start 0 --end 2
dmaker audio effect disable projects/entrevista/spec.json audio.voiceover.0 0
```

`dmaker audio effects` lista o catálogo (`--json` para o formato das ferramentas). Além de `add` e `disable`, existem `enable`, `remove`, `move` e `set` (muda parâmetros); `add` aceita `--position`, `--start`, `--end` e `--disabled`.

## Como conferir

Rode `dmaker validate` e olhe a duração: o Repetir numa voz gravada mostra o áudio com o tempo novo, e a trilha **VO** da linha do tempo (`timeline_view`) tem o item com o dobro do tamanho. Renderize com `dmaker render --preview` e `dmaker qa`, ou ouça a prévia da linha do tempo: ela usa a mesma cadeia do render. Para medir, amplificar 6 dB sobe o pico em 6,0 dB, e normalizar a -1 dBFS deixa o pico do item em -1,0 dBFS (com a tolerância de 0,1 dB).

## Erros comuns

- **"O efeito Repetir muda a duração do item e não vale aqui"**: o Repetir só vale em voz gravada (`audio.voiceover`) e em música (`audio.music`). O mesmo vale para os efeitos de tempo (veja "Mudar o tom, a velocidade e o andamento, e esticar o som"); no clipe, a velocidade do som e da imagem é o `speed` do próprio clipe.
- **Não ouvi diferença**: confira se o efeito está ligado (`enabled`), se o intervalo (`start`/`end`) cobre o trecho e se o item não está mudo.
- **O Normalizar não fez nada**: o trecho é silêncio, ou o intervalo está fora do item.
- **A primeira prévia ou o primeiro render demora**: o item é tratado uma vez e guardado em `cache/audio-fx` (uns 23 MB por minuto de estéreo); `dmaker clean` o apaga.
