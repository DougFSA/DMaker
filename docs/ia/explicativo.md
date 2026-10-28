# Fazer um vídeo explicativo

Tarefa `explicativo` do manual do DMaker. Monta um vídeo de reel em que a gravação de quem explica fica num quadro arredondado embaixo, a área de cima mostra a imagem de cada assunto e o fundo troca a cada assunto.

## Quando usar

Você grava uma explicação de frente para a câmera e tem uma imagem ou infográfico para cada assunto. A fala nunca é cortada na troca de fundo, porque a gravação é uma só, contínua.

**Pedidos que levam a esta tarefa:**
- "Faz um vídeo explicativo com minha gravação e essas três imagens"
- "Quero o rosto embaixo e o gráfico em cima"

## O que perguntar antes

- A gravação (vertical ou horizontal) e a duração dela.
- Os assuntos, em ordem: o segundo em que cada um termina (`fim`), o fundo (`escuro`, `claro`, `bege`, uma cor `#RRGGBB` ou uma imagem) e a imagem de cada um, se houver. O fim do último assunto é a duração da gravação.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `probe_media`: conhecer a duração da gravação
   Argumentos de exemplo: `{"paths": ["C:/videos/gravacao.mp4"]}`
2. `new_from_template`: criar o projeto
   Argumentos de exemplo: `{"template": "explicativo", "name": "meu-explicativo", "params": {"gravacao": "C:/videos/gravacao.mp4", "assuntos": [{"fim": 20, "fundo": "escuro", "imagem": "C:/imagens/assunto1.png"}, {"fim": 40, "fundo": "bege", "imagem": "C:/imagens/assunto2.png"}, {"fim": 60, "fundo": "claro"}]}}`
3. `validate_project`: conferir duração e avisos
   Argumentos de exemplo: `{"name_or_path": "meu-explicativo"}`
4. `render_project`: gerar a prévia
   Argumentos de exemplo: `{"name_or_path": "meu-explicativo", "preview": true}`

## Equivalente na CLI

```powershell
dmaker new-from-template explicativo meu-explicativo --param gravacao=gravacao.mp4 --params-json '{"assuntos": [{"fim": 20, "fundo": "escuro", "imagem": "assunto1.png"}, {"fim": 40, "fundo": "bege", "imagem": "assunto2.png"}, {"fim": 60, "fundo": "claro"}]}'
dmaker validate projects\meu-explicativo\spec.json
dmaker render projects\meu-explicativo\spec.json --preview
```

Opções do modelo: `foco` (ponto do rosto que o quadro mantém visível; padrão `[0.5, 0.3]`), `legendas` (padrão ligado), `legenda_modo` (`rounded`, `karaoke`, `classic`, `boxed`) e `marca`.

## Como conferir

O quadro do rosto e a área de cima ficam dentro da zona segura do Reels. `dmaker validate` avisa se a gravação é mais curta que o fim do último assunto. Na prévia, confira que o fundo troca no segundo certo e que a fala segue contínua.

## Erros comuns

- **Aviso de gravação mais curta**: o `fim` do último assunto passa da duração do arquivo; corrija o número.
- **Rosto cortado**: ajuste `foco` (em gravação vertical o rosto fica no terço de cima).
- **Imagem fora do lugar**: ela entra inteira e centrada na região `topo`, sem distorcer; use uma imagem com a proporção da área de cima.
