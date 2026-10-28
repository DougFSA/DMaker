# Fazer vários vídeos de uma planilha

Tarefa `lote` do manual do DMaker. Gera um vídeo por linha de uma planilha (CSV, XLSX ou JSON), todos sobre o mesmo modelo de projeto, com validação antes, pausa e retomada.

## Quando usar

Você precisa de uma série (dez Reels "procedimento da semana") ou do mesmo anúncio em versões por clínica ou cidade.

**Pedidos que levam a esta tarefa:**
- "Faz os 10 stories dessa planilha"
- "Gera um vídeo para cada linha desse CSV"

## O que perguntar antes

- O modelo (`dmaker templates`) e a planilha: uma linha por vídeo, e o nome de cada coluna casa com o parâmetro do modelo sem diferenciar maiúscula, acento ou espaço (`Título` serve para `titulo`).
- Qual coluna dá o nome ao arquivo de cada vídeo (`--name-column`).
- Para ler `.xlsx`: `pip install -e ".[lote]"`. CSV (UTF-8 ou o ANSI do Excel, `,` ou `;`) e JSON não precisam de nada.

Exemplo de planilha para `stories-medlycare` (CSV com `;`):

```
titulo;texto;print
Dica um;A fila de espera organiza quem chega;imagens/dica1.png
Dica dois;Agenda online para o paciente;imagens/dica2.png
```

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `validate_batch`: conferir a planilha sem renderizar nada
   Argumentos de exemplo: `{"template": "stories-medlycare", "sheet": "C:/planilhas/semana.csv", "name_column": "titulo"}`
2. `run_batch`: gerar as prévias do lote
   Argumentos de exemplo: `{"template": "stories-medlycare", "sheet": "C:/planilhas/semana.csv", "name": "semana", "name_column": "titulo", "preview": true}`
3. `batch_status`: ver o que saiu e o que falhou
   Argumentos de exemplo: `{"name": "semana"}`
4. `resume_batch`: refazer só o que falta ou foi corrigido
   Argumentos de exemplo: `{"name": "semana"}`

## Equivalente na CLI

```powershell
dmaker batch validate stories-medlycare semana.csv --name-column titulo
dmaker batch run stories-medlycare semana.csv --name-column titulo --lote semana --preview
dmaker batch status semana
dmaker batch resume semana
```

`--skip-invalid` segue sem as linhas com problema (elas ficam "Pulada" no relatório). `dmaker batch pause semana`, em outra janela, para depois do vídeo em andamento. `--replace` refaz um lote de mesmo nome a partir da planilha atual.

## Como conferir

Cada linha vira um projeto (`projects/<lote>-<nome>`) e um vídeo em `output/<lote>/<nome>.mp4`. O relatório está em `output/<lote>/relatorio.txt`. Para corrigir um vídeo, edite o projeto dele e rode `dmaker batch resume semana`: só ele é refeito.

## Erros comuns

- **Lote não começa**: há linha inválida; leia a validação (linha, coluna, motivo) ou use `--skip-invalid`.
- **"Coluna ignorada"**: o nome não casa com nenhum parâmetro do modelo; renomeie a coluna.
- **O processo caiu no meio**: `resume` refaz só o vídeo que estava rodando; o que já saiu com a mesma spec não é refeito.
- **Travessão na planilha**: a regra da marca vale para o texto das células; troque por vírgula.
