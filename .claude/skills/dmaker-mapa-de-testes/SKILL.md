---
name: dmaker-mapa-de-testes
description: Monta e publica como Artifact o mapa de teste manual do DMaker a partir do Jira (projeto DMK): a lista do que testar agora na develop, ou seja, os chamados em Teste Manual, agrupados por área, com o que olhar ou ouvir em cada um e uma lista de marcar que fica salva no navegador. Tudo se testa na develop, então não há branch para fazer checkout. Use sempre que o Douglas pedir "o mapa de testes", "o que eu testo agora", "o que tem pra testar no DMaker", "gera o mapa de novo", "atualiza o mapa" ou qualquer variação de "por onde eu começo a testar o DMaker". Também serve depois de uma leva de entregas, quando ele vai começar o teste manual da versão.
---

# Mapa de testes: DMaker

Responde uma pergunta só: **o que ele tem para testar agora, e o que olhar em cada
coisa.**

Leia junto:

- `.claude/skills/_comum/jira.md`: colunas, transições, consultas
- `.claude/skills/_comum/git.md`: o fluxo de entrega (tudo entra na `develop` na entrega)

## O que o mapa é, e o que ele não é

Desde 23/10/2026 o executor mergeia o PR na `develop` ao entregar o card, e o
Douglas testa **sempre pela `develop`**. Não há mais "qual branch fazer checkout",
pilha de branches nem PR aberto esperando aval. O mapa deixou de ser um mapa de
lugares e virou uma **lista do que testar na `develop` agora**.

Ele **não** é uma lista de PRs nem um relatório de entrega. É o roteiro de teste,
agrupado por **área**, para ele testar de uma vez tudo que mexe na mesma parte do
editor (uma passada pela interface de voz serve a todos os cards de voz).

Os postos agora são áreas, e só têm cards em `Teste Manual`:

1. **Uma área por posto**, pelo rótulo do card (`voz`, `dublagem`, `interface`,
   `audio`, `render`, `testes`, `desempenho`; o prefixo do título, `Voz:`,
   `Dublagem:`, serve de reserva). Card com dois rótulos entra na área do
   comportamento que mais pesa e o `olhar` cita a outra.
2. **Dentro da área**, ponha primeiro o que foi **corrigido num redesenvolvimento**
   (ele já viu o defeito e quer confirmar o conserto), depois o resto por chave.
3. Área sem card em `Teste Manual` não entra no mapa. Se nada está em
   `Teste Manual`, o mapa é uma frase: "não há nada para testar", e o relatório
   diz o que está em desenvolvimento ou em redesenvolvimento.

Cards em `Concluído` não aparecem (já foram testados e aprovados). Cards em
`Redesenvolvimento`, `Em desenvolvimento`, `Backlog` ou `Aguardando Atendimento`
não são testáveis: vão numa nota do fecho, com o status.

## 1. Pergunte a versão

Sempre, mesmo que uma pareça óbvia. Uma pergunta curta basta.

## 2. Levante os fatos

**Jira**, para saber o que ainda se testa:

```
project = DMK AND fixVersion = "<versão>" ORDER BY key ASC
```

Guarde chave, título, rótulos e **status**. `Teste Manual` (id 10075) é o que vai
para os postos.

**O git**, para confirmar que o que o Jira diz está de fato na `develop`:

```bash
git fetch -q origin
git log --oneline origin/develop | grep -i DMK-XXX
```

(case-insensitive: há commits com a chave em minúsculas). Card em `Teste Manual`
**sem** commit na `develop` é anomalia, não é testável: não entra num posto; diga
no relatório (a entrega não mergeou, ou o merge se perdeu).

**A prova de que o card está pronto para testar.** Não há CI, então o que vale é o
comentário de entrega do card trazer a validação técnica (`ruff` e `pytest` com
contagem) e o commit de merge. Entrega sem isso não entra como testável: diga no
relatório.

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

O mapa tem **um** preparo, que vale para todos os postos, e vai no `lede`:

```
git checkout develop && git pull
pip install -e .           # só se algum card mudou dependência (pyproject.toml)
dmaker ui                  # ou a CLI do card
```

Lembre: `projects/`, `output/`, `cache/` e `assets/voices/` não são versionados,
então sobrevivem à atualização da `develop`. Se algum card mexeu na receita do
mezanino, o cache se renova sozinho (`MEZZ_VERSION`), mas o primeiro render é mais
lento.

Marque com `selo` o que merece atenção fora do normal:

- chamado corrigido depois que ele já tinha visto (`corrigido`);
- chamado que exige instalação (extra do pip, modelo que baixa na primeira vez);
- chamado cuja área foi mexida por **outro** card da mesma leva: é onde os
  defeitos de integração aparecem, e o selo diz qual era o outro.

## 4. Preencha o template

O visual **não se reescreve**. Ele está em `mapa.template.html`, ao lado deste
arquivo, e a skill troca só o bloco `DADOS`, delimitado por comentários no
próprio arquivo. Mapa da v1 e mapa da v3 têm que parecer a mesma página.

```js
const DADOS = {
  versao: '1',
  titulo: 'O que testar na develop',
  lede: 'Tudo está na `develop`: rode `git checkout develop && git pull` e teste por área.',
  placar: [
    { valor: '8', rotulo: 'a testar', tom: 'teal', id: 'restam' },
    { valor: '3', rotulo: 'áreas' },
  ],
  postos: [
    {
      titulo: 'Dublagem',
      modo: '3 chamados',
      estilo: 'pilha',            // 'pilha' (destaque) | 'avulso' | 'pronto'
      nota: 'Uma passada pela tela de dublagem serve aos três.',
      // `onde` é opcional: omita (a `develop` já está no lede). Use só se um
      // chamado exigir um lugar diferente.
      itens: [
        {
          chave: 'DMK-12',
          titulo: 'Dublagem: troca a voz mantendo o ritmo',
          olhar: 'Gere a dublagem e compare a duração de cada trecho com o original.',
          selo: null,             // ou 'corrigido', 'baixa um modelo'...
          pr: 12,                 // PR já mergeado (link de registro)
          contaComoTeste: true,
        },
      ],
    },
  ],
  tituloFecho: 'Para lembrar',
  avisos: ['**Atualize a `develop` antes de cada sessão**: ela recebe entregas o tempo todo.'],
  notas: ['**DMK-20** ainda não foi desenvolvido.'],
  assinatura: 'Cada chamado conferido no log da `develop`; o que não estava lá ficou de fora.',
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

- o que mudou desde o último mapa (o que ele já aprovou e o que chegou novo são as
  mudanças mais comuns);
- quantas áreas e quantos chamados ele tem para testar;
- os um ou dois itens que merecem ser os primeiros, com o motivo;
- o que ficou de fora da versão e continua pendente, e qualquer anomalia (card em
  `Teste Manual` sem commit na `develop`).

## Delegação

Levantar Jira e conferir o log da `develop` é trabalho de `dmaker-apurador`, e ler o
comentário de entrega de cada card para escrever o "o que olhar" é o que mais pesa
quando a versão tem mais de oito chamados. Peça a ele, por card: chave, título,
rótulos, status, o commit na `develop` (ou a ausência), e **duas linhas do
comentário de entrega, com o que testar** e o comando ou arquivo de exemplo.

O agrupamento por área, a ordem e o texto do mapa ficam com você: é onde o mapa
acerta ou erra.
