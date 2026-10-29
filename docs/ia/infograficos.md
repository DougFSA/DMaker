# Pôr um infográfico animado no vídeo

Tarefa `infograficos` do manual do DMaker. Põe por cima do vídeo um infográfico pronto que se mexe (um contador, uma barra, uma linha entre dois pontos, uma imagem entrando, uma etiqueta, um grifo à mão ou um emoji animado), escolhido pelo nome e com os valores que você quiser, nas cores e na fonte da marca.

## Quando usar

Você quer o número que conta até 10.000, a barra que enche até 95 mg com o limite em 400, a linha que liga o prédio ao mapa, a etiqueta "QUARTO", o círculo na palavra da legenda. Cada modelo faz uma coisa só e não traz fundo: combine vários no mesmo assunto. Para outra animação, veja "Pôr uma animação em HTML sobre o vídeo".

**Pedidos que levam a esta tarefa:**
- "Põe um contador de 0 a 10 mil na parte de cima, com 'mais de R$' antes"
- "Faz uma barra até 95 mg com o limite de 400 e circula a palavra 'frio' na legenda"

## O que perguntar antes

- O navegador da animação, instalado uma vez: `pip install -e ".[html]"` e `dmaker setup --html`.
- Onde ele entra: uma região do projeto (a `topo` do `explicativo`) e de que instante a qual; sem região, a área própria do modelo.
- Os parâmetros de cada modelo estão na tabela "Infográficos prontos" da referência. Valor fora dela aparece no `validate`, com o caminho do campo.
- Os emojis animados são do Google (CC BY 4.0): ao publicar, dê o crédito "Animated Noto Emoji, Google, CC BY 4.0".

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `list_infographics`: ver os modelos e os parâmetros de cada um
   Argumentos de exemplo: `{}`
2. `render_infographic_frame`: ver o quadro antes de pôr no projeto
   Argumentos de exemplo: `{"name": "contador", "params": {"ate": 10000, "prefixo": "+ de R$"}, "brand": "medlycare", "at": 1.5}`
3. `add_infographic`: pôr o contador na região de cima
   Argumentos de exemplo: `{"project": "meu-reel", "name": "contador", "params": {"ate": 10000, "prefixo": "+ de R$"}, "start": 1, "end": 6, "region": "topo"}`
4. `validate_project`: apontar valor fora do esquema, arquivo ausente ou navegador não instalado
   Argumentos de exemplo: `{"name_or_path": "meu-reel"}`
5. `render_project`: gerar a prévia
   Argumentos de exemplo: `{"name_or_path": "meu-reel", "preview": true}`
6. `qa_report`: conferir a zona segura e o resto
   Argumentos de exemplo: `{"name_or_path": "meu-reel", "output": false}`

## Equivalente na CLI

```powershell
dmaker infographics list
dmaker infographics list contador
dmaker infographics frame contador --param ate=10000 --param "prefixo=+ de R$" --brand medlycare --at 1.5
dmaker infographics add meu-reel contador --param ate=10000 --param "prefixo=+ de R$" --region topo --start 1 --end 6
dmaker validate projects\meu-reel\spec.json
```

O `frame` grava o quadro em `output/html/`. Na spec: `{"type": "html", "infographic": "contador", "region": "topo", "start": 1, "end": 6, "data": {"ate": 10000}}`. No `explicativo`, cada assunto aceita `infografico` (`{"nome": "contador", "parametros": {"ate": 10000}}`).

## Como conferir

O quadro do `frame` é o que o vídeo mostra. No `validate`, `overlays[N].data.ate: precisa ser um número` aponta o valor errado, e o `qa` avisa se a área invade a região coberta pelo app. No vídeo, o contador termina exatamente no valor e para, a barra enche até a conta (95 de 400 é 23,75% do trilho) e o grifo se desenha como traço na palavra da legenda, quando ela é dita.

## Erros comuns

- **"`ate` precisa ser um número"**: o valor está fora do esquema; a mensagem diz o limite ou as opções.
- **"a palavra ... não aparece na legenda"**: o `grifo` não achou a palavra; confira `palavra`, `ocorrencia` e se o projeto tem legendas.
- **O grifo some atrás da caixa da legenda**: a legenda fica sempre na frente; no modo `rounded` aumente a folga (`recuo`).
- **Cor ou fonte inesperadas**: vêm da marca do projeto (`brand`); trocar a marca as troca, sem mexer no modelo.
- **"O Chromium não está em bin/playwright"**: rode `dmaker setup --html`.
