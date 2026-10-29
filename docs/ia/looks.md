# Dar um acabamento de cinema ao vídeo

Tarefa `looks` do manual do DMaker. Aplica um acabamento visual pronto, por nome (cinema, quente, frio, preto e branco, vintage), com vinheta, grão, brilho e vazamento de luz.

## Quando usar

Você quer o vídeo com "cara de filme" ou uma cor uniforme em todos os trechos, sem ajustar brilho e contraste na mão.

**Pedidos que levam a esta tarefa:**
- "Deixa o vídeo com cara de cinema"
- "Põe um tom quente, de fim de tarde"
- "Faz em preto e branco contrastado"

## O que perguntar antes

- O nome do look: `cinema`, `quente`, `frio`, `pb-contraste` ou `vintage` (a marca pode definir outros em `looks` no `brand.json`).
- Se algum trecho deve ficar sem acabamento (um cartão, por exemplo): ele leva `"look": "nenhum"`.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `edit_project`: aplicar o look a todos os trechos
   Argumentos de exemplo: `{"name": "meu-reel", "op": {"type": "set_field", "path": "look", "value": "cinema"}}`
2. `render_project`: ver o acabamento na prévia
   Argumentos de exemplo: `{"name_or_path": "meu-reel", "preview": true}`
3. `qa_report`: conferir o resultado e o tamanho do arquivo
   Argumentos de exemplo: `{"name_or_path": "meu-reel", "output": false}`

## Equivalente na CLI

```powershell
dmaker looks list
dmaker looks sheet all
```

As folhas de contato ficam em `output\looks`. Para aplicar, ponha `"look": "cinema"` na raiz da spec e renderize.

## Como conferir

O look só aparece no render. A **granulação** custa tamanho de arquivo: uns 3 a 4 MB a cada 10 s em 1080x1920, e o look `cinema` inteiro pode passar de 30% a mais. Para um vídeo que precisa ficar leve, use `frio` ou `quente`, que não têm grão. Cada efeito soma de 1 a 5 s de CPU por 10 s de vídeo.

## Erros comuns

- **"look desconhecido"**: o erro vem antes de gastar o render; confira os nomes com `dmaker looks list --brand <marca>`.
- **O look não pegou num trecho**: o trecho tem `color` próprio (mantém a cor) ou `"look": "nenhum"`.
- **Legendas mudaram de cor**: não mudam; texto e legendas ficam por cima do acabamento.
