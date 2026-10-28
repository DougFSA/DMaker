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
