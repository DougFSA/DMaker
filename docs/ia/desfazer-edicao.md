# Desfazer e refazer uma edição

Tarefa `desfazer-edicao` do manual do DMaker. Volta a spec exatamente a como estava antes da última edição do `edit_project` (ou refaz a que foi desfeita), com um histórico de até 50 passos guardado na pasta do projeto.

## Quando usar

A edição saiu errada, ou você quer comparar o antes e o depois.

**Pedidos que levam a esta tarefa:**
- "Desfaz a última edição"
- "Volta como estava antes"
- "Refaz o que eu desfiz"
- "O que eu editei até agora?"

## O que perguntar antes

- Só o que foi gravado pelo MCP e pela CLI entra no histórico; a interface tem o desfazer dela, em memória.
- Uma edição nova depois de desfazer esvazia o que podia ser refeito.
- O `undo_cut` (devolver um corte do corte automático) segue valendo e também entra no histórico.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `edit_history`: ver os passos que dá para desfazer e refazer
   Argumentos de exemplo: `{"name": "entrevista"}`
2. `undo_edit`: desfazer a última edição
   Argumentos de exemplo: `{"name": "entrevista"}`
3. `redo_edit`: refazer o que foi desfeito
   Argumentos de exemplo: `{"name": "entrevista"}`

## Equivalente na CLI

```powershell
dmaker history projects/entrevista/spec.json
dmaker undo projects/entrevista/spec.json
dmaker redo projects/entrevista/spec.json
```

## Como conferir

Depois do `undo`, o `spec.json` é byte a byte o de antes da edição; o `redo` devolve a editada. `dmaker history` mostra o que sobrou em cada pilha.

## Erros comuns

- **"não há o que desfazer"**: o projeto não tem edição gravada pelo histórico (edições antigas ou feitas na interface não entram).
- **"o projeto tinha mudado fora do histórico"**: alguém mexeu na spec pela interface ou à mão; o desfazer trocou pelo estado guardado e o estado de agora ficou no `redo_edit`.

---
