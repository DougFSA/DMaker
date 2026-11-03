# Kit Correção de fala e isolamento

Isolar a voz da música e do ruído, corrigir uma palavra dita errada sem regravar e trocar a voz de uma gravação.

## Ferramentas deste kit

`probe_media`, `job_status`, `search_manual`, `speech_words`, `fix_speech`, `convert_voice`, `isolate_vocals`, `list_voices`.

## Pedidos e as chamadas certas

### Pedido: "Tira a música dessa gravação e deixa só a voz"

1. `isolate_vocals`: separar a voz do fundo no trecho
   Argumentos: `{"path": "C:/videos/entrevista.mp4", "start": 0, "end": 60, "format": "wav"}`
2. `job_status`: acompanhar o job (use o id devolvido)
   Argumentos: `{"job_id": "exemplo-de-job"}`

Pergunte antes, se faltar:
- O arquivo e, para poupar tempo, o trecho (`start` e `end` em segundos). Conte de 3 a 6 vezes a duração do trecho, mais cerca de 30 s para carregar o modelo na primeira vez; o resultado fica em cache.

### Pedido: "Ele falou o nome errado no minuto 2, corrige sem regravar"

1. `speech_words`: listar as palavras ditas, com o tempo de cada uma
   Argumentos: `{"path": "C:/videos/gravacao.mp4", "start": 0, "end": 60}`
2. `fix_speech`: regravar o trecho com a voz do falante
   Argumentos: `{"path": "C:/videos/gravacao.mp4", "find": "Medicare", "text": "MedlyCare", "occurrence": 1}`
3. `job_status`: acompanhar o job (use o id devolvido)
   Argumentos: `{"job_id": "exemplo-de-job"}`

Pergunte antes, se faltar:
- O arquivo, o texto errado **como foi dito**, e o texto certo. Em vídeo longo, o trecho aproximado (`start` e `end`) poupa a transcrição.
- Se a palavra aparece mais de uma vez, qual ocorrência (1, 2...).

### Pedido: "Troca a voz dessa gravação pela voz `narradora`"

1. `list_voices`: escolher a voz de destino
   Argumentos: `{}`
2. `convert_voice`: testar nos primeiros 30 segundos
   Argumentos: `{"path": "C:/videos/gravacao.mp4", "voice": "narradora", "start": 0, "end": 30}`
3. `convert_voice`: converter o arquivo inteiro
   Argumentos: `{"path": "C:/videos/gravacao.mp4", "voice": "narradora"}`

Pergunte antes, se faltar:
- O arquivo e o id da voz (`dmaker voice list`). Para testar, converta só 20 a 30 s (`start` e `end`) antes do arquivo todo.
- Se a voz de destino é de uma pessoa real, a **autorização** dela.
