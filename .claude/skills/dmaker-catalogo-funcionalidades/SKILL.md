---
name: dmaker-catalogo-funcionalidades
description: Atualiza o catálogo de funcionalidades do DMaker, a lista, em linguagem de cliente, do que o editor faz hoje na main, cruzando o CHANGELOG da main, os comandos da CLI, as ferramentas MCP, as seções da interface e os chamados Concluído do Jira (projeto DMK). Use sempre que o Douglas pedir "as funções do DMaker", "o que o DMaker faz", "lista de funcionalidades", "atualiza o catálogo", "o que já está lançado", material para apresentação ou proposta, ou logo depois de lançar uma versão, quando ele quiser saber o que ganhou. Vale também quando ele descreve o pedido sem nomear o catálogo ("preciso listar tudo que o editor tem pra mostrar pra alguém"). Para saber o que ainda falta desenvolver, o caminho é o Jira (dmaker-rodada), não esta skill.
---

# Catálogo de funcionalidades: DMaker

Produz e mantém `docs/funcionalidades.md`: o que o DMaker entrega **para quem o
usa**, escrito para uma pessoa que edita vídeo para uma igreja, uma clínica, um
casamento ou uma rede social, e não sabe (nem quer saber) o que é um filtergraph
ou um mezanino.

O documento é reconstruído a cada versão lançada, não editado a esmo. O valor
está em duas coisas que só saem do levantamento honesto: **estar em dia com o que
a `main` de fato tem** e **não conter uma linha de jargão**.

Não confunda com `docs/MANUAL.md`: o manual ensina a **operar** (instalar, usar,
resolver problema); o catálogo diz **o que existe**. Não edite o manual por aqui.

Leia junto:

- `.claude/skills/_comum/jira.md`: cloudId, colunas, como consultar sem estourar tokens
- `.claude/skills/_comum/git.md`: convenções de branch e commit

## O que conta como "lançado"

O lançado é a branch **`main`**. Nada mais conta:

- A árvore de trabalho local **não** é referência. Você pode estar num branch de
  feature com meia versão nova dentro.
- O bloco `## [Não lançado]` do CHANGELOG é a `develop`. É exatamente o que **não**
  entra no catálogo.
- Card em `Concluído` (ou em `Teste Manual`) no Jira também não prova nada
  sozinho: ele está na `develop`, aprovado ou não, mas a coluna não conhece a data
  do release nem se a `develop` já subiu para a `main` (`_comum/jira.md`).

A versão lançada é o **primeiro cabeçalho `## vX`** do CHANGELOG **da main**:

```bash
git fetch origin main
git show origin/main:CHANGELOG.md | grep -nE "^## v|^## Linha de base" | head -5
```

Se o topo trouxer `[Não lançado]` com conteúdo, a versão ainda não foi fechada:
pergunte ao Douglas antes de seguir, porque o catálogo passaria a anunciar o que
ninguém tem. Se ainda não houver nenhum `## vX` (só a `## Linha de base`), o
catálogo descreve a linha de base e diz "versão: linha de base de <data>".

**Cuidado com o que está "em teste manual" na linha de base.** O estúdio de voz
(DMK-9 a DMK-15) já está na `main`, mas ainda está sendo testado pelo Douglas.
Antes de anunciar um recurso assim como pronto, **pergunte** se entra no catálogo
ou vai na seção "Em teste, ainda não disponível" (abaixo).

## Confirme no código, não no texto

O CHANGELOG diz o que se pretendeu entregar. O código diz o que existe. Eles
divergem por motivos banais e recorrentes: card que voltou em redesenvolvimento e
teve escopo cortado, funcionalidade descrita antes de o recorte final ser
decidido, recurso que depende de modelo que ninguém instalou.

Antes de escrever cada bloco grande do catálogo, confirme que a coisa existe na
`main` de verdade, lendo da `origin/main` e não do disco:

```bash
# o comando existe?
git show origin/main:src/dmaker/cli.py | grep -n "add_typer\|@app.command"

# a ferramenta MCP existe?
git show origin/main:src/dmaker/mcp_server.py | grep -n "@mcp.tool\|def "

# o módulo existe?
git ls-tree -r --name-only origin/main | grep -i "dubbing\|separation\|matting"
```

`dmaker --help` só vale se a árvore local **estiver na `main` e limpa**; senão ele
mostra o código do branch em que você está. Foi assim que, no MedlyCare, itens
ficaram de fora do catálogo de agosto/2026: estavam no CHANGELOG do working tree e
não existiam na `main`.

## Onde levantar o que o editor faz

O CHANGELOG do DMaker só começa na linha de base de 2026-10-22; tudo que nasceu
antes está resumido lá em poucas linhas, e um catálogo tirado só dele nasce
incompleto. Cruze as fontes:

| Fonte | Comando | O que dá |
| --- | --- | --- |
| CHANGELOG da main | `git show origin/main:CHANGELOG.md` | o que mudou, com o porquê |
| CLI | `cli.py` na main e os sub-apps `voice`, `audio`, `dub` (`dmaker <app> --help`) | o que dá para fazer por comando |
| Ferramentas MCP | `mcp_server.py` na main e o guia `dmaker://guide` | o que uma IA (Claude, Ollama) consegue operar |
| Interface | `src/dmaker/ui/static/index.html` na main | as abas (Linha do tempo, Propriedades, JSON, Preview, Voz, Legendas) e os botões |
| Modelos e marcas | `templates/*.json`, `domain/presets.py`, `assets/brands/` | formatos de saída, modelos prontos, marcas |
| Jira concluído | `project = DMK AND statusCategory = Done ORDER BY key ASC` | o histórico dos cards |

O histórico do git é um atalho barato para o que veio antes do CHANGELOG, e não
estoura contexto como a resposta do Jira:

```bash
git log --pretty=format:"%s" origin/main | head -40
```

Se for consultar o Jira, peça só `["summary","status"]`: a resposta padrão traz
avatares e URLs por issue e estoura o contexto. Não há `jq` nesta máquina; leia
JSON salvo com PowerShell + `ConvertFrom-Json`.

## Como escrever cada linha

O leitor edita vídeo, não programa. Ele não compra "mezanino em cache por hash",
compra "ajustar um detalhe e refazer o vídeo em segundos, sem renderizar tudo de
novo".

Cada linha responde **o que a pessoa consegue fazer** e, quando houver, **o que
isso poupa**. Traduza, não resuma:

| Não escreva | Escreva |
| --- | --- |
| Correlação de áudio para sincronizar fontes multicâmera | Sincroniza as câmeras sozinho pelo som, sem marcar palma |
| Transcrição via faster-whisper com tempo por palavra | Legendas automáticas, com cada palavra aparecendo na hora em que é dita |
| Isolamento vocal com Demucs | Separa a voz da música e do ruído de fundo |
| Dublagem via OmniVoice com clonagem e tradução por LLM local | Dubla o vídeo em outro idioma mantendo a voz de quem fala, tudo no seu computador |
| Matting RVM por ONNX | Recorta a pessoa do fundo sem tela verde |

Três coisas merecem aparecer porque quem escolhe a ferramenta decide com base
nelas, e nenhuma é jargão:

- **O que roda 100% no computador dele**, sem enviar nada para a internet: voz,
  transcrição, separação de áudio, tradução com o modelo local. Confira no código
  o que de fato é local antes de prometer.
- **O que é opcional e precisa de instalação a mais**: legendas (`captions`),
  estúdio de voz (`voice`), modelo de tradução do Ollama. Diga o que cada um pede
  em uma frase (sem comando).
- **Para quais redes e formatos exporta**: Instagram (Reels, Stories, Feed),
  Facebook, YouTube (Shorts e vídeo), TikTok, WhatsApp, LinkedIn. Confira a lista
  atual em `domain/presets.py` na `main`.

### O que fica de fora

Nada disso entra: refatoração, atualização de dependência, desempenho, testes,
mudança de estrutura interna, e a maior parte das correções de bug: consertar
algo que já deveria funcionar não é funcionalidade nova.

A exceção é o bug cuja correção **criou capacidade**: uma correção que passou a
permitir algo que antes não dava é uma coisa nova que o usuário pode fazer.

**Nenhum nome de cliente, de casal ou de projeto real** no catálogo. Os modelos
prontos entram pelo que são ("modelo de casamento com duas câmeras"), nunca pelo
cliente para quem foram feitos. Vozes clonadas são dado pessoal: o catálogo fala
do recurso, nunca de uma voz específica.

## Estrutura do documento

Mantenha estas seções, nesta ordem. Elas seguem o caminho de quem faz um vídeo
(começar → montar → falar → entregar), e não o desenho do sistema:

```markdown
# DMaker: o que o editor faz
_Atualizado em <data> · versão <vX> (ou linha de base de <data>)_

## Começar um vídeo        ← modelos prontos, projeto a partir de arquivos, edição rápida
## Montar e editar         ← trechos, cartões, textos, picture-in-picture, multicâmera, linha do tempo
## Legendas
## Voz e dublagem          ← só quando houver algo lançado
## Áudio                   ← música, volume, isolamento vocal
## Formatos e entrega      ← redes sociais, exportar vários de uma vez, capa
## Marcas e modelos
## Conferir antes de publicar   ← validação, relatório de qualidade, prévia
## Usando pela interface, pelo terminal ou com uma IA
```

Seção sem nada lançado **sai** do documento: um título vazio faz o leitor procurar
o que não existe. Uma linha por funcionalidade, começando por um verbo ou pelo
substantivo do recurso; sem número de card, sem nome de arquivo, sem versão no
meio do texto.

## O passo a passo

1. **Confirme a versão lançada** pelo CHANGELOG da `origin/main` e diga ao
   Douglas qual é, antes de trabalhar. Se ele pediu logo depois de um release,
   confirme que o merge já está na `main`, não na `develop`.
2. **Levante as fontes** e monte a lista bruta, ainda com jargão.
3. **Confirme no código** o que veio do CHANGELOG, com `git show origin/main:` e
   `git ls-tree origin/main`. O que não existir na `main` sai.
4. **Traduza** cada linha para linguagem de cliente e agrupe nas seções.
5. **Compare com o catálogo anterior** (`git diff` no `docs/funcionalidades.md`)
   e guarde o que entrou e o que saiu: é o que o Douglas quer ler primeiro.
6. **Grave** `docs/funcionalidades.md` e commite num branch próprio
   (`docs/catalogo-vX`, saindo da `develop`) com PR para a `develop`, seguindo
   `_comum/git.md`. É documentação: não precisa de card, mas não vá direto na
   `main` nem na `develop`. Commit: `docs: atualiza o catálogo de funcionalidades`.
   Portões de texto: sem travessão, e `ruff` e `pytest` só se você tocou em algo
   além do `.md` (normalmente não).
7. **Responda no chat** com o resumo do que mudou desde a última versão do
   catálogo, não com o documento inteiro colado. Ele acabou de pedir o arquivo;
   repetir o conteúdo é ruído.
8. **Ofereça publicar como artifact** quando o destino for apresentação ou
   proposta. Não publique sem ele pedir.

## Quando ele quiser incluir o que está em teste

Acontece: material de divulgação às vezes precisa falar do que vem aí. Nesse caso
o que está na `develop` (ou em `Teste Manual`) vai numa seção separada e
claramente rotulada (**"Em teste, ainda não disponível"**), nunca misturado às
linhas do que está lançado. Quem se interessa por uma linha que ainda não saiu
vira um problema seu, não do documento.

Se ele não disser nada, o padrão é **só o que está na `main`**.
