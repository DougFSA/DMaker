# Fazer um Reel a partir de uma gravação

Tarefa `reel` do manual do DMaker. Transforma uma gravação sua em um vídeo vertical para o Instagram, com legenda automática palavra a palavra, gancho no começo e barra de progresso.

## Quando usar

Você tem um vídeo falado (celular, webcam) e quer um Reel pronto, sem montar uma linha do tempo. Serve também para Shorts, TikTok e Stories: troque o formato. Para vários trechos, cartões e fotos, use um modelo pronto (tarefa "Criar um projeto a partir de um modelo pronto").

**Pedidos que levam a esta tarefa:**
- "Faz um reel de 30 segundos desse vídeo com legenda"
- "Põe legenda automática e um gancho nesse vídeo e deixa vertical"
- "Transforma essa gravação em short"

## O que perguntar antes

- Qual é o arquivo de vídeo (caminho completo) e se é falado em português.
- Em que segundos o Reel começa e termina (o padrão é do início ao fim; Reels aceitam até 180 s).
- Qual frase de gancho aparece nos primeiros 3 segundos, se quiser uma, e o formato (Reels é o padrão).

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `probe_media`: ver duração e orientação da gravação
   Argumentos de exemplo: `{"paths": ["C:/videos/gravacao.mp4"]}`
2. `quick_edit`: montar a prévia do Reel com legenda
   Argumentos de exemplo: `{"src": "C:/videos/gravacao.mp4", "preset": "instagram/reels", "start": 0, "end": 30, "captions": true, "hook": "Três erros ao gravar em casa", "preview": true}`
3. `qa_report`: conferir zona segura, ritmo e legenda do projeto
   Argumentos de exemplo: `{"name_or_path": "quick_gravacao", "output": false}`
4. `quick_edit`: gerar a versão final
   Argumentos de exemplo: `{"src": "C:/videos/gravacao.mp4", "preset": "instagram/reels", "start": 0, "end": 30, "captions": true, "hook": "Três erros ao gravar em casa"}`
5. `qa_report`: conferir o arquivo final (duração, resolução, loudness)
   Argumentos de exemplo: `{"name_or_path": "quick_gravacao", "output": true}`

## Equivalente na CLI

```powershell
dmaker probe gravacao.mp4
dmaker quick gravacao.mp4 --preset instagram/reels --start 0 --end 30 --captions --hook "Três erros ao gravar em casa" --preview
dmaker qa projects\quick_gravacao\spec.json
dmaker quick gravacao.mp4 --preset instagram/reels --start 0 --end 30 --captions --hook "Três erros ao gravar em casa"
dmaker qa projects\quick_gravacao\spec.json --output output\quick_gravacao__instagram-reels.mp4
```

O comando mostra o caminho do vídeo gerado em `output/` (a prévia sai com o sufixo `__preview` e em resolução menor de propósito, 540x960; por isso o QA do arquivo só vale para a versão final). Com `--logo --brand medlycare` entra o logo da marca; `--cta "texto"` põe a chamada nos últimos 4 segundos; `--music trilha.mp3` põe a trilha.

## Como conferir

Abra o MP4 de `output/` e veja as legendas em sincronia e o gancho no topo. `dmaker qa` diz em texto se algo foge da zona segura, do ritmo de leitura ou do contraste; com `--output` e o arquivo **final**, confere também a duração, a resolução, os quadros pretos, o silêncio e a loudness perto de -14 LUFS. Só olhe quadros (`dmaker sheet`) se o relatório apontar algo.

## Erros comuns

- **"Fonte não encontrada"**: o caminho do vídeo está errado; use o caminho completo.
- **A legenda errou um nome**: veja a tarefa "Corrigir uma palavra errada na legenda".
- **A legenda não aparece**: faltou `--captions`, ou o vídeo não tem fala; a transcrição baixa o modelo na primeira vez e precisa de internet só nessa vez.
- **A legenda ficou torta no vídeo horizontal**: use `--reframe crop` ou `--reframe blur`.
- **O QA avisou "cue longa" ou "baixa confiança"**: são sugestões, não erros; veja a legenda suspeita e, se estiver errada, corrija-a (tarefa da legenda).
