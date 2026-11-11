# Tirar o chiado de uma gravação (Redução de ruído)

Tarefa `reduzir-ruido` do manual do DMaker. Tira o chiado de fundo de um item a partir de um perfil de ruído, como o Audacity, sem mexer no arquivo original.

## Quando usar

A gravação de celular tem chiado, a ventoinha do notebook aparece nas pausas, ou o áudio de WhatsApp está sujo.

**Pedidos que levam a esta tarefa:**
- "Tira o chiado dessa gravação"
- "Limpa o ruído de fundo da entrevista"
- "Reduz o ruído usando o começo da gravação, que só tem chiado"

## O que perguntar antes

- O projeto (`name`) e o item (`target`): `timeline.N` (o som do clipe), `overlays.N`, `audio.voiceover.N`, `audio.tracks.N` ou `audio.music`. Não vale na narração sintetizada nem no `audio.master_effects`.
- É em dois passos, como no Audacity. Primeiro o **perfil**: um trecho que só tem chiado (0,1 s ou mais, sem fala), em segundos da linha do tempo ou `marker:<texto>`. Depois o efeito `noise_reduction`: `reduction_db` (12), `sensitivity` (6), `smoothing_bands` (3) e `profile`, o nome do perfil.
- `profile: "auto"` usa o trecho mais quieto do item, e só se ele for uma pausa de verdade (10 dB abaixo da média). Numa fala sem pausas, ou num tom contínuo, o automático não tira nada.
- O perfil fica em `audio.noise_profiles` (`{nome: {target, start, end}}`, tempos do item) e entra no desfazer. O espectro é medido na hora do render e nunca vai para a spec.
- A narração sintetizada e a voz trocada têm marca d'água inaudível: a redução pode apagá-la do trecho. É uma decisão registrada; a etiqueta de procedência continua.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `noise_profile`: guardar o trecho só de chiado e ver o nível por banda
   Argumentos de exemplo: `{"name": "entrevista", "profile": "sala", "target": "audio.voiceover.0", "start": 0.2, "end": 1.4}`
2. `edit_project`: tirar 12 dB do chiado
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "audio_effect", "action": "add", "target": "audio.voiceover.0", "effect": {"type": "noise_reduction", "profile": "sala", "reduction_db": 12}}}`
3. `qa_report`: conferir a saída
   Argumentos de exemplo: `{"name_or_path": "entrevista"}`

## Equivalente na CLI

```powershell
dmaker audio noise-profile add projects/entrevista/spec.json sala audio.voiceover.0 --start 0.2 --end 1.4
dmaker audio effect add projects/entrevista/spec.json audio.voiceover.0 noise_reduction --param profile=sala --param reduction_db=12
dmaker audio noise-profile list projects/entrevista/spec.json
```

`noise-profile add` sem `--start` e `--end` pega o trecho mais quieto; `noise-profile remove` apaga um perfil que nenhum efeito usa. Tudo entra no histórico (`dmaker undo`).

## Como conferir

Ouça o **Comparar antes e depois** ou renderize e rode `dmaker qa`. Medido em sinal de teste: o chiado a -45 dBFS cai 11,99 dB com 12 dB de redução, a fala muda menos de 0,2 dB e a transcrição fica igual.

## Erros comuns

- **"o trecho de ruído tem 0.020 s"**: o perfil precisa de 0,1 s ou mais só de chiado. Com fala dentro, a voz fica abafada.
- **A voz ficou metálica**: baixe `reduction_db` (12 a 18 dB é o limite) ou suba `smoothing_bands`.
- **Ficou chiado**: suba `sensitivity`, ou use um perfil de um trecho mais longo e mais limpo.
- **O automático não tirou nada**: a gravação não tem pausa só de ruído; dê o trecho.
- **"o perfil de ruído 'x' não existe"**: `dmaker audio noise-profile list` mostra os que existem.
