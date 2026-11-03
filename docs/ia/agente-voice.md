# Kit Voz e narração

Narrar um texto, pôr a narração num projeto, clonar ou criar uma voz, ensinar a pronúncia de um nome e conferir se um áudio foi gerado pelo DMaker.

## Ferramentas deste kit

`probe_media`, `job_status`, `search_manual`, `narrate_into_project`, `synthesize_speech`, `list_voices`, `clone_voice`, `design_voice`, `voice_queue_add`, `voice_queue_list`, `pronunciation`, `verify_watermark`, `list_projects`, `get_project`, `validate_project`, `render_project`.

## Pedidos e as chamadas certas

### Pedido: "Narra esse roteiro com a minha voz"

1. `list_voices`: ver as vozes prontas e as suas
   Argumentos: `{}`
2. `synthesize_speech`: narrar em rascunho e gravar a legenda
   Argumentos: `{"text": "Olá! Este é o meu roteiro.\n\nEle tem duas frases.", "voice": "minha-voz", "out": "C:/audio/narracao.wav", "srt": true, "draft": true}`
3. `synthesize_speech`: narrar na qualidade final
   Argumentos: `{"text": "Olá! Este é o meu roteiro.\n\nEle tem duas frases.", "voice": "minha-voz", "out": "C:/audio/narracao.wav", "srt": true}`
4. `verify_watermark`: confirmar a etiqueta de voz gerada
   Argumentos: `{"path": "C:/audio/narracao.wav"}`

Pergunte antes, se faltar:
- O texto (ou um arquivo `.txt`). Linha em branco vira pausa de parágrafo; `[pausa 1.2]` fixa uma pausa em segundos; números, R$ e % são lidos por extenso.
- Qual voz: `dmaker voice list` mostra as prontas e as suas. Para a **sua** voz, uma gravação limpa de 3 a 15 s (veja "Clonar uma voz"), e a **autorização de quem fala**: só clone a voz de quem concordou.
- Rascunho ou versão final: o rascunho (`draft`) usa metade do tempo e sai mais áspero.

### Pedido: "Narra esse texto sobre os cartões do vídeo"

1. `narrate_into_project`: pôr a narração no projeto, usar o texto como legenda e avisar de voz inexistente
   Argumentos: `{"name_or_path": "meu-video", "text": "Bem-vindo ao DMaker.", "voice": "narradora", "start": 0.5, "seed": 1}`
2. `render_project`: gerar a prévia
   Argumentos: `{"name_or_path": "meu-video", "preview": true}`

Pergunte antes, se faltar:
- O projeto, o texto (ou um `.txt` relativo à pasta do projeto), a voz e o instante em que a fala começa.
- A voz e o texto são lidos do cache: só a primeira vez sintetiza.

### Pedido: "Clona a minha voz com essa gravação"

1. `clone_voice`: cadastrar a voz (só com a autorização do dono)
   Argumentos: `{"name": "minha-voz", "reference_audio": "C:/audio/referencia.wav", "language": "pt"}`
2. `list_voices`: confirmar que a voz entrou na biblioteca
   Argumentos: `{}`
3. `synthesize_speech`: ouvir uma amostra
   Argumentos: `{"text": "Teste da minha voz clonada.", "voice": "minha-voz", "out": "C:/audio/teste-voz.wav", "draft": true}`

Pergunte antes, se faltar:
- **Pergunte se o dono da voz autorizou a clonagem. Sem autorização, não clone.** A interface exige marcar "Tenho permissão do dono desta voz para cloná-la"; a CLI e as ferramentas não perguntam, então a pergunta é sua.
- Uma gravação de fala limpa, sem música nem ruído, de 3 a 15 s (até 20 s vale inteira; acima disso o DMaker escolhe a janela de 15 s com mais fala). O ideal é a pessoa lendo uma frase natural.
- O que é dito na gravação, se souber (sem isso o Whisper transcreve).
