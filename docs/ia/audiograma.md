# Fazer um audiograma de um áudio

Tarefa `audiograma` do manual do DMaker. Transforma um áudio (corte de podcast, entrevista, áudio de WhatsApp) em um vídeo vertical com a capa num círculo, a onda ou as barras animadas no ritmo da fala e a legenda automática.

## Quando usar

Você só tem o áudio e quer divulgá-lo numa rede social, onde o que roda é vídeo. O vídeo dura o que o áudio toca: o modelo `audiograma` mede o arquivo sozinho.

**Pedidos que levam a esta tarefa:**
- "Faz um audiograma desse corte do podcast com esta capa"
- "Transforma esse áudio de WhatsApp em um vídeo com onda e legenda"
- "Quero um vídeo do episódio 12 com a foto e as barras mexendo no ritmo da fala"

## O que perguntar antes

- O arquivo de áudio (`.mp3`, `.wav`, `.m4a`, `.ogg`) e a capa (PNG ou JPG, a foto do episódio ou do convidado), com o caminho completo.
- O título (opcional, sem travessão) e o desenho: `circle` (o padrão, barras em volta da foto), `bars` (barras simétricas embaixo dela) ou `wave` (linha de onda embaixo dela).
- Se há música de fundo junto da voz, peça `seguir=voice`: o desenho então acompanha só a voz e fica parado nas pausas.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `probe_media`: conferir que o áudio abre e quanto dura
   Argumentos de exemplo: `{"paths": ["C:/audios/ep12.mp3"]}`
2. `new_from_template`: criar o projeto (a duração do vídeo é a do áudio)
   Argumentos de exemplo: `{"template": "audiograma", "name": "episodio-12", "params": {"audio": "C:/audios/ep12.mp3", "capa": "C:/imagens/capa.jpg", "titulo": "Episódio 12", "estilo": "circle"}}`
3. `validate_project`: avisar de áudio que passa do fim do vídeo ou de arquivo ausente
   Argumentos de exemplo: `{"name_or_path": "episodio-12"}`
4. `render_project`: gerar a prévia
   Argumentos de exemplo: `{"name_or_path": "episodio-12", "preview": true}`
5. `qa_report`: conferir texto, legenda e zona segura
   Argumentos de exemplo: `{"name_or_path": "episodio-12", "output": false}`
6. `render_project`: gerar a versão final
   Argumentos de exemplo: `{"name_or_path": "episodio-12"}`

## Equivalente na CLI

```powershell
dmaker new-from-template audiograma episodio-12 --param audio=ep12.mp3 --param capa=capa.jpg --param titulo="Episódio 12"
dmaker validate projects\episodio-12\spec.json
dmaker render projects\episodio-12\spec.json --preview
dmaker render projects\episodio-12\spec.json
```

`--param estilo=bars` troca o desenho, `--param seguir=voice` faz a onda seguir só a voz, `--param fundo=capa` usa a própria capa, cortada e desfocada, e `--param legendas=false` tira a legenda. Na spec, o áudio é `audio.voiceover` (`{"src": "ep12.mp3"}`, com `start`, `offset`, `end` e `volume`) e o desenho é a sobreposição `audiogram` (`style` `wave`, `bars` ou `circle`).

## Como conferir

A duração do vídeo é a do áudio. `dmaker validate` avisa quando o áudio passa do fim do vídeo, quando o arquivo não existe e quando `follow: "voice"` não tem voz para seguir. Na prévia, o pico da fala e o pico do desenho caem no mesmo quadro, e o desenho fica parado nas pausas.

## Erros comuns

- **Aviso de áudio que passa do fim**: o fundo precisa durar o que o áudio toca. O modelo `audiograma` mede sozinho; numa spec escrita à mão, meça com `dmaker probe` e use a duração dele.
- **A onda se mexe no silêncio da fala**: há música de fundo e o desenho segue a mistura; use `seguir=voice`.
- **Sem legenda**: o modelo do Whisper baixa na primeira vez (precisa de internet nessa vez); `legendas=false` desliga.
- **Capa esticada**: use uma imagem quadrada; o círculo recorta o maior quadrado central.
