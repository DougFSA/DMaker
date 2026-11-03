# Pôr o texto atrás da pessoa

Tarefa `texto-atras` do manual do DMaker. Faz o título grande passar atrás de quem fala e na frente da parede, o efeito de profundidade dos Reels, recortando a pessoa só enquanto o texto aparece.

## Quando usar

O vídeo mostra uma pessoa de frente, com a câmera parada, e você quer um título grande no cenário ("CINCO CAMADAS") com a cabeça e os ombros por cima das letras. O recorte usa a mesma rede neural da troca de fundo e só roda do início ao fim do texto: o resto do vídeo não é tocado.

**Pedidos que levam a esta tarefa:**
- "Põe o título atrás da minha cabeça"
- "Faz aquele efeito de texto atrás da pessoa"

## O que perguntar antes

- O trecho tem uma pessoa de frente (cartão e foto não têm: o `validate` avisa) e o texto já está na spec com `start` e `end`. Se ainda não está, crie-o antes (um texto de papel `title`, no meio).
- Custo: perto de 0,5 s por quadro do intervalo em 1080x1920 (3 s de efeito somam uns 50 s ao render final). O recorte fica em cache: trocar só a frase ou a cor do texto não recorta de novo.
- Modelos: o render final usa o `resnet50` (o `dmaker setup` baixa) e a prévia usa o `mobilenetv3`, que baixa na primeira vez (15 MB).

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `timeline_view`: achar o índice do texto entre as sobreposições
   Argumentos de exemplo: `{"name": "meu-reel"}`
2. `edit_project`: pôr o texto atrás da pessoa
   Argumentos de exemplo: `{"name": "meu-reel", "op": {"type": "set_field", "path": "overlays.1.layer", "value": "behind-person"}}`
3. `validate_project`: avisar se o intervalo só cobre cartão ou foto
   Argumentos de exemplo: `{"name_or_path": "meu-reel"}`
4. `render_project`: ver o efeito na prévia
   Argumentos de exemplo: `{"name_or_path": "meu-reel", "preview": true}`
5. `qa_report`: conferir o projeto
   Argumentos de exemplo: `{"name_or_path": "meu-reel", "output": false}`

## Equivalente na CLI

```powershell
dmaker validate projects\meu-reel\spec.json
dmaker render projects\meu-reel\spec.json --preview
```

Na spec, o texto leva `{"type": "text", "text": "CINCO CAMADAS", "role": "title", "layer": "behind-person", "start": 0, "end": 3, "position": "center", "style": {"size": 190, "color": "#FFFFFF", "outline": 0}}`. O padrão de `layer` é `"front"`, na frente de tudo.

## Como conferir

A ordem das camadas, de baixo para cima, é: o vídeo, os textos atrás da pessoa, a pessoa recortada e, por cima, imagens, picture-in-picture, audiogramas, textos comuns e legendas. Veja a borda do cabelo e das mãos na prévia (o `mobilenetv3` é mais grosseiro que o `resnet50` do render final). O ASS dos textos atrás da pessoa fica em `overlay_behind.ass`, na pasta do job.

## Erros comuns

- **Aviso em `overlays[N].layer`**: o intervalo do texto só cobre cartão ou foto; não há pessoa a recortar.
- **A borda piscou**: movimento rápido ou câmera em movimento; o efeito pede a pessoa de frente e a câmera parada.
- **Render lento**: o recorte pesa na CPU; reduza o intervalo do texto ou confira só a prévia.
