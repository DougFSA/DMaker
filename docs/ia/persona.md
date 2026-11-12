# Fazer uma persona falar no vídeo

Tarefa `persona` do manual do DMaker. Põe uma personagem ilustrada (2D) ou um personagem 3D falando no vídeo, em tela cheia ou num canto, com a boca seguindo a fala, piscadas, gestos e troca de expressão nas marcas que você escolher.

## Quando usar

Você quer um apresentador sem gravar ninguém: ele fala o texto que você escrever, com a voz que escolher, e vale em qualquer projeto. Uma **persona** é um cadastro (nome, tipo, voz e aparência); as prontas (`bia`, `caio`, `lia`) não mudam.

**Pedidos que levam a esta tarefa:**
- "Cria uma persona ilustrada chamada Marina com cabelo em coque"
- "Faz um vídeo com o Rafael (3D) apresentando o produto, com um aceno no meio"
- "Põe a persona no canto do vídeo falando por cima"

## O que perguntar antes

- Tipos: **2d** (desenhado pelo DMaker, não baixa nada) e **3d** (glTF animado pelo TalkingHead; antes, `dmaker models download persona3d-mpfb`, 36,8 MB, CC0). Os dois desenham no Chromium (`dmaker setup --html`).
- Voz: da biblioteca (`dmaker voice list`); sem ela, a automática.
- Expressões nos dois: `neutral`, `happy`, `sad`, `surprised`. Gestos nos dois: `nod`, `shake`, `tilt`, `wave`; o 3d tem ainda `handup`, `index`, `ok`, `thumbup`, `thumbdown`, `side`, `shrug`. Assim a spec de uma persona 2d vale ao trocá-la por 3d.
- Aparência 2d: `skin`, `hair_color`, `eye_color`, `outfit_color` (`#RRGGBB`) e `hair_style` (`short`, `long`, `bun`). Aparência 3d: `outfit_color` (a roupa é lisa nessa cor) e `model` (`mpfb` ou um `.glb` na pasta da persona).
- Render só com CPU: 30 s de fala em 1080x1920 levaram 19 min 32 s no 2d, 31 min 41 s no 3d e 5 min 36 s no 3d em um canto, na primeira vez e com a voz inclusa; o clipe fica em cache.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `create_persona`: cadastrar a persona
   Argumentos de exemplo: `{"name": "Marina", "kind": "2d", "voice": "dora", "appearance": {"hair_style": "bun"}}`
2. `list_personas`: ver as personas e o que cada tipo aceita
   Argumentos de exemplo: `{}`
3. `render_project`: conferir um projeto com trecho persona
   Argumentos de exemplo: `{"name_or_path": "apresentacao", "preview": true}`

## Equivalente na CLI

```powershell
dmaker persona create "Marina" --kind 2d --voice dora --hair-style bun
dmaker persona create "Rafael" --kind 3d --outfit-color "#2E5E4E"
dmaker persona list
```

Em tela cheia, no `timeline`:

```json
{"type": "persona", "persona": "marina", "speech": {"text": "Olá, eu sou a Marina."},
 "marks": [{"at": 3.0, "expression": "happy"}, {"at": 5.5, "gesture": "wave"}], "background": {"color": "#D9E4F2"}}
```

No canto, em `overlays` (`position`, `width`, `background` e `shape` como no picture-in-picture; a fala entra na mixagem e na legenda):

```json
{"type": "persona", "persona": "rafael", "start": 1.0, "speech": {"text": "Olha só."}, "background": "#D9E4F2"}
```

`marks` conta segundos desde o início da fala. A fala é `text` ou `audio`.

## Como conferir

`dmaker validate` confere a persona e as marcas; `dmaker render NOME --preview --no-ui` mostra o resultado e `dmaker qa` confere a duração contra a fala real, que fica em `persona_speech.json` na pasta do projeto e alimenta também a linha do tempo.

## Erros comuns

- **"O personagem da persona 3D ainda não foi baixado"**: `dmaker models download persona3d-mpfb`.
- **Chromium ausente**: `dmaker setup --html`.
- **Gesto ou expressão desconhecido**: a mensagem lista os que o tipo aceita.
- **Licença do 3D**: o `mpfb.glb` é CC0; a textura da roupa, com logotipo de terceiro, é trocada por uma cor lisa.

---
