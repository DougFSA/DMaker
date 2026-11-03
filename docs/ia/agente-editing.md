# Kit Edição e render

Criar o vídeo (reel, short, story, explicativo), cortar pausas e vícios, editar o projeto, renderizar, exportar para outras plataformas e conferir o resultado.

## Ferramentas deste kit

`probe_media`, `job_status`, `search_manual`, `list_templates`, `new_from_template`, `quick_edit`, `build_explainer_video`, `autocut`, `cut_pauses_and_caption`, `list_cuts`, `undo_cut`, `list_projects`, `get_project`, `validate_project`, `edit_project`, `timeline_view`, `render_project`, `export_project`, `qa_report`, `presets`, `brands`.

## Pedidos e as chamadas certas

### Pedido: "Faz um reel de 30 segundos desse vídeo com legenda"

1. `probe_media`: ver duração e orientação da gravação
   Argumentos: `{"paths": ["C:/videos/gravacao.mp4"]}`
2. `quick_edit`: montar a prévia do Reel com legenda
   Argumentos: `{"src": "C:/videos/gravacao.mp4", "preset": "instagram/reels", "start": 0, "end": 30, "captions": true, "hook": "Três erros ao gravar em casa", "preview": true}`
3. `qa_report`: conferir zona segura, ritmo e legenda do projeto
   Argumentos: `{"name_or_path": "quick_gravacao", "output": false}`
4. `quick_edit`: gerar a versão final
   Argumentos: `{"src": "C:/videos/gravacao.mp4", "preset": "instagram/reels", "start": 0, "end": 30, "captions": true, "hook": "Três erros ao gravar em casa"}`
5. `qa_report`: conferir o arquivo final (duração, resolução, loudness)
   Argumentos: `{"name_or_path": "quick_gravacao", "output": true}`

Pergunte antes, se faltar:
- Qual é o arquivo de vídeo (caminho completo) e se é falado em português.
- Em que segundos o Reel começa e termina (o padrão é do início ao fim; Reels aceitam até 180 s).
- Qual frase de gancho aparece nos primeiros 3 segundos, se quiser uma, e o formato (Reels é o padrão).
- Se pediu uma marca (MedlyCare): `brand` com o nome em minúsculas (`medlycare`) e `logo` para pôr o logo. A marca não é o gancho.

### Pedido: "Faz um story com esse print e a pergunta 'Chegou sem hora marcada?'"

1. `list_templates`: escolher o modelo e ver os parâmetros de cada um
   Argumentos: `{}`
2. `new_from_template`: criar o projeto
   Argumentos: `{"template": "stories-medlycare", "name": "story-dica", "params": {"print": "C:/imagens/agenda.png", "titulo": "Chegou sem hora marcada?", "texto": "A fila de espera organiza quem chega e avisa o profissional"}}`
3. `validate_project`: ver a duração e os avisos
   Argumentos: `{"name_or_path": "story-dica"}`
4. `render_project`: gerar a prévia
   Argumentos: `{"name_or_path": "story-dica", "preview": true}`
5. `qa_report`: conferir antes da versão final
   Argumentos: `{"name_or_path": "story-dica", "output": false}`
6. `render_project`: gerar a versão final
   Argumentos: `{"name_or_path": "story-dica"}`

Pergunte antes, se faltar:
- Que tipo de vídeo é (produto, depoimento, story, vlog, tutorial, explicativo) para escolher o modelo.
- Os arquivos que o modelo pede (prints, vídeos) com o caminho completo: são os parâmetros obrigatórios (`list_templates` marca quais). Pergunte só o que falta deles.
- Os textos (título, gancho, CTA) têm padrão no modelo: se o usuário não deu um texto, use o padrão e siga em frente, sem perguntar.

### Pedido: "Corta as pausas dessa gravação"

1. `cut_pauses_and_caption`: cortar as pausas e deixar a legenda pronta, esperando o fim
   Argumentos: `{"source": "C:/videos/entrevista.mp4", "name": "entrevista-corte", "intensity": "normal"}`
2. `list_cuts`: mostrar o que saiu, com tempo e motivo
   Argumentos: `{"name_or_path": "entrevista-corte"}`
3. `undo_cut`: devolver ao projeto o corte número 3
   Argumentos: `{"name_or_path": "entrevista-corte", "cut_id": 3}`
4. `render_project`: gerar a prévia
   Argumentos: `{"name_or_path": "entrevista-corte", "preview": true}`
5. `qa_report`: conferir o resultado
   Argumentos: `{"name_or_path": "entrevista-corte", "output": false}`

Pergunte antes, se faltar:
- O arquivo (vídeo ou áudio com fala) e o nome do projeto novo.
- A intensidade: `suave` (só pausas), `normal` (pausas e vícios, o padrão) ou `agressiva` (também falsos começos e frases repetidas, ficando com a última tomada).
