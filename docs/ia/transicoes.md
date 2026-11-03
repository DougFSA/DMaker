# Escolher a transição entre os trechos

Tarefa `transicoes` do manual do DMaker. Muda como um trecho entra a partir do anterior (corte seco, fade, deslize, zoom de passagem, chicote) e o ritmo dessa troca (linear, suave ou mola).

## Quando usar

O corte seco ficou duro, ou você quer um efeito de passagem entre dois trechos. Você pode ver todas as transições antes de escolher.

**Pedidos que levam a esta tarefa:**
- "Põe uma transição de zoom entre o segundo e o terceiro trecho"
- "Quais transições existem? Mostra"
- "Quero a troca com efeito de mola"

## O que perguntar antes

- Qual trecho recebe a transição (o número na linha do tempo; o primeiro é 0). A transição é a **entrada** do trecho, vinda do anterior.
- Qual transição e quanto dura (0,3 a 0,6 s costuma bastar).

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `timeline_view`: achar o índice do trecho
   Argumentos de exemplo: `{"name": "meu-reel"}`
2. `edit_project`: trocar a entrada do trecho 2
   Argumentos de exemplo: `{"name": "meu-reel", "op": {"type": "set_field", "path": "timeline.2.transition", "value": {"type": "whippan", "duration": 0.5, "curve": "spring"}}}`
3. `render_project`: ver a transição na prévia
   Argumentos de exemplo: `{"name_or_path": "meu-reel", "preview": true}`

## Equivalente na CLI

```powershell
dmaker transitions list --kind movimento
dmaker transitions sheet whippan --curve spring
```

A folha de contato vai para `output\transitions`. Para aplicar, ponha em `timeline[N]` da spec `"transition": {"type": "whippan", "duration": 0.5, "curve": "spring"}`.

## Como conferir

A transição só aparece no render (a prévia ao vivo do player não a mostra). Gere a prévia e olhe o instante da troca. Transição consome tempo: a duração final é a soma dos trechos menos as transições, e `dmaker validate` mostra.

## Erros comuns

- **Nome desconhecido**: confira com `dmaker transitions list`.
- **A troca não passa de metade do trecho**: a duração é limitada à metade de cada trecho; trechos muito curtos pedem transição mais curta.
- **A mola não "passa do ponto" num wipe ou slide**: numa cortina a curva só acelera e assenta; nas de movimento a mola passa de verdade.
