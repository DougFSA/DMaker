# Pôr uma animação em HTML sobre o vídeo

Tarefa `animacao-html` do manual do DMaker. Põe por cima do vídeo uma animação que a IA escreve como código (HTML, CSS e JavaScript, com três dimensões e Lottie): um título grande, um número que conta, um objeto em 3D girando, um mapa com fotos entrando.

## Quando usar

Você quer um gráfico ou uma animação que o DMaker não tem pronta: a Terra em corte com rótulos, uma planta baixa em 3D, quadros inclinados. A IA escreve a animação, você confere um quadro dela e o DMaker a desenha quadro a quadro, com fundo transparente, na região do vídeo que você escolher. A mesma animação sai sempre igual.

**Pedidos que levam a esta tarefa:**
- "Põe na parte de cima um número que conta até 87% e um cubo 3D girando"
- "Faz uma animação em HTML com o título entrando e deixa atrás da pessoa"

## O que perguntar antes

- O navegador da animação, instalado uma vez: `pip install -e ".[html]"` e `dmaker setup --html` (Chromium de uns 120 MB em `bin/playwright`). Sem ele o `validate` avisa e o render falha com essa instrução.
- Onde ela entra: uma região do projeto (`regions`) ou o quadro todo, e de que instante a qual.
- A animação mora numa pasta do projeto (`composicoes/titulo/index.html` e os arquivos dela) e **não acessa a internet**: só usa a pasta, three.js, lottie-web, a Poppins e as cores da marca, que o DMaker já traz.
- Custo: uns 70 ms por quadro em 1080x1920 (5 s levam uns 12 s), em cache no segundo render.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `render_html_frame`: ver o quadro do meio, com os avisos da página
   Argumentos de exemplo: `{"src": "composicoes/titulo", "project": "meu-reel", "at": 2.0, "size": "1080x960"}`
2. `add_html_overlay`: pôr a animação na região de cima
   Argumentos de exemplo: `{"name": "meu-reel", "src": "composicoes/titulo", "start": 1, "end": 6, "region": "topo"}`
3. `validate_project`: avisar de pasta ausente ou navegador não instalado
   Argumentos de exemplo: `{"name_or_path": "meu-reel"}`
4. `render_project`: gerar a prévia
   Argumentos de exemplo: `{"name_or_path": "meu-reel", "preview": true}`
5. `qa_report`: conferir o projeto
   Argumentos de exemplo: `{"name_or_path": "meu-reel", "output": false}`

## Equivalente na CLI

```powershell
dmaker html frame projects\meu-reel\composicoes\titulo --at 2 --size 1080x960 --background "#3a4a5a"
dmaker validate projects\meu-reel\spec.json
dmaker render projects\meu-reel\spec.json --preview
```

O `dmaker html frame` grava o quadro em `output/html/`; `--data` entrega um JSON à página e `--brand` escolhe a marca dela. Na spec: `{"type": "html", "src": "composicoes/titulo", "region": "topo", "start": 1, "end": 6, "data": {"titulo": "Cinco camadas"}, "motion_blur": true, "layer": "behind-person"}`. `data` chega à página como `dmaker.data`, `motion_blur` borra o que se move rápido e `layer: "behind-person"` põe a animação atrás da pessoa.

## Como conferir

Veja um quadro antes de renderizar o vídeo: os avisos da página (internet bloqueada, erro de JavaScript, arquivo que não existe nela) saem junto. No vídeo, a animação entra no quadro do início pedido e some no do fim; duas renderizações do mesmo projeto saem idênticas.

## Erros comuns

- **"O Chromium não está em bin/playwright"**: rode `dmaker setup --html`.
- **Aviso "tentou acessar ... na internet"**: a página pediu algo de fora (CDN, imagem de um site). Copie o arquivo para a pasta da animação; o render segue sem a requisição.
- **A animação não se mexe**: use `animation` em CSS, animações Web, GSAP, Lottie ou uma função `window.dmakerSeek(segundos)`; `setTimeout` anda só quando o DMaker manda.
- **Fundo opaco**: a página pintou o `body`; deixe-o sem fundo.
