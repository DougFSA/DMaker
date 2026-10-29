# Kit Legendas

Ler, transcrever e corrigir as legendas de um vídeo ou de um projeto.

## Ferramentas deste kit

`probe_media`, `job_status`, `search_manual`, `read_captions`, `fix_captions`, `transcribe_media`, `get_project`, `validate_project`, `edit_project`, `render_project`, `qa_report`.

## Pedidos e as chamadas certas

### Pedido: "A legenda escreveu o nome errado, corrige"

1. `read_captions`: ver as legendas suspeitas
   Argumentos: `{"name_or_path": "meu-reel", "mode": "compact"}`
2. `fix_captions`: trocar a grafia em todas as falas
   Argumentos: `{"name_or_path": "meu-reel", "replacements": {"medly care": "MedlyCare"}}`
3. `render_project`: gerar a prévia com o texto corrigido
   Argumentos: `{"name_or_path": "meu-reel", "preview": true}`

Pergunte antes, se faltar:
- O nome do projeto e as duas grafias: a errada, como saiu, e a certa.

### Pedido: "Faz a legenda ficar em caixa"

1. `edit_project`: trocar o modo da legenda para caixa arredondada
   Argumentos: `{"name": "meu-reel", "op": {"type": "set_field", "path": "captions.style.mode", "value": "rounded"}}`
2. `render_project`: gerar a prévia para ver a caixa
   Argumentos: `{"name_or_path": "meu-reel", "preview": true}`
3. `qa_report`: conferir que a legenda cabe na zona segura
   Argumentos: `{"name_or_path": "meu-reel", "output": false}`

Pergunte antes, se faltar:
- O projeto já tem legendas automáticas (`captions.source` é `auto`, um `.srt` ou `narration`).
- Se quiser cantos mais ou menos redondos, o raio e a margem vêm da marca (`rounded_box_radius` e `rounded_box_padding` no `brand.json`; padrão 28 px na base 1080).
