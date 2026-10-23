---
name: dmaker-mapa-de-testes
description: Monta e publica como Artifact o mapa de teste manual de uma versão do DMaker no Jira (projeto DMK): onde sentar para testar cada chamado (qual branch fazer checkout), agrupado por pilha de branch e não por PR, com o que olhar ou ouvir em cada um e uma lista de marcar que fica salva no navegador. Use sempre que o Douglas pedir "o mapa de testes", "me diz qual chamado testo em qual branch", "onde eu testo cada coisa", "gera o mapa de novo", "atualiza o mapa" ou qualquer variação de "por onde eu começo a testar o DMaker". Também serve depois de uma leva de entregas, quando ele vai começar o teste manual da versão.
---

# Mapa de testes: DMaker

Responde uma pergunta só: **onde ele senta para testar o que ainda falta.**

Leia junto:

- `.claude/skills/_comum/jira.md`: colunas, transições, consultas
- `.claude/skills/_comum/git.md`: convenções de branch e PR empilhada

## O que o mapa é, e o que ele não é

Ele **não** é uma lista de PRs. É uma lista de **postos de teste**.

Uma pilha de sete branches é um checkout só: o topo contém as seis anteriores, e
ele testa as sete de lá sem trocar de branch. Uma lista PR a PR faria ele
levantar sete vezes, e é justamente o trabalho que o mapa existe para poupar. No
DMaker a regra é cada card sair da `develop`, então quase todo posto será avulso;
pilha aparece só quando um card depende de outro de verdade.

Quatro tipos de posto, nesta ordem:

1. **Pilhas ainda em teste**: um posto por pilha, o topo dela como lugar de sentar.
2. **Avulsos**: chamados em `Teste Manual` que saíram direto da `develop` e não se
   empilham. Um checkout cada, e a ordem entre eles não importa. Diga isso.
3. **Na develop**: chamados em `Teste Manual` cujo código **já está mergeado** na
   `develop` (voltaram do `dmaker-redesenvolvimento-develop`). Um único posto: a
   própria `develop`. Ele não troca de branch, só atualiza.
4. **Já aprovado**: o que ele mesmo já moveu para `Concluído` e cujo PR ainda está
   aberto (esperando o `dmaker-merge-develop`). Entra no mapa **sem nada a
   testar**, só para ele não procurar; some quando mergear. Card em `Concluído`
   sem PR aberto fica de fora: já está na `develop` ou na `main`.

Um posto vazio não entra. Se a versão inteira já está aprovada, o mapa é curto e
o relatório diz isso.

## 1. Pergunte a versão

Sempre, mesmo que uma pareça óbvia. Uma pergunta curta basta.

## 2. Levante os fatos

Três fontes, e nenhuma substitui a outra.

**Jira**, para saber o que ainda se testa:

```
project = DMK AND fixVersion = "<versão>" ORDER BY key ASC
```

Guarde chave, título e **status**. É o status que separa os postos: `Teste
Manual` vai para os postos de teste (pilha, avulso ou develop, conforme o PR);
`Concluído` com PR aberto vai para o posto de aprovados; `Concluído` sem PR aberto
fica de fora, com uma exceção, abaixo. Card em `Redesenvolvimento`,
`Em desenvolvimento`, `Backlog` ou `Aguardando Atendimento` não é testável: não
entra num posto, vai numa nota do fecho dizendo o status.

**GitHub**, para as PRs e as bases:

```bash
gh pr list --state open --limit 60 --json number,title,headRefName,baseRefName
```

Para cada card em `Teste Manual`, descubra se o PR está aberto ou se o código já
está na `develop` (`git log --oneline origin/develop | grep -i DMK-XXX`): isso
decide entre os postos "pilha/avulso" e "na develop".

**O git**, para a ancestralidade, e este é o passo que não se pula.

### Confirme a pilha por ancestralidade, nunca pela base da PR

A base de uma PR diz o que alguém *pretendia*. `git merge-base` diz o que a
branch **contém**. Os dois divergem toda vez que uma PR do meio da pilha é
mergeada e o GitHub re-aponta as bases, e o mapa que confia na base manda ele
testar de um lugar que não tem o código.

```bash
git fetch -q origin
git merge-base --is-ancestor origin/<branch-de-baixo> origin/<branch-do-topo> \
  && echo contido || echo FALTA
```

Rode para **cada** branch da pilha contra o topo candidato. Um "FALTA" quebra a
premissa do posto: ou o topo é outro, ou aquele chamado vira avulso. Nunca
publique um posto de pilha sem ter rodado isto.

Confirme também se duas pilhas se cruzam. Quando não se cruzam, diga no mapa que
são independentes: é o que autoriza ele a testar as duas em qualquer ordem.

**A prova de que o PR está pronto**, por último. Não há CI, então
`gh pr checks` vem vazio e não prova nada. O que vale é o comentário de entrega do
card trazer a validação técnica (`ruff` e `pytest` com contagem). Entrega sem isso
não entra como testável: diga no relatório e mande consertar antes.

## 3. Escreva o "o que olhar"

Uma linha por chamado, e é a parte que dá valor ao mapa. Ela sai do **comentário
de entrega no Jira**, não do título do card: o título diz o que o card era, o
comentário diz o que mudou e o que costuma quebrar.

Escreva a ação, não o resumo. "Abra o projeto de dublagem, gere com a voz clonada
e confira o texto do primeiro trecho na transcrição" serve; "correção de
sincronismo na dublagem" não serve, porque não diz o que fazer. Inclua, quando
couber, **como testar**: o comando (`dmaker ui`, `dmaker render <projeto>
--preview`, `dmaker voice ...`) e o arquivo de exemplo em `output/`, se o
comentário de entrega apontar um.

O posto de sentar ganha também a receita de preparo, no `nota` do posto:

```
git checkout <branch>      # o topo da pilha, ou o branch do avulso, ou develop
git pull                   # se for a develop
pip install -e .           # só se o card mudou dependência (pyproject.toml)
dmaker ui                  # ou a CLI do card
```

Lembre: `projects/`, `output/`, `cache/` e `assets/voices/` não são versionados,
então sobrevivem à troca de branch. Se o card mexeu na receita do mezanino, o
cache se renova sozinho (`MEZZ_VERSION`), mas o primeiro render é mais lento.

Marque com `selo` o que merece atenção fora do normal:

- chamado corrigido depois que ele já tinha visto;
- chamado que exige instalação (extra do pip, modelo que baixa na primeira vez);
- card `Concluído` cujo conteúdo foi reescrito depois por outro card: este é o
  caso que justifica trazer um concluído de volta para o mapa, com o selo
  dizendo por quê.

## 4. Preencha o template

O visual **não se reescreve**. Ele está em `mapa.template.html`, ao lado deste
arquivo, e a skill troca só o bloco `DADOS`, delimitado por comentários no
próprio arquivo. Mapa da v1 e mapa da v3 têm que parecer a mesma página.

```js
const DADOS = {
  versao: '1',
  titulo: 'Onde sentar para testar o que falta',
  lede: 'Duas ou três linhas dizendo como a versão está dividida.',
  placar: [
    { valor: '8', rotulo: 'a testar', tom: 'teal', id: 'restam' },
    { valor: '3', rotulo: 'já em Concluído', tom: 'done' },
    { valor: '9', rotulo: 'PRs abertas' },
  ],
  postos: [
    {
      titulo: 'Pilha da dublagem',
      modo: 'Um checkout, três chamados',
      estilo: 'pilha',            // 'pilha' | 'avulso' | 'pronto'
      nota: 'Confirmei por ancestralidade: o branch abaixo contém os dois anteriores.',
      onde: { rotulo: 'Sente em', branch: 'feat/dmk-14-dublagem-...', pr: 12 },
      itens: [
        {
          chave: 'DMK-12',
          titulo: 'Dublagem: troca a voz mantendo o ritmo',
          olhar: 'Gere a dublagem e compare a duração de cada trecho com o original.',
          selo: null,             // ou 'corrigido hoje', 'baixa um modelo'...
          pr: null,               // só nos avulsos; na pilha o PR está em `onde`
          contaComoTeste: true,   // false no posto de aprovados
        },
      ],
    },
  ],
  tituloFecho: 'Na hora de mergear',
  avisos: ['**O CHANGELOG vai conflitar.** ...'],
  notas: ['**DMK-20** ainda não foi desenvolvido.'],
  assinatura: 'Pilhas conferidas por ancestralidade de commit, não por leitura das PRs.',
};
```

Detalhes que o template já resolve, e que você não precisa montar à mão:

- `DMK-xxx` em `chave` vira link para o Jira; `pr` vira link para o GitHub
  (`github.com/DougFSA/DMaker`).
- Em `nota`, `olhar`, `lede`, `avisos` e `notas` valem `` `código` ``, `*ênfase*`
  e `**forte**`. Todo o resto é escapado, porque o texto vem de card e de
  comentário e dado não pode virar marcação.
- O chip com `id: 'restam'` é recalculado sozinho conforme ele marca; itens com
  `contaComoTeste: false` ficam fora da conta.
- A marcação fica no `localStorage` do navegador dele, com a versão na chave, e
  não se perde ao republicar.

Copie o template para o scratchpad, troque o bloco `DADOS` e o `vVERSAO` do
`<title>`, e publique com o Artifact. Nunca edite o template no lugar. Sem
travessão em nenhum texto do mapa (regra da marca; vale para o que o Douglas lê).

## 5. Publique e relate

Publique com título `Mapa de testes v<N>` e ícone `map`.

**Mapa da mesma versão já publicado?** Republique na mesma URL em vez de criar
outro: ele pode ter marcações e o link pode estar aberto no celular. Se a URL
não estiver nesta conversa, ache com `action: "list"` antes de publicar.

No chat, não repita o mapa. Diga só:

- o que mudou desde o último mapa (o que ele já aprovou é a mudança mais comum);
- em quantos lugares ele precisa sentar, e quais;
- os um ou dois itens que merecem ser os primeiros, com o motivo;
- o que ficou de fora da versão e continua pendente.

## Delegação

Levantar Jira, PRs e estado de merge é trabalho de `dmaker-apurador`, e ler o
comentário de entrega de cada card para escrever o "o que olhar" é o que mais pesa
quando a versão tem mais de oito chamados. Peça a ele, por card: chave, título,
status, PR (e se está aberto), e **duas linhas do comentário de entrega, com o que
testar** e o comando ou arquivo de exemplo.

A ancestralidade, a montagem dos postos e o texto do mapa ficam com você: é onde
o mapa acerta ou erra.
