# Narrar um roteiro com a minha voz

Tarefa `narrar` do manual do DMaker. Transforma um texto em áudio falado com a sua voz (clonada de uma gravação sua, com a sua autorização) ou com uma voz pronta, e gera a legenda com o tempo de cada fala.

## Quando usar

Você tem um roteiro e quer a narração sem gravar. Para um roteiro longo (livro, manual, vários roteiros), use a fila. Para pôr a narração dentro de um vídeo, veja "Pôr a narração dentro de um vídeo".

**Pedidos que levam a esta tarefa:**
- "Narra esse roteiro com a minha voz"
- "Transforma esse texto em áudio"
- "Faz uma narração de rascunho com a voz pronta"

## O que perguntar antes

- O texto (ou um arquivo `.txt`). Linha em branco vira pausa de parágrafo; `[pausa 1.2]` fixa uma pausa em segundos; números, R$ e % são lidos por extenso.
- Qual voz: `dmaker voice list` mostra as prontas e as suas. Para a **sua** voz, uma gravação limpa de 3 a 15 s (veja "Clonar uma voz"), e a **autorização de quem fala**: só clone a voz de quem concordou.
- Rascunho ou versão final: o rascunho (`draft`) usa metade do tempo e sai mais áspero.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `list_voices`: ver as vozes prontas e as suas
   Argumentos de exemplo: `{}`
2. `synthesize_speech`: narrar em rascunho e gravar a legenda
   Argumentos de exemplo: `{"text": "Olá! Este é o meu roteiro.\n\nEle tem duas frases.", "voice": "minha-voz", "out": "C:/audio/narracao.wav", "srt": true, "draft": true}`
3. `synthesize_speech`: narrar na qualidade final
   Argumentos de exemplo: `{"text": "Olá! Este é o meu roteiro.\n\nEle tem duas frases.", "voice": "minha-voz", "out": "C:/audio/narracao.wav", "srt": true}`
4. `verify_watermark`: confirmar a etiqueta de voz gerada
   Argumentos de exemplo: `{"path": "C:/audio/narracao.wav"}`

## Equivalente na CLI

```powershell
dmaker voice clone minha-voz referencia.wav --text "Esta é a frase que eu li na gravação, com calma e perto do microfone."
dmaker voice list
dmaker voice say --file roteiro.txt --voice minha-voz --out narracao.wav --srt --draft
dmaker voice say --file roteiro.txt --voice minha-voz --out narracao.wav --srt
```

O primeiro comando cadastra a sua voz (só uma vez; veja "Clonar uma voz" e a autorização). Os dois últimos narram: o rascunho para ouvir o ritmo, e a versão final.

`dmaker voice say "texto direto" --out narracao.wav` serve para frases curtas. Sem `--voice`, fala a voz automática do OmniVoice. `--steps 32` dá a qualidade máxima, `--speed 1.2` acelera, `--seed 7` repete a mesma fala, `--raw` desliga o acabamento de rádio, `--language en` muda o idioma. A saída pode ser `.wav`, `.mp3` ou `.m4a`.

## Como conferir

O comando mostra a duração do áudio e o tempo de processamento. Confira a legenda `.srt` ao lado do áudio. Nunca prove "que ficou bom" só pelo arquivo existir: ouça o início e o fim, e rode `dmaker voice verify narracao.wav` para confirmar a etiqueta. Cada fala fica em `cache/voice`: refazer o roteiro com poucas mudanças só sintetiza o que mudou.

## Erros comuns

- **Muito lento**: use `--draft`; referências curtas (5 a 10 s) deixam tudo mais rápido; conte cerca de 50 s por segundo de áudio na versão final.
- **O nome saiu mal pronunciado** ("DMaker" vira "DeMaker"): veja "Ensinar o DMaker a pronunciar um nome".
- **"Voz não encontrada"**: o id está errado; confira com `dmaker voice list`.
- **Falta de modelo ou de pacote**: instale o extra `voice` (veja a instalação) e deixe baixar na primeira vez.
