# Código e materiais de terceiros

O que o DMaker usa de outros projetos e sob qual licença. O código copiado ou portado fica com a atribuição
no topo do próprio arquivo; modelos e pesos baixados em tempo de uso têm a licença registrada no
gerenciador de modelos (`dmaker models`).

## @remotion/rounded-text-box

- **Onde:** `src/dmaker/text/rounded_box.py` (caixa de fundo arredondada que abraça cada linha da legenda e
  dos textos, estilo TikTok).
- **Projeto:** Remotion, pacote `packages/rounded-text-box`, https://github.com/remotion-dev/remotion/tree/main/packages/rounded-text-box
- **Licença:** MIT, declarada no `package.json` do pacote (`"license": "MIT"`, autor Jonny Burger). A pasta do
  pacote não traz um arquivo `LICENSE` próprio nem linha de copyright; a linha abaixo segue o autor do
  `package.json`.
- **O que foi aproveitado:** o algoritmo da geometria (raio do canto na emenda entre duas linhas igual à
  metade do degrau, limitado ao raio pedido e à metade da altura da linha), reescrito em Python com Bézier
  cúbica no lugar do arco do SVG. **Só** a pasta MIT do pacote foi consultada: o núcleo do Remotion é
  Remotion License e nada dele foi copiado.

```
MIT License

Copyright (c) Remotion (Jonny Burger)

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
associated documentation files (the "Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the
following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial
portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO
EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## OpenVoice V2 (MyShell.ai)

- **Onde:** `src/dmaker/voice/third_party/openvoice/` (conversor de timbre).
- **Projeto:** https://github.com/myshell-ai/OpenVoice
- **Licença:** MIT, texto no arquivo `LICENSE` ao lado do código. Origem e o que foi copiado em `ORIGEM.md`.

## three.js

- **Onde:** `assets/html/three.module.min.js` e `assets/html/three.core.min.js` (a versão minificada em módulo, que
  importa o núcleo), servidos às composições em HTML em `/_dmaker/` (o DMaker não roda JavaScript de terceiros
  fora do navegador da composição).
- **Projeto:** https://github.com/mrdoob/three.js, pacote `three` do npm, versão **0.185.1**, baixada do registro
  oficial do npm (`npm pack three@0.185.1`); só os dois arquivos de `build/` e o `LICENSE` foram copiados.
- **Licença:** MIT (Copyright 2010-2026 three.js authors), texto em `assets/html/LICENSE-three.txt`.

## lottie-web

- **Onde:** `assets/html/lottie.min.js` (o player completo, minificado), servido às composições em HTML em
  `/_dmaker/lottie.min.js`, para tocar animações Lottie (`.json`) com o relógio controlado pelo DMaker.
- **Projeto:** https://github.com/airbnb/lottie-web, pacote `lottie-web` do npm, versão **5.13.0**, baixada do
  registro oficial do npm (`npm pack lottie-web@5.13.0`); só `build/player/lottie.min.js` e o `LICENSE.md` foram
  copiados.
- **Licença:** MIT (Copyright 2015 Bodymovin), texto em `assets/html/LICENSE-lottie-web.txt`. A licença de cada
  animação Lottie que alguém usar numa composição é da animação, não da biblioteca: confira antes de publicar.

## GSAP

- **Não vendorizado.** A licença do GSAP é própria (não é MIT) e o DMaker não a distribui. Se uma composição trouxer
  o GSAP junto dos arquivos dela, o relógio virtual do DMaker o controla; a decisão de usá-lo e a licença são de
  quem o traz.

## rough-notation

- **Onde:** `assets/html/rough-notation.js` (a versão `iife` da biblioteca, com o rough.js embutido, 11 KB), servida às
  composições em HTML em `/_dmaker/rough-notation.js` e usada pelo infográfico `grifo` (círculo, sublinhado,
  marca-texto e risco desenhados à mão).
- **Projeto:** https://github.com/rough-stuff/rough-notation (Preet Shihn), pacote `rough-notation` do npm, versão
  **0.5.1**, baixada do registro oficial do npm (`npm pack rough-notation@0.5.1`); só `lib/rough-notation.iife.js` e
  o `LICENSE` foram copiados.
- **Licença:** MIT (Copyright 2020 Preet Shihn), texto em `assets/html/LICENSE-rough-notation.txt`. O rough.js
  embutido no arquivo também é MIT.

## Animated Noto Emoji (Google)

- **Onde:** `assets/html/emoji/*.json` (dez animações Lottie: joinha, check, coração, fogo, festa, lâmpada, café,
  gráfico, surpresa e risada), servidas em `/_dmaker/emoji/<nome>.json` e tocadas pelo infográfico `emoji` com o
  lottie-web.
- **Projeto:** Noto Emoji Animation, https://googlefonts.github.io/noto-emoji-animation/ (Google). Os arquivos foram
  baixados da fonte oficial, sem alteração, de
  `https://fonts.gstatic.com/s/e/notoemoji/latest/<codepoint>/lottie.json` (1f44d, 2705, 2764_fe0f, 1f525, 1f389,
  1f4a1, 2615, 1f4c8, 1f632 e 1f602) e só foram renomeados.
- **Licença:** Creative Commons Attribution 4.0 International (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/.
  A página oficial do projeto, na pergunta "Can I use these animated assets commercially: for a video, for
  broadcast, apps, etc.?", responde: "Animated Noto Emoji is licensed under CC BY 4.0". O uso comercial é permitido
  e a licença pede **atribuição**: crédito ao autor, link da licença e aviso de que houve alteração. O texto de
  crédito está em `assets/html/emoji/ATRIBUICAO.md` e a documentação do modelo `emoji` o repete; quem publicar um
  vídeo com esses emojis deve manter o crédito "Animated Noto Emoji, Google, CC BY 4.0".
