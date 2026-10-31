# Dublar um vídeo para outro idioma

Tarefa `dublar` do manual do DMaker. Traduz a fala de um vídeo ou áudio e a refaz, com a voz clonada de quem fala, no idioma escolhido, mantendo o fundo; você revisa a tradução antes de gerar.

## Quando usar

Você tem um vídeo falado em português (ou outro idioma) e quer a versão em inglês, espanhol, francês... com a mesma voz. O trabalho tem dois passos, com a revisão no meio: preparar (separar, transcrever, traduzir) e gerar.

**Pedidos que levam a esta tarefa:**
- "Como dublo um vídeo para inglês?"
- "Dubla esse vídeo em espanhol com a minha voz"
- "Traduz e refaz a fala em inglês, mantendo a música"

## O que perguntar antes

- O arquivo, o idioma da fala (padrão `pt`) e o idioma alvo (`en`, `es`, `fr`, `de`, `it`...).
- O **Ollama no ar** com o modelo de tradução; sem ele o erro diz como abrir.
- Termos que não se traduzem (marcas): vão em `--glossary`; as marcas do dicionário de pronúncia já são mantidas.
- Se quer a voz original por baixo, estilo voice-over (`--keep-original -18`), ou só a dublada.
- **Autorização** de quem fala: a dublagem clona a voz dela.
- Se esse arquivo e idioma já têm dublagem preparada, preparar de novo apaga as traduções revisadas: só com `overwrite`.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `dub_prepare`: separar, transcrever e traduzir; grava o projeto .dub.json
   Argumentos de exemplo: `{"path": "C:/videos/gravacao.mp4", "target_language": "en", "source_language": "pt"}`
2. `dub_get`: ler as falas e a tradução para revisar
   Argumentos de exemplo: `{"project": "C:/dmaker/output/dublagem/gravacao.en.dub.json"}`
3. `dub_update_segment`: corrigir a tradução de uma fala e travá-la
   Argumentos de exemplo: `{"project": "C:/dmaker/output/dublagem/gravacao.en.dub.json", "segment_id": "s1", "text": "Hello, I am [[MedlyCare|Medly Care]].", "locked": true}`
4. `dub_render`: gerar a dublagem em rascunho
   Argumentos de exemplo: `{"project": "C:/dmaker/output/dublagem/gravacao.en.dub.json", "draft": true}`

## Equivalente na CLI

```powershell
dmaker dub prepare gravacao.mp4 --to en --from pt
dmaker dub render output\dublagem\gravacao.en.dub.json --draft
```

Com o projeto já existente, `dub prepare` e `dub run` recusam; `--overwrite` prepara por cima.

Para fazer os dois passos de uma vez, sem revisar: `dmaker dub gravacao.mp4 --to en`. O projeto `output\dublagem\gravacao.en.dub.json` é um JSON editável: corrija o campo `text` de cada fala à mão, ou use `dmaker dub retranslate <projeto>` para traduzir de novo só as falas sem a trava (`locked`). A tradução aceita `[[termo|pronúncia]]`.

O vídeo sai em `output\dublagem\<nome>.<idioma>.<ext>` com a legenda `.srt`. `--draft` usa 8 passos de síntese (metade do tempo, mais áspero); `--steps 32` é o máximo.

## Como conferir

Ouça o vídeo dublado e leia o `.srt`. Cada fala tem um `status` no relatório (`fits`, `advances`, `squeezed`, `stretched`, `overflow`, `empty`); o resultado traz `warnings` pedindo uma tradução mais curta onde o fim da fala foi cortado. Corrigir uma tradução e gerar de novo só ressintetiza aquela fala (o cache é por texto, voz, idioma, duração e passos).

## Erros comuns

- **"Ollama não está rodando"**: abra o aplicativo ou `ollama serve`, e baixe o modelo (`ollama pull gpt-oss:20b`).
- **"Já existe uma dublagem preparada"**: continue por ela (`dub render <projeto>`), ou refaça com `--overwrite` (`overwrite: true` no `dub_prepare`) e perca as traduções revisadas.
- **A fala traduzida não cabe**: encurte a tradução da fala, ou use o modo que estica o vídeo (tarefa "Dublar esticando o vídeo onde a fala não cabe").
- **Duas pessoas, uma voz só**: veja "Dublar com mais de uma pessoa falando".
- **Muito lento**: use `--draft` para conferir e a versão final só no fim.
- **Quero parar no meio**: na interface nova, **Parar** pede ao servidor que pare na próxima etapa ou fala (a separação da voz em andamento termina antes de parar); o que já foi sintetizado fica em cache e a dublagem preparada não se perde. A CLI e a clássica não têm esse botão.
