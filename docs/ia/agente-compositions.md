# Kit Composições e infográficos

Pôr sobre o vídeo um infográfico pronto com parâmetros (contador, gráfico, barra) ou uma composição em HTML.

## Ferramentas deste kit

`probe_media`, `job_status`, `search_manual`, `list_infographics`, `add_infographic`, `list_projects`, `get_project`, `validate_project`, `edit_project`, `timeline_view`, `render_project`, `qa_report`.

## Pedidos e as chamadas certas

### Pedido: "Põe um contador de 0 a 10 mil na parte de cima, com 'mais de R$' antes"

1. `list_infographics`: ver os modelos e os parâmetros de cada um
   Argumentos: `{}`
2. `add_infographic`: pôr o contador na região de cima
   Argumentos: `{"project": "meu-reel", "name": "contador", "params": {"ate": 10000, "prefixo": "+ de R$"}, "start": 1, "end": 6, "region": "topo"}`
3. `validate_project`: apontar valor fora do esquema, arquivo ausente ou navegador não instalado
   Argumentos: `{"name_or_path": "meu-reel"}`
4. `render_project`: gerar a prévia
   Argumentos: `{"name_or_path": "meu-reel", "preview": true}`
5. `qa_report`: conferir a zona segura e o resto
   Argumentos: `{"name_or_path": "meu-reel", "output": false}`

Pergunte antes, se faltar:
- O navegador da animação, instalado uma vez: `pip install -e ".[html]"` e `dmaker setup --html`.
- Onde ele entra: uma região do projeto (a `topo` do `explicativo`) e de que instante a qual; sem região, a área própria do modelo.
- Os parâmetros de cada modelo estão na tabela "Infográficos prontos" da referência. Valor fora dela aparece no `validate`, com o caminho do campo.
- Os emojis animados são do Google (CC BY 4.0): ao publicar, dê o crédito "Animated Noto Emoji, Google, CC BY 4.0".
