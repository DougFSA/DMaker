# Dublar esticando o vídeo onde a fala não cabe

Tarefa `dublar-esticar` do manual do DMaker. Quando a tradução é mais longa que a fala original, estica o vídeo só naquele trecho em vez de acelerar ou cortar a voz.

## Quando usar

O inglês (ou outro idioma) saiu mais comprido e a voz acelerada ficou corrida. Há três modos de encaixe: `voz` (padrão: acelera a voz até 1,25x e corta o excesso), `video` (a voz fica natural e o vídeo estica naquela janela, até 1,3x, sem interpolar quadros) e `misto` (a voz acelera até 1,15x e o vídeo estica no que faltar).

**Pedidos que levam a esta tarefa:**
- "A dublagem ficou corrida; estica o vídeo onde precisar"
- "Dubla sem acelerar a voz"

## O que perguntar antes

- Aceitar que o arquivo final fique **mais longo** que o original, e que a imagem seja recodificada (x264, CRF 18) nos trechos esticados.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `dub_prepare`: preparar já com o encaixe que estica o vídeo
   Argumentos de exemplo: `{"path": "C:/videos/gravacao.mp4", "target_language": "en", "fit_mode": "video"}`
2. `dub_render`: gerar escolhendo outro modo só desta geração
   Argumentos de exemplo: `{"project": "C:/dmaker/output/dublagem/gravacao.en.dub.json", "fit_mode": "misto", "draft": true}`

## Equivalente na CLI

```powershell
dmaker dub prepare gravacao.mp4 --to en --fit video
dmaker dub render output\dublagem\gravacao.en.dub.json --fit misto --draft
```

## Como conferir

Só a fala que não coube estica; o fundo e a voz original atenuada acompanham o vídeo (mesmo tom) e a legenda `.srt` cai nos tempos novos. O resultado traz `output_seconds` (a duração nova) e `stretched`. Passou de 1,3x: o fim da fala é cortado e há um aviso. Em áudio sem imagem, o modo vale como `voz`.

## Erros comuns

- **A duração mudou e não esperava**: é o efeito do modo `video`; use `voz` para manter a duração.
- **Aviso de fala cortada**: encurte a tradução daquela fala e gere de novo.
