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

Chaves de metadados no topo do JSON (`description` e `params`, mais `prepare` quando o template precisa dele),
removidas do resultado renderizado:

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
- `type`: `text`, `path` (um caminho), `paths` (lista de caminhos), `dir` (uma pasta: vira a lista dos
  arquivos de vídeo/áudio dela, em ordem natural pelo nome, `0002` antes de `0010`), `number`, `bool`
  ou `list` (lista genérica). Se omitido, é inferido do `default` (texto vira `text`, `true`/`false`
  vira `bool`, lista vira `list`, número vira `number`); sem `default` também, o padrão é `text`.
- `required`: `true`/`false`. Se omitido, é `true` quando não há `default` e `false` quando há.
- `example`: um valor de exemplo (opcional). Aparece no resumo que a IA lê (`dmaker templates`, `list_templates`)
  e é o que os testes usam para preencher o parâmetro; serve sobretudo para uma lista de objetos, cujo formato
  não se adivinha pelo tipo.

## Placeholders

- `"{{nome}}"` sozinho como o valor inteiro de uma chave: vira o valor com o tipo original
  (número, lista, booleano, string), não uma substituição de texto. Exemplo: `"duration": "{{duracao}}"`
  com `duracao` do tipo `number` vira `"duration": 4` (número, não a string `"4"`). Um parâmetro `dir`
  já chega expandido: `"parts": "{{pasta}}"` vira a lista dos arquivos daquela pasta.
- `"{{nome}}"` dentro de um texto maior: interpolação simples (`str(valor)`). Exemplo:
  `"text": "Oi, {{nome}}!"`.
- `"{{item.campo}}"`: o campo de um parâmetro que é um objeto, em geral cada elemento de uma lista de objetos
  dentro de um `$for` (`"end": "{{assunto.fim}}"`). Campo que não existe é erro, com o nome dele na mensagem.

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

## Preparador de parâmetros: `prepare`

O JSON só substitui valores; ele não soma nem subtrai. Quando o template precisa de conta ou de uma
validação que o JSON não faz (a duração de cada assunto a partir do início e do fim, o tom de um fundo), a
chave `"prepare": "<nome>"` aponta para uma função pura registrada em `PARAM_PREPARERS`
(`src/dmaker/domain/templates.py`). Ela recebe os parâmetros já validados, devolve os mesmos mais os valores
derivados, e o JSON usa o resultado como qualquer outro parâmetro. Um `ValueError` da função vira
`TemplateError` com o nome do template. Um template novo nessa situação registra a sua função, sem mexer no
resto do motor. Hoje usam o `explicativo` (`src/dmaker/domain/explainer.py`) e o `audiograma`
(`src/dmaker/domain/audiogram_template.py`, que confere o estilo e monta o trecho de fundo).

Um parâmetro numérico pode declarar `"duration_of": "<outro parâmetro>"` (um arquivo de áudio ou vídeo): se o
pedido o omite, quem cria o projeto (`new-from-template`, `new_from_template`, a interface) mede o arquivo com o
probe e usa a duração dele. É assim que o `audiograma` dispensa o `duracao`. O motor de templates em si não
toca o disco: a medição fica em `pipeline/projects.py` (`with_media_durations`).

## Em lote: um vídeo por linha de uma planilha

Qualquer template serve de modelo para um lote (`dmaker batch run <template> <planilha>`, ferramenta MCP
`run_batch`, tela "Lote" da interface): cada linha da planilha preenche os parâmetros e vira um projeto e um
vídeo. O nome de cada coluna casa com o do parâmetro sem diferenciar maiúscula, acento, espaço, hífen ou
sublinhado; a célula é convertida para o `type` do parâmetro (número com vírgula decimal, `bool` com sim ou
não, `paths` e `list` separados por `|` ou vírgula, ou em JSON), e caminho relativo parte da pasta da
planilha. Célula vazia usa o `default`; parâmetro obrigatório vazio é erro daquela linha. Para o lote dar certo,
deixe os textos do template com folga (o QA aponta o que não cabe) e os caminhos fixos absolutos. Detalhes no
`dmaker://guide`, seção "Lote".

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
| `explicativo.json` | Vídeo explicativo em formato de reel: a gravação do apresentador num quadro arredondado embaixo, a área de cima (região `topo`) livre para a imagem ou o infográfico de cada assunto, legenda sobre o quadro e o fundo trocando a cada assunto. | `gravacao`, `assuntos` (obrigatórios), `legendas`, `legenda_modo`, `foco`, `marca` |
| `audiograma.json` | Audiograma para divulgar um corte de podcast, entrevista ou áudio de WhatsApp sem vídeo: a capa num círculo no meio, a onda ou as barras animadas no ritmo da fala (em volta da foto ou embaixo dela), o título no alto e a legenda automática. | `audio`, `capa` (obrigatórios), `titulo`, `estilo` (`circle`, `bars`, `wave`), `seguir`, `cor`, `fundo`, `legendas`, `legenda_modo`, `idioma`, `marca`; `duracao` omitida é a do áudio |
| `casamento-pascom.json` | Casamento comunitário padrão da PASCOM: duas câmeras com corte automático pela fala (bloco `multicam`), cartões da marca `pascom-sjb` e trilha na abertura e no encerramento. | `camera_altar`, `camera_lateral` (pastas, obrigatórios), `nomes`, `data` (obrigatórios), `titulo`, `igreja`, `cidade`, `celebrante`, `diacono`, `cerimonial`, `musicos`, `trilha`, `inicio`, `fim` |

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
- `casamento-pascom`: ao contrário do `casamento-multicam`, o corte entre as câmeras é automático:
  o template só monta os cartões e um bloco `multicam` (câmeras, fase da cerimônia, janela de
  `inicio`/`fim`); depois de `new_from_template`, rodar `plan_multicam` uma vez para transcrever a
  câmera de áudio, reconhecer as fases da cerimônia e substituir o bloco pelos clipes de verdade,
  antes de validar ou renderizar. Os cartões (abertura, créditos, encerramento) vêm dos
  `card_layouts` da marca `pascom-sjb` (`assets/brands/pascom-sjb/brand.json`), não do visual
  genérico do tema. A música usa `from_end`/`tail` em `MusicSpan` porque a duração final só se sabe
  depois do `plan_multicam`: a segunda janela conta a partir do fim do vídeo e toca o final da
  faixa.

- `explicativo`: o formato é de reel (`instagram/reels`), com as regiões `topo` e `rosto` já nas medidas do
  Reels. A gravação é UMA sobreposição de vídeo contínua (por isso a fala não é cortada na troca de fundo) e
  cada assunto é um cartão de cor lisa (`flat`) ou uma imagem de fundo, em corte seco, para os limites dos
  assuntos não se moverem. Os assuntos precisam se emendar e o fim do último é a duração do vídeo; o
  preparador `explicativo` confere isso e a mensagem de erro diz qual assunto está fora. As regiões ficam
  na spec (`regions`) para infográficos e composições se encaixarem nelas por nome; ver "Regiões nomeadas" no
  `dmaker://guide`. A legenda usa `follow_background: false` (fica sempre sobre o vídeo do rosto, qualquer que
  seja o fundo) e o estilo `rounded` por padrão. A sombra do quadro fica desligada: a moldura do
  picture-in-picture corta a própria sombra e a borda aparece sobre fundo claro.

Caminhos de mídia que mudam a cada uso (vídeos, prints, gravações) ficam sempre `required`, sem
`default`. Textos e caminhos que servem de exemplo claro (trilha padrão, nomes de exemplo) ficam
com `default`, editável a qualquer momento.

## Infográficos prontos (`html/`)

A subpasta `html/` não tem modelos de projeto: cada pasta dela é um **infográfico animado pronto** (`contador`, `barra`,
`linha`, `imagem`, `etiqueta`, `grifo`, `emoji`), uma composição em HTML com os parâmetros declarados num `esquema.json`
ao lado do `index.html`. Na spec, `{"type": "html", "infographic": "contador", "region": "topo", "data": {"ate": 10000}}`
usa o modelo pelo nome; `dmaker infographics list` mostra os parâmetros e `dmaker infographics frame` desenha um quadro.
Para escrever um modelo novo, copie a pasta do `contador` (o contrato e o formato do esquema estão no `dmaker://guide`,
seção "Infográficos prontos"): o desenho de cada instante sai de `window.dmakerSeek(t)`, a marca vem só das variáveis
`--dm-*` e o modelo não traz fundo.
