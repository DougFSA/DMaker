# Fazer uma persona falar no vídeo

Tarefa `persona` do manual do DMaker. Põe uma personagem ilustrada (2D), um personagem 3D ou uma pessoa de verdade, a partir de uma foto (realista), falando no vídeo, em tela cheia ou num canto, com a boca seguindo a fala; nos dois primeiros também há piscadas, gestos e troca de expressão nas marcas que você escolher.

## Quando usar

Você quer um apresentador sem gravar ninguém: ele fala o texto que você escrever, com a voz que escolher. Uma **persona** é um cadastro (nome, tipo, voz e aparência) que vale em qualquer projeto; as prontas (`bia`, `caio`, `lia`) não mudam.

**Pedidos que levam a esta tarefa:**
- "Cria uma persona ilustrada chamada Marina com cabelo em coque"
- "Põe a persona no canto do vídeo falando por cima"
- "Faz um vídeo comigo falando este texto, a partir desta foto"

## O que perguntar antes

- Tipos: **2d** (desenhado pelo DMaker, não baixa nada) e **3d** (glTF; antes, `dmaker models download persona3d-mpfb`). Os dois desenham no Chromium (`dmaker setup --html`).
- Voz: da biblioteca (`dmaker voice list`); sem ela, a automática.
- **Realista** (uma foto que fala): sem placa NVIDIA e sem internet. Instale uma vez `pip install -e .[persona-realista]` e `dmaker models download persona-realista` (uns 2,3 GB). Foto .jpg ou .png, lado menor de 512 px; **use só foto sua ou de quem autorizou o uso da imagem**. Sem expressões nem gestos.
- Expressões do 2d e do 3d: `neutral`, `happy`, `sad`, `surprised`. Gestos: `nod`, `shake`, `tilt`, `wave`; o 3d tem ainda `handup`, `index`, `ok`, `thumbup`, `thumbdown`, `side`, `shrug`.
- Aparência: 2d `skin`, `hair_color`, `eye_color`, `outfit_color` (`#RRGGBB`), `hair_style` (`short`, `long`, `bun`); 3d `outfit_color`, `model`.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `create_persona`: cadastrar a persona
   Argumentos de exemplo: `{"name": "Marina", "kind": "2d", "voice": "dora", "appearance": {"hair_style": "bun"}}`
2. `create_persona`: cadastrar a realista pela foto
   Argumentos de exemplo: `{"name": "Rosto", "kind": "realistic", "voice": "dora", "photo": "C:/fotos/rosto.jpg"}`
3. `list_personas`: ver as personas e o que cada tipo aceita
   Argumentos de exemplo: `{}`
4. `render_project`: conferir um projeto com trecho persona
   Argumentos de exemplo: `{"name_or_path": "apresentacao", "preview": true}`

## Equivalente na CLI

```powershell
dmaker persona create "Marina" --kind 2d --voice dora --hair-style bun
dmaker persona create "Rafael" --kind 3d --outfit-color "#2E5E4E"
dmaker persona create "Rosto" --kind realistic --voice dora --photo C:
otos
osto.jpg
dmaker persona list
```

Em tela cheia, no `timeline`:

```json
{"type": "persona", "persona": "marina", "speech": {"text": "Olá, eu sou a Marina."},
 "marks": [{"at": 3.0, "expression": "happy"}, {"at": 5.5, "gesture": "wave"}]}
```

No canto, em `overlays` (`position`, `width`, `background`, `shape` como no picture-in-picture):

```json
{"type": "persona", "persona": "rafael", "start": 1.0, "speech": {"text": "Olha só."}, "background": "#D9E4F2"}
```

A realista no canto sempre sai recortada em `shape` (`rounded`, `circle` ou `rect`); nas outras, `shape` só vale com `background`. Com legenda no vídeo, a persona num canto de baixo fica acima da legenda. `marks` conta segundos desde o início da fala. A fala é `text` ou `audio`.

## Como conferir

`dmaker validate` confere a persona e as marcas;  o log do render e o campo `forecast` do `render_project` dizem até quanto a realista deve levar; `dmaker render NOME --preview --no-ui` e `dmaker qa` conferem a duração contra a fala real, em `persona_speech.json` na pasta do projeto.

## Erros comuns

- **"O personagem da persona 3D ainda não foi baixado"**: `dmaker models download persona3d-mpfb`.
- **Chromium ausente**: `dmaker setup --html`.

---
