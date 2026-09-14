# Templates

Cada arquivo `.json` nesta pasta é uma spec de projeto completa (o mesmo formato validado por
`Project` em `src/dmaker/domain/spec.py`), só que com placeholders no lugar do que muda de vídeo
para vídeo. Em vez de reescrever a spec inteira, cria-se um projeto passando apenas os parâmetros:

```powershell
.\.venv\Scripts\dmaker.exe templates
.\.venv\Scripts\dmaker.exe new-from-template reel-medlycare-produto meu-reel --param titulo="Novo título" --param prints="C:\1.png,C:\2.png"
```

Ou pelo MCP: `list_templates()` lista os templates com o resumo dos parâmetros de cada um;
`new_from_template(template, name, params)` cria o projeto (`projects/<name>/spec.json`) e devolve
o mesmo resumo de `validate_project` (duração, avisos).

## Formato de um template

Duas chaves de metadados no topo do JSON, removidas do resultado renderizado:

```json
{
  "description": "Frase curta dizendo para que serve o template.",
  "params": {
    "titulo": { "description": "Título do cartão de abertura", "default": "Exemplo", "type": "text" },
    "video": { "description": "Vídeo principal", "type": "path", "required": true }
  },

  "name": "...",
  "timeline": [ ... ]
}
```

Cada parâmetro em `params` aceita:

- `description`: frase curta (a IA lê isso antes de preencher).
- `default`: valor usado quando o parâmetro não é passado. Sem `default`, o parâmetro é
  obrigatório (a não ser que `required` diga o contrário).
- `type`: `text`, `path` (um caminho), `paths` (lista de caminhos), `number`, `bool` ou `list`
  (lista genérica). Se omitido, é inferido do `default` (texto vira `text`, `true`/`false` vira
  `bool`, lista vira `list`, número vira `number`); sem `default` também, o padrão é `text`.
- `required`: `true`/`false`. Se omitido, é `true` quando não há `default` e `false` quando há.

## Placeholders

- `"{{nome}}"` sozinho como o valor inteiro de uma chave: vira o valor com o tipo original
  (número, lista, booleano, string), não uma substituição de texto. Exemplo: `"duration": "{{duracao}}"`
  com `duracao` do tipo `number` vira `"duration": 4` (número, não a string `"4"`).
- `"{{nome}}"` dentro de um texto maior: interpolação simples (`str(valor)`). Exemplo:
  `"text": "Oi, {{nome}}!"`.

## Listas de tamanho variável: `$for`

Um item de array pode ser um objeto `$for`, que expande para um item por elemento de um
parâmetro do tipo lista (`paths` ou `list`):

```json
"timeline": [
  { "type": "card", "title": "{{titulo}}", "duration": 3.5 },
  {
    "$for": "prints",
    "as": "src",
    "item": {
      "type": "image",
      "src": "{{src}}",
      "duration": 4,
      "motion": "zoom-in"
    }
  }
]
```

Com `"prints": ["a.png", "b.png"]`, o item acima vira dois `ImageSegment`, um por caminho.
Dentro de `"item"` ficam disponíveis `{{as}}` (o elemento, aqui `{{src}}`) e `{{as}}_index`
(o índice a partir de 0, aqui `{{src_index}}`).

## Itens opcionais: `$if`

Uma chave `"$if": "{{parametro}}"` num objeto faz esse objeto sumir do resultado quando o valor
não é verdadeiro (string vazia, lista vazia, `false`, `0` ou `null` contam como falso). Funciona
tanto num item de array quanto no valor de uma chave:

```json
"overlays": [
  { "$if": "{{logo}}", "type": "image", "src": "logo", "position": "top-right" },
  { "type": "progress-bar" }
],
"audio": {
  "music": { "$if": "{{musica}}", "src": "{{musica}}", "volume": 0.15 },
  "normalize": "two-pass"
}
```

Sem `logo`/`musica`, o overlay de logo some da lista e a chave `music` some do objeto `audio`
(fica só `{"normalize": "two-pass"}`, o que o `AudioSettings` interpreta como "sem música").

Truque útil: como o índice de `$for` começa em 0 (falso em Python), `"$if": "{{item_index}}"` numa
`transition` pula a transição só do primeiro item de uma lista expandida (que normalmente não
precisa de transição, por não ter um trecho anterior):

```json
{ "$for": "videos", "as": "src", "item": {
    "type": "clip", "src": "{{src}}",
    "transition": { "$if": "{{src_index}}", "type": "fade", "duration": 0.4 }
} }
```

## Erros

Parâmetro obrigatório faltando, parâmetro de tipo errado, template ou placeholder desconhecido:
tudo vira `TemplateError` (`dmaker.domain.templates`) com uma mensagem em português dizendo o que
falta ou o que está errado, e chega assim até a CLI e o MCP.

## Templates disponíveis

| Arquivo | Descrição | Parâmetros principais |
| --- | --- | --- |
| `reel-medlycare-produto.json` | Reel de produto MedlyCare: abertura, capturas de tela com movimento, CTA. | `titulo`, `subtitulo`, `prints` (obrigatório), `cta_titulo`, `cta_subtitulo`, `musica` (opcional), `legendas` |
| `reel-medlycare-depoimento.json` | Reel de depoimento: um corte do vídeo com gancho, crédito e CTA. | `video`, `nome`, `cargo`, `hook` (obrigatórios), `cta` |
| `stories-medlycare.json` | Story de uma dica: captura de tela de fundo, gancho, texto, CTA. | `titulo`, `texto`, `print` (obrigatório) |
| `pessoal-vlog-reel.json` | Reel pessoal de vlog/viagem: vídeos em sequência, título, trilha. | `videos` (obrigatório), `titulo`, `musica` |
| `youtube-longo.json` | Vídeo longo para YouTube: abertura, gravação principal, CTA. | `titulo`, `video` (obrigatório) |
| `casamento-multicam.json` | Cerimônia multicâmera sincronizada por áudio. | `cam_principal`, `cam_secundaria`, `audio_externo` (obrigatórios), `nomes`, `data` |
| `tutorial-tela-webcam.json` | Tutorial com tela gravada e webcam em picture-in-picture. | `tela`, `webcam` (obrigatórios), `titulo`, `subtitulo`, `nome`, `cargo` |

Todos validam como `Project` quando renderizados com os valores padrão (mais valores fictícios
para os parâmetros obrigatórios) — é o que `tests/test_templates.py` confere a cada mudança.

## Decisões e simplificações

Alguns templates simplificam o exemplo original para caber num conjunto pequeno de parâmetros:

- `reel-medlycare-produto`: cada print usa movimento fixo (`zoom-in`); o original alternava
  zoom-in/pan-left/zoom-out por posição, mas isso exigiria expressões dentro do template (fora do
  que `$for`/`$if` cobrem hoje).
- `pessoal-vlog-reel`: cada vídeo entra com o clipe inteiro (sem aparar início/fim) e reenquadre
  fixo (`crop`); o `$if` em `src_index` cuida de não aplicar transição no primeiro vídeo.
- `youtube-longo`: só `titulo`/`video` (sem capítulos), com um clipe principal entre os cartões de
  abertura e CTA.
- `casamento-multicam`: reduzido a duas câmeras e um áudio externo (o exemplo original tinha 5
  fontes e cortes com tempos específicos daquela gravação); os cortes ainda precisam de ajuste
  manual depois de criado, já que o template não sabe onde ficam os momentos da cerimônia.

Caminhos de mídia que mudam a cada uso (vídeos, prints, gravações) ficam sempre `required`, sem
`default`. Textos e caminhos que servem de exemplo claro (trilha padrão, nomes de exemplo) ficam
com `default`, editável a qualquer momento.
