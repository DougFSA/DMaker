# Kit Lote

Gerar vários vídeos de uma planilha (CSV, XLSX ou JSON) sobre o mesmo modelo.

## Ferramentas deste kit

`probe_media`, `job_status`, `search_manual`, `validate_batch`, `run_batch`, `resume_batch`, `pause_batch`, `batch_status`, `list_templates`.

## Pedidos e as chamadas certas

### Pedido: "Faz os 10 stories dessa planilha"

1. `validate_batch`: conferir a planilha sem renderizar nada
   Argumentos: `{"template": "stories-medlycare", "sheet": "C:/planilhas/semana.csv", "name_column": "titulo"}`
2. `run_batch`: gerar as prévias do lote
   Argumentos: `{"template": "stories-medlycare", "sheet": "C:/planilhas/semana.csv", "name": "semana", "name_column": "titulo", "preview": true}`
3. `batch_status`: ver o que saiu e o que falhou
   Argumentos: `{"name": "semana"}`
4. `resume_batch`: refazer só o que falta ou foi corrigido
   Argumentos: `{"name": "semana"}`

Pergunte antes, se faltar:
- O modelo (`dmaker templates`) e a planilha: uma linha por vídeo, e o nome de cada coluna casa com o parâmetro do modelo sem diferenciar maiúscula, acento ou espaço (`Título` serve para `titulo`).
- Qual coluna dá o nome ao arquivo de cada vídeo (`--name-column`).
- Para ler `.xlsx`: `pip install -e ".[lote]"`. CSV (UTF-8 ou o ANSI do Excel, `,` ou `;`) e JSON não precisam de nada.

Exemplo de planilha para `stories-medlycare` (CSV com `;`):

```
titulo;texto;print
Dica um;A fila de espera organiza quem chega;imagens/dica1.png
Dica dois;Agenda online para o paciente;imagens/dica2.png
```
