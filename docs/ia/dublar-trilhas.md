# Exportar as trilhas separadas da dublagem

Tarefa `dublar-trilhas` do manual do DMaker. Exporta a voz dublada, o fundo e a voz original em arquivos separados, para refazer a mixagem em outro editor (Premiere, DaVinci, CapCut).

## Quando usar

Você quer controlar o volume da voz e do fundo por conta própria, ou usar a dublagem num editor que não é o DMaker.

**Pedidos que levam a esta tarefa:**
- "Me dá a voz dublada e o fundo em arquivos separados"
- "Exporta os stems da dublagem"

## O que perguntar antes

- O projeto `.dub.json` já preparado (tarefa "Dublar um vídeo para outro idioma"). As falas vêm do cache; as que faltarem são sintetizadas.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `dub_stems`: exportar voz dublada, fundo e voz original
   Argumentos de exemplo: `{"project": "C:/dmaker/output/dublagem/gravacao.en.dub.json", "make_zip": true}`

## Equivalente na CLI

```powershell
dmaker dub stems output\dublagem\gravacao.en.dub.json --zip
dmaker dub render output\dublagem\gravacao.en.dub.json --stems --zip
```

## Como conferir

Sai uma pasta `output\dublagem\<nome>.<idioma>.trilhas` com `voz-dublada.wav` (só as falas dubladas, nas posições do vídeo), `fundo.wav` e `voz-original.wav` (isolada, sem atenuar). São WAV de 16 bits, 48 kHz, estéreo, com a duração exata do vídeo e alinhados no zero, sem normalização nem limitador: somando a voz dublada e o fundo você reproduz a mixagem antes do acabamento.

## Erros comuns

- **Faltam falas**: o projeto não foi gerado antes; rode `dub render`, ou deixe o `stems` sintetizar o que falta.
- **Duração diferente do original**: o vídeo foi esticado (modo `video` ou `misto`); as trilhas seguem o vídeo esticado.
