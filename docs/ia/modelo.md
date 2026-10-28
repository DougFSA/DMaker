# Criar um projeto a partir de um modelo pronto

Tarefa `modelo` do manual do DMaker. Cria um projeto completo de um modelo pronto (produto, depoimento, stories, vlog, tutorial, YouTube, explicativo, casamento), passando só o que muda de vídeo para vídeo.

## Quando usar

O vídeo que você quer já cabe num dos modelos de `templates/`: é o caminho mais rápido e o que o agente local faz melhor. Sem modelo que sirva, escreva a spec (veja "Escrever a spec na mão").

**Pedidos que levam a esta tarefa:**
- "Faz um story com esse print e a pergunta 'Chegou sem hora marcada?'"
- "Monta um reel de produto com esses três prints"
- "Quais modelos de vídeo existem?"

## O que perguntar antes

- Que tipo de vídeo é (produto, depoimento, story, vlog, tutorial, explicativo) para escolher o modelo.
- Os arquivos que o modelo pede (prints, vídeos) com o caminho completo: são os parâmetros obrigatórios (`list_templates` marca quais). Pergunte só o que falta deles.
- Os textos (título, gancho, CTA) têm padrão no modelo: se o usuário não deu um texto, use o padrão e siga em frente, sem perguntar.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `list_templates`: escolher o modelo e ver os parâmetros de cada um
   Argumentos de exemplo: `{}`
2. `new_from_template`: criar o projeto
   Argumentos de exemplo: `{"template": "stories-medlycare", "name": "story-dica", "params": {"print": "C:/imagens/agenda.png", "titulo": "Chegou sem hora marcada?", "texto": "A fila de espera organiza quem chega e avisa o profissional"}}`
3. `validate_project`: ver a duração e os avisos
   Argumentos de exemplo: `{"name_or_path": "story-dica"}`
4. `render_project`: gerar a prévia
   Argumentos de exemplo: `{"name_or_path": "story-dica", "preview": true}`
5. `qa_report`: conferir antes da versão final
   Argumentos de exemplo: `{"name_or_path": "story-dica", "output": false}`
6. `render_project`: gerar a versão final
   Argumentos de exemplo: `{"name_or_path": "story-dica"}`

## Equivalente na CLI

```powershell
dmaker templates
dmaker new-from-template stories-medlycare story-dica --param print=prints\agenda.png --param titulo="Chegou sem hora marcada?"
dmaker validate projects\story-dica\spec.json
dmaker render projects\story-dica\spec.json --preview
dmaker render projects\story-dica\spec.json
```

`--param chave=valor` repete para cada parâmetro (listas separadas por vírgula); `--params-json '{"titulo": "..."}'` passa tudo de uma vez. Os modelos: `reel-medlycare-produto` (capturas de tela com movimento e CTA), `reel-medlycare-depoimento` (um corte com gancho e crédito), `stories-medlycare` (uma dica sobre um print), `pessoal-vlog-reel` (vídeos em sequência com título e trilha), `youtube-longo` (abertura, gravação, CTA), `tutorial-tela-webcam` (tela e webcam em picture-in-picture), `explicativo` (veja a tarefa própria), `casamento-multicam` e `casamento-pascom` (veja "Fazer o vídeo do casamento com duas câmeras"). `dmaker templates` mostra os parâmetros de cada um.

## Como conferir

`dmaker validate` mostra a duração final e os avisos (limite da plataforma, regra da marca, arquivo faltando). A prévia em `output/` confirma corte, texto e ritmo. O formato de um arquivo de modelo (para criar um novo) está em `templates/README.md`.

## Erros comuns

- **"parâmetro obrigatório ausente"**: a mensagem nomeia o parâmetro; confira com `dmaker templates`.
- **Arquivo não encontrado**: caminhos relativos partem da pasta do projeto; prefira o caminho completo com barra `/`.
- **Aviso de travessão**: a regra da marca proíbe travessão em texto na tela; troque por vírgula ou dois-pontos.
