# Git: um chamado, um PR, mergeado na entrega

Referência compartilhada pelas skills do DMaker e pelos subagentes
`dmaker-executor` e `dmaker-apurador`.

Remoto: https://github.com/DougFSA/DMaker. Branches de longa vida: `main`
(o que está lançado) e `develop` (o que foi entregue e ainda não foi lançado: o
Douglas testa **sempre por ela**). A `develop` sai da `main` e é criada pelo
Douglas; se ela não existir, **pare e avise**, não crie por conta própria.

## O fluxo em uma frase

Cada chamado sai da `develop` num branch, passa pelos portões locais, vira PR, o
executor **mergeia o PR na hora** e só então move o card para `Teste Manual`. O PR
fica como registro e revisão; o branch não precisa sobreviver ao merge.

Como a `develop` agora recebe código **antes** do teste manual, ela deixou de ser
"o que foi aprovado" e passou a ser "o que foi entregue". Um portão que passou em
falso não fica retido num PR esperando: ele já está na `develop` quando o Douglas
vai testar. Por isso os portões locais (`_comum/qualidade.md`) e a conferência na
ponta da `develop` (abaixo) pesam mais do que antes.

## Convenções

- **Branch:** `feat/dmk-XXX-slug-curto` para funcionalidade, `fix/dmk-XXX-slug-curto`
  para correção; correção de redesenvolvimento: `fix/dmk-XXX-ajuste-N` (N é a
  rodada). Slug em minúsculas, sem acento. Sempre sai da `develop`.
- **Commit:** `tipo(DMK-XXX): resumo no imperativo, sem acento, até 72 colunas`.
  O corpo explica **por que**, não o que: o diff já diz o que. Termina com a
  atribuição `Co-Authored-By` **indicada na sessão de quem commita** (cada sessão
  informa o seu modelo; não copie o de outra, nem de memória).
- **Corpo do PR:** mesma explicação do comentário do Jira, e termina com:
  ```
  🤖 Generated with [Claude Code](https://claude.com/claude-code)
  ```
- **Nunca** commitar direto na `main` nem na `develop`: tudo entra por PR. A única
  exceção por escrito é o fechamento do CHANGELOG no `dmaker-producao`.

## Dependência entre cards: ordem, não pilha

Por padrão, todo chamado sai da `develop`. Se o card B usa algo que só existe no
card A, **o A entra primeiro**: como a entrega do A já termina em merge, o B sai da
`develop` depois dele, sem empilhar nada. Não existe mais pilha de branches nem
PR com base que não seja a `develop`.

Isso encerra de vez o engarrafamento que o MedlyCare viveu em agosto/2026, quando
uma rodada virou 19 branches encadeados por ordem de execução e um card reprovado
lá embaixo prendeu 13 aprovados acima dele. Aqui um card reprovado simplesmente
volta para `Redesenvolvimento` e é corrigido na `develop` por cima, sem prender
ninguém.

Se o B depende do A e o A ainda não terminou, o B espera (ou o planejador reordena
a fila). Executores em paralelo só se justificam para cards **independentes**
(`_comum/delegacao.md`).

## Mergear na entrega

Quando os portões do branch estão verdes e a verificação real foi feita:

```bash
gh pr create --base develop --title "..." --body "..."
gh pr merge <n> --merge --delete-branch
```

- **Merge commit (`--merge`), nunca squash**: o histórico da `develop` é de merge
  commits, e é ele que o `git log` da auditoria de produção lê.
- `--delete-branch` é seguro porque nenhum PR usa outro branch como base.
- **Num worktree**, o `gh` tenta trocar o branch local para a `develop` depois do
  merge e pode reclamar que ela está em uso na pasta principal. O merge remoto já
  aconteceu: confirme com `gh pr view <n> --json state,mergeCommit` e, se o branch
  remoto ainda existir, apague com `git push origin --delete <branch>`.
- Guarde o **sha do commit de merge** (`mergeCommit.oid`): ele vai no comentário
  de entrega do Jira.

### Antes de mergear: a develop andou?

Vários cards entram na `develop` em sequência (às vezes de worktrees diferentes),
e o código de cada um só foi testado **sem** os dos outros. A cada merge, a soma
tem que ser testada de novo. Procedimento, nesta ordem:

1. `git fetch origin`. Traga a `develop` para o seu branch:
   `git merge origin/develop` (merge, não rebase: o branch já foi empurrado e assim não
   é preciso `--force`).
2. **Conflito se resolve mantendo os DOIS lados.** Os dois lados são trabalho de
   cards diferentes; escolher um é apagar um chamado. Se forem de verdade
   incompatíveis, pare e pergunte. Os conflitos recorrentes caem nos mesmos arquivos
   (`CHANGELOG.md`, `cli.py`, `mcp_server.py`, `pipeline/projects.py`,
   `pipeline/segments.py` por causa do `MEZZ_VERSION`); `git config rerere.enabled true`
   reaproveita a resolução.
3. **Veio código novo? Portões de novo**, os três, no resultado da mistura
   (`_comum/qualidade.md`). Não veio nada, vale o portão que você já rodou.
4. **O merge é serializado: um por vez.** Pegue a trava, confira que a `develop`
   não andou de novo, mergeie e solte a trava, tudo em poucos segundos:
   ```bash
   # Bash. No PowerShell: New-Item -ItemType Directory e Remove-Item sem -Recurse.
   lock="$(git rev-parse --git-common-dir)/dmaker-merge.lock"
   mkdir "$lock"        # falhou: outro está mergeando; espere alguns segundos e repita
   git fetch origin
   git merge-base --is-ancestor origin/develop HEAD   # falhou: a develop andou; solte a trava e volte ao passo 1
   gh pr merge <n> --merge --delete-branch
   rmdir "$lock"
   ```
   A trava é uma pasta dentro do `.git` compartilhado, por isso vale entre
   worktrees e a pasta principal. Solte-a **sempre**, mesmo se o merge falhar. Se
   uma trava ficar parada por mais de 15 minutos, não a apague: avise o planejador,
   porque pode haver um merge em andamento.

   A trava só cobre o instante do merge, não os portões: assim ninguém espera 5
   minutos de `pytest` do outro, e a condição "a `develop` já está dentro do meu
   branch" garante que o que você mergeia é exatamente o que você testou.

### Depois de mergear: a ponta da develop

Só se mergeia uma árvore que já contém toda a `develop` e já passou nos portões,
então a ponta resultante é a árvore testada. Confirme isso, em vez de supor:

```bash
git fetch origin
git diff --quiet <o-HEAD-que-você-testou> origin/develop && echo "ponta igual ao testado"
```

- **Igual:** os portões que você rodou valem como os da ponta; não repita.
- **Diferente** (outro card entrou entre o seu último portão e o merge, furando a
  fila): rode os três portões na ponta da `develop` agora
  (`git checkout --detach origin/develop` num worktree; `git checkout develop && git pull`
  na pasta principal).
- **A ponta quebrou? O card não está entregue.** Não mova o card para
  `Teste Manual` nem siga para o próximo: conserte antes, por um branch
  `fix/dmk-XXX-...` e PR com merge imediato, pelo mesmo caminho. Uma `develop`
  quebrada trava o Douglas inteiro, que testa nela.

Na pasta principal, depois do merge, volte para a `develop` e puxe
(`git checkout develop && git pull`), para o Douglas encontrar a pasta no estado
em que ele testa.

Ao final de uma leva, reporte o que **não** entrou e por quê.

## Worktrees: executores em paralelo

O Douglas autorizou executores em paralelo **quando os cards são independentes e
tocam coisas diferentes**. O que isola um do outro é o worktree: cada git worktree
tem o seu HEAD, o seu index e a sua pasta, então o branch de um não troca debaixo
do outro. Um executor fica na pasta principal `D:\DMaker`; cada outro roda com
`isolation: "worktree"` (ou `git worktree add`) e segue este preparo.

**1. Venv: use o da pasta principal.** O worktree não tem `.venv`, e o pacote
editável do venv aponta para `D:\DMaker\src`. Para rodar o código **do worktree**:

```powershell
$wt = (Get-Location).Path
$env:PYTHONPATH = "$wt\src"
& D:\DMaker\.venv\Scripts\python.exe -m dmaker.cli --help
& D:\DMaker\.venv\Scripts\python.exe -m pytest -q
& D:\DMaker\.venv\Scripts\ruff.exe check src tests
```

Use `python -m dmaker.cli` em vez de `dmaker.exe`, e confira com
`python -c "import dmaker; print(dmaker.__file__)"` que o caminho é o do worktree.

**2. `tests/test_mcp.py` sobe o servidor MCP como subprocesso por stdio** e o
subprocesso **precisa receber o `PYTHONPATH`** do worktree. Sem isso ele importa o
código da pasta principal e o teste passa ou falha pelo código errado. Se o teste
monta o ambiente do filho a partir de `os.environ`, basta exportar a variável
antes; senão, passe `PYTHONPATH` no `env` do subprocesso do teste.

**3. Junções para dados que não são versionados** (cada pasta é ignorada pelo git,
então não existe no worktree). Crie com `mklink /J` pelo `cmd`:

```powershell
cmd /c mklink /J "$wt\bin" "D:\DMaker\bin"                    # ffmpeg
cmd /c mklink /J "$wt\cache\models" "D:\DMaker\cache\models"  # modelos baixados
# só se o card precisar de dados reais (cache de mezanino, projetos, saídas):
cmd /c mklink /J "$wt\projects" "D:\DMaker\projects"
cmd /c mklink /J "$wt\output" "D:\DMaker\output"
```

Crie `$wt\cache` antes, se não existir. Pelas junções, **só acrescente**: nunca
apague, renomeie nem regenere o que já está lá, porque é o acervo do Douglas e a
pasta principal enxerga o mesmo conteúdo. Prefira mídia sintética no scratchpad
(`_comum/qualidade.md`).

**4. Remoção das junções: `rmdir`, nunca `Remove-Item -Recurse`.** O
`Remove-Item -Recurse` atravessa a junção e apaga o conteúdo da pasta de destino.
Antes de remover o worktree (`git worktree remove`), tire cada junção:

```powershell
cmd /c rmdir "$wt\bin"
cmd /c rmdir "$wt\cache\models"
cmd /c rmdir "$wt\projects"
cmd /c rmdir "$wt\output"
```

`rmdir` sem `/s` remove só o ponto da junção. Confira antes (`dir` mostra
`<JUNCTION>`).

**5. Porta própria para a interface.** Uma porta por executor: 8771, 8772, 8773...
A **8769 é do executor da pasta principal** e a **8765 é do Douglas**; nunca as
use num worktree. Suba em segundo plano com o `PYTHONPATH` do worktree
(`python -m dmaker.cli ui --port 8771 --no-browser`), guarde o PID e navegue com o
navegador embutido em `http://localhost:8771`. Ao terminar, encerre **só o seu**
processo, pelo PID guardado.

**6. Cuidados com o que é compartilhado:** `cache/` de mezanino e `projects/` pelas
junções são o mesmo disco, e dois renders ao mesmo tempo disputam ffmpeg e CPU.
Renders pesados dos dois executores ao mesmo tempo atrasam ambos; combine com o
planejador se houver mais de dois.

## Higiene

- Antes de commitar, `git status --short`. Adicione caminhos explícitos no
  `git add`, nunca `-A`. Arquivos de verificação (ver `_comum/qualidade.md`) e
  saídas de teste não podem vazar para o commit.
- **Não vão para o git, nunca:** `projects/`, `output/`, `cache/`, `bin/` e
  `assets/voices/`. Projetos têm vídeos de clientes e de casamentos; vozes
  clonadas são dado pessoal. Todos já estão no `.gitignore`, mas confira o
  `git status` antes de cada commit: um `git add -f` ou um arquivo de outra pasta
  com extensão de mídia escapa do filtro. Num worktree com junções, o `git status`
  é ainda mais importante.
- **Nada de nome de cliente, áudio ou vídeo real** em commit, PR ou Jira, além do
  estritamente necessário para descrever o teste (por exemplo, "projeto de teste
  com duas câmeras", não o nome do casal). Mídia que serviu de fixture de teste
  é sintética, gerada pelo próprio teste.
