# Kit Dublagem

Dublar um vídeo para outro idioma, revisar as traduções e exportar as trilhas.

## Ferramentas deste kit

`probe_media`, `job_status`, `search_manual`, `dub_prepare`, `dub_get`, `dub_update_segment`, `dub_retranslate`, `dub_render`, `dub_stems`, `list_voices`.

## Pedidos e as chamadas certas

### Pedido: "Como dublo um vídeo para inglês?"

1. `dub_prepare`: separar, transcrever e traduzir; grava o projeto .dub.json
   Argumentos: `{"path": "C:/videos/gravacao.mp4", "target_language": "en", "source_language": "pt"}`
2. `dub_get`: ler as falas e a tradução para revisar
   Argumentos: `{"project": "C:/dmaker/output/dublagem/gravacao.en.dub.json"}`
3. `dub_update_segment`: corrigir a tradução de uma fala e travá-la
   Argumentos: `{"project": "C:/dmaker/output/dublagem/gravacao.en.dub.json", "segment_id": "s1", "text": "Hello, I am [[MedlyCare|Medly Care]].", "locked": true}`
4. `dub_render`: gerar a dublagem em rascunho
   Argumentos: `{"project": "C:/dmaker/output/dublagem/gravacao.en.dub.json", "draft": true}`

Pergunte antes, se faltar:
- O arquivo, o idioma da fala (padrão `pt`) e o idioma alvo (`en`, `es`, `fr`, `de`, `it`...).
- O **Ollama no ar** com o modelo de tradução; sem ele o erro diz como abrir.
- Termos que não se traduzem (marcas): vão em `--glossary`; as marcas do dicionário de pronúncia já são mantidas.
- Se quer a voz original por baixo, estilo voice-over (`--keep-original -18`), ou só a dublada.
- **Autorização** de quem fala: a dublagem clona a voz dela.

### Pedido: "Dubla essa entrevista com duas vozes diferentes"

1. `dub_prepare`: preparar separando as duas pessoas
   Argumentos: `{"path": "C:/videos/entrevista.mp4", "target_language": "en", "speaker_mode": "per_speaker", "num_speakers": 2}`
2. `dub_get`: ver o falante de cada fala
   Argumentos: `{"project": "C:/dmaker/output/dublagem/entrevista.en.dub.json"}`
3. `dub_update_segment`: corrigir quem fala uma fala
   Argumentos: `{"project": "C:/dmaker/output/dublagem/entrevista.en.dub.json", "segment_id": "s4", "speaker": "Falante 2"}`
4. `dub_render`: gerar a dublagem
   Argumentos: `{"project": "C:/dmaker/output/dublagem/entrevista.en.dub.json", "draft": true}`

Pergunte antes, se faltar:
- Quantas pessoas falam, se você souber (`--speakers N` força o número; sem isso o áudio decide).
- A **autorização** de cada pessoa para clonar a voz.
- Os modelos de diarização baixam na primeira vez (cerca de 34 MB). `DMAKER_DIARIZATION=off` desliga a separação.

### Pedido: "A dublagem ficou corrida; estica o vídeo onde precisar"

1. `dub_prepare`: preparar já com o encaixe que estica o vídeo
   Argumentos: `{"path": "C:/videos/gravacao.mp4", "target_language": "en", "fit_mode": "video"}`
2. `dub_render`: gerar escolhendo outro modo só desta geração
   Argumentos: `{"project": "C:/dmaker/output/dublagem/gravacao.en.dub.json", "fit_mode": "misto", "draft": true}`

Pergunte antes, se faltar:
- Aceitar que o arquivo final fique **mais longo** que o original, e que a imagem seja recodificada (x264, CRF 18) nos trechos esticados.
