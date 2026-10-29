# Corrigir uma palavra errada sem regravar

Tarefa `corrigir-fala` do manual do DMaker. Troca uma palavra ou frase dita errado numa gravação pela versão certa, falada com a voz do próprio falante, sem regravar nada.

## Quando usar

Na gravação a pessoa disse "Medicare" em vez de "MedlyCare", ou errou um número. O DMaker acha o trecho pela transcrição, regrava só ele com a voz clonada do falante (tirada de outro pedaço do mesmo arquivo) e emenda. A duração do arquivo não muda e o resto do áudio é o original. Para corrigir o texto da **legenda**, veja a tarefa própria.

**Pedidos que levam a esta tarefa:**
- "Ele falou o nome errado no minuto 2, corrige sem regravar"
- "Corrige essa palavra que eu falei errado, sem gravar de novo"
- "Troca 'cinco mil' por 'quinze mil' nessa fala"

## O que perguntar antes

- O arquivo, o texto errado **como foi dito**, e o texto certo. Em vídeo longo, o trecho aproximado (`start` e `end`) poupa a transcrição.
- Se a palavra aparece mais de uma vez, qual ocorrência (1, 2...).

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `speech_words`: listar as palavras ditas, com o tempo de cada uma
   Argumentos de exemplo: `{"path": "C:/videos/gravacao.mp4", "start": 0, "end": 60}`
2. `fix_speech`: regravar o trecho com a voz do falante
   Argumentos de exemplo: `{"path": "C:/videos/gravacao.mp4", "find": "Medicare", "text": "MedlyCare", "occurrence": 1}`
3. `job_status`: acompanhar o job (use o id devolvido)
   Argumentos de exemplo: `{"job_id": "exemplo-de-job"}`

## Equivalente na CLI

```powershell
dmaker voice words gravacao.mp4 --start 0 --end 60 --words
dmaker voice fix gravacao.mp4 --find "Medicare" --text "MedlyCare"
```

Em vez de `--find`, aponte por tempo: `--start 12.4 --end 13.1`. `--occurrence 2` escolhe a segunda ocorrência; `--no-expand` fala só o trecho trocado; `--voice` usa uma voz da biblioteca; `--save-voice nome` guarda a voz clonada do falante. A saída padrão é `output/correcao/<nome>.corrigido.<ext>`.

## Como conferir

Ouça o trecho antes e depois e as duas emendas. A emenda cai no ponto mais quieto da pausa (crossfade de 30 ms) e o volume da fala nova é igualado ao do falante. O comprimento do arquivo nunca muda: o texto novo cabe no trecho original (até 10% de diferença nas letras mantém a duração); se for maior, o trecho estica para dentro das pausas vizinhas e, se nem assim couber, a fala é comprimida e `duration_rule` avisa.

## Erros comuns

- **"Texto encontrado mais de uma vez"**: passe `--occurrence`.
- **Não achou o texto**: escreva como foi **dito** (sem acento nem maiúscula importa), ou aponte por tempo.
- **Lento**: conte cerca de 20 s por segundo de fala sintetizada, mais a separação da janela de 60 s ao redor (em cache); reparos próximos reaproveitam a separação.
- **Nome mal pronunciado na fala nova**: use `[[termo|pronúncia]]` no texto ou cadastre o termo (veja a tarefa de pronúncia).
