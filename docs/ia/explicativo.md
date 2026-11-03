# Fazer um vídeo explicativo

Tarefa `explicativo` do manual do DMaker. Monta um vídeo de reel em que a gravação de quem explica fica num quadro arredondado embaixo, a área de cima mostra a imagem de cada assunto e o fundo troca a cada assunto.

## Quando usar

Você grava uma explicação de frente para a câmera e tem uma imagem ou infográfico para cada assunto. A fala nunca é cortada na troca de fundo, porque a gravação é uma só, contínua.

**Pedidos que levam a esta tarefa:**
- "Faz um vídeo explicativo com minha gravação e essas três imagens"
- "Quero o rosto embaixo e o gráfico em cima"

## O que perguntar antes

- A gravação (vertical ou horizontal) e a duração dela.
- Os assuntos, em ordem: o segundo em que cada um termina (`fim`), o fundo (`escuro`, `claro`, `bege`, uma cor `#RRGGBB` ou uma imagem), a imagem de cada um, se houver, e o infográfico, se houver (`infografico`: `{"nome": "contador", "parametros": {"ate": 10000}}`, um dos modelos da tarefa "Pôr um infográfico animado no vídeo"). O fim do último assunto é a duração da gravação.
- Os sons de cada assunto, se quiser (`sons`: `[{"som": "whoosh", "em": 0, "volume": 1}]`): `som` é um nome de `dmaker sfx list`, `em` são os segundos desde o começo do assunto (0 se omitido, até o fim dele) e `volume` vai de 0 a 1,5 (1 é o padrão). Cabe um som no meio, como o `ding` do contador.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `build_explainer_video`: criar o projeto e conferir duração e avisos
   Argumentos de exemplo: `{"name": "meu-explicativo", "recording": "C:/videos/gravacao.mp4", "subjects": [{"fim": 20, "fundo": "escuro", "imagem": "C:/imagens/assunto1.png", "sons": [{"som": "whoosh"}]}, {"fim": 40, "fundo": "bege", "infografico": {"nome": "contador", "parametros": {"ate": 10000, "prefixo": "+ de R$"}}, "sons": [{"som": "whoosh"}, {"som": "ding", "em": 8}]}, {"fim": 60, "fundo": "claro", "infografico": {"nome": "barra", "parametros": {"valor": 95, "maximo": 400, "sufixo": "mg", "limite": 400}}}]}`
2. `render_project`: gerar a prévia
   Argumentos de exemplo: `{"name_or_path": "meu-explicativo", "preview": true}`

## Equivalente na CLI

```powershell
dmaker new-from-template explicativo meu-explicativo --param gravacao=gravacao.mp4 --params-json '{"assuntos": [{"fim": 20, "fundo": "escuro", "imagem": "assunto1.png", "sons": [{"som": "whoosh"}]}, {"fim": 40, "fundo": "bege", "imagem": "assunto2.png"}, {"fim": 60, "fundo": "claro"}]}'
dmaker validate projects\meu-explicativo\spec.json
dmaker render projects\meu-explicativo\spec.json --preview
```

Opções do modelo: `foco` (ponto do rosto que o quadro mantém visível; padrão `[0.5, 0.3]`), `legendas` (padrão ligado), `legenda_modo` (`rounded`, `karaoke`, `classic`, `boxed`) e `marca`.

## Como conferir

O quadro do rosto e a área de cima ficam dentro da zona segura do Reels. `dmaker validate` avisa se a gravação é mais curta que o fim do último assunto. Na prévia, confira que o fundo troca no segundo certo, que a fala segue contínua e que cada som toca no começo do assunto (ou no `em` dele).

## Erros comuns

- **Aviso de gravação mais curta**: o `fim` do último assunto passa da duração do arquivo; corrija o número.
- **Erro `assunto N, som M`**: o nome do `som` não está na biblioteca (a mensagem lista os disponíveis) ou o `em` passa do fim do assunto.
- **Rosto cortado**: ajuste `foco` (em gravação vertical o rosto fica no terço de cima).
- **Imagem fora do lugar**: ela entra inteira e centrada na região `topo`, sem distorcer; use uma imagem com a proporção da área de cima.
- **Aviso `overlays[N].data...` no `validate`**: um parâmetro do infográfico de um assunto está fora do esquema do modelo; a mensagem diz qual e o que é aceito.
