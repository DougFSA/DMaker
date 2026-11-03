# Dublar com mais de uma pessoa falando

Tarefa `dublar-varias-pessoas` do manual do DMaker. Descobre quem fala em cada trecho e dubla cada pessoa com a sua própria voz clonada.

## Quando usar

O vídeo é uma conversa ou entrevista com duas ou mais pessoas. O modo `per_speaker` (padrão) separa os falantes por diarização local, sem conta nem token, e monta um clone por pessoa a partir do melhor trecho de 3 a 15 s só com a fala dela.

**Pedidos que levam a esta tarefa:**
- "Dubla essa entrevista com duas vozes diferentes"
- "A segunda pessoa está com a voz da primeira, corrige"

## O que perguntar antes

- Quantas pessoas falam, se você souber (`--speakers N` força o número; sem isso o áudio decide).
- A **autorização** de cada pessoa para clonar a voz.
- Os modelos de diarização baixam na primeira vez (cerca de 34 MB). `DMAKER_DIARIZATION=off` desliga a separação.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `dub_prepare`: preparar separando as duas pessoas
   Argumentos de exemplo: `{"path": "C:/videos/entrevista.mp4", "target_language": "en", "speaker_mode": "per_speaker", "num_speakers": 2}`
2. `dub_get`: ver o falante de cada fala
   Argumentos de exemplo: `{"project": "C:/dmaker/output/dublagem/entrevista.en.dub.json"}`
3. `dub_update_segment`: corrigir quem fala uma fala
   Argumentos de exemplo: `{"project": "C:/dmaker/output/dublagem/entrevista.en.dub.json", "segment_id": "s4", "speaker": "Falante 2"}`
4. `dub_render`: gerar a dublagem
   Argumentos de exemplo: `{"project": "C:/dmaker/output/dublagem/entrevista.en.dub.json", "draft": true}`

## Equivalente na CLI

```powershell
dmaker dub prepare entrevista.mp4 --to en --speakers 2
dmaker dub render output\dublagem\entrevista.en.dub.json --draft
```

`--speaker per_segment` clona a voz em volta de cada fala (uma aproximação para vários falantes) e `--speaker single` usa um clone só para o arquivo. Com uma pessoa só, `per_speaker` vale como `single`.

## Como conferir

A tabela de falas mostra o falante de cada uma; ouça os trechos de troca de pessoa. A diarização roda em cerca de 0,3 vez a duração do áudio.

## Erros comuns

- **Duas pessoas viraram uma**: force com `--speakers 2`.
- **Uma fala está com a voz errada**: troque o falante dela (`dub_update_segment`, `speaker`).
- **Sem o pacote de diarização**: instale o extra `voice`; sem ele, o padrão volta a `per_segment`.
