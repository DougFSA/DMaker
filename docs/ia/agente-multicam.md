# Kit Multicâmera

Sincronizar câmeras pelo áudio e montar o vídeo de um evento (casamento) com duas câmeras.

## Ferramentas deste kit

`probe_media`, `job_status`, `search_manual`, `sync_sources`, `plan_multicam`, `list_templates`, `new_from_template`, `get_project`, `validate_project`, `timeline_view`, `render_project`, `qa_report`.

## Pedidos e as chamadas certas

### Pedido: "Monta o vídeo do casamento com as duas câmeras dessas pastas"

1. `new_from_template`: criar o projeto com as duas câmeras
   Argumentos: `{"template": "casamento-pascom", "name": "casamento-ana-carlos", "params": {"camera_altar": "D:/casamento/altar", "camera_lateral": "D:/casamento/lateral", "nomes": ["Ana & Carlos"], "data": "15.08.2026"}}`
2. `plan_multicam`: reconhecer as fases e montar os clipes
   Argumentos: `{"name_or_path": "casamento-ana-carlos"}`
3. `validate_project`: conferir duração e avisos
   Argumentos: `{"name_or_path": "casamento-ana-carlos"}`
4. `render_project`: gerar a prévia do corte
   Argumentos: `{"name_or_path": "casamento-ana-carlos", "preview": true}`
5. `qa_report`: conferir antes do render final
   Argumentos: `{"name_or_path": "casamento-ana-carlos", "output": false}`

Pergunte antes, se faltar:
- As duas pastas (câmera do altar e câmera lateral), os nomes dos casais (um item por casal, no formato "Nome & Nome") e a data. O resto (celebrante, cidade, igreja, músicos, trilha) tem padrão.
- Se a cerimônia não começa no início da gravação: o segundo em que começa e termina (`inicio`, `fim`).
- Pergunte; nunca invente o caminho de uma pasta nem os nomes.
