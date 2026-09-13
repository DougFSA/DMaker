---
name: dmaker-dev
description: Desenvolvimento no DMaker com economia de tokens: o Opus (sessão principal) planeja e revisa, agentes Sonnet implementam. Use quando o usuário invocar /dmaker-dev e descrever features, bugs ou melhorias do DMaker.
---

# dmaker-dev: planejar com Opus, implementar com Sonnet

Objetivo: entregar features/bugs do DMaker (`D:\DMaker`) gastando poucos tokens na sessão principal. O Opus entende o pedido, planeja com precisão e revisa; agentes **Sonnet** escrevem o código e os testes. Os padrões de `D:\DMaker\CLAUDE.md` valem para todos (SOLID, injeção de dependência, testes junto de cada mudança, código limpo em português/inglês, ruff + pytest verdes).

## Regras de economia

- A sessão principal **não lê arquivos grandes inteiros** para planejar: usa `Grep`/`Glob` e lê só os trechos necessários. A exploração ampla é do agente.
- Um plano cabe em uma tela: arquivos a tocar, funções/classes novas com assinatura, testes a criar, critério de aceite. Sem prosa.
- Um agente por tarefa independente; tarefas independentes rodam em paralelo (`run_in_background: true`). Tarefas que dependem uma da outra, em sequência.
- O agente recebe **tudo que precisa no prompt** (ele começa do zero): contexto, plano, padrões, comandos de verificação. Nunca "veja a conversa".
- A revisão do Opus é sobre o **diff** (`git diff --stat` + trechos críticos) e o resultado dos testes, não sobre o código inteiro.

## Fluxo

1. **Entender** (Opus): reformular o pedido em 1 a 3 frases; listar dúvidas que mudam a solução e perguntar só essas (AskUserQuestion). Se não houver, seguir.
2. **Planejar** (Opus): localizar os pontos de mudança com Grep/Glob; escrever o plano no formato abaixo. Para bug: primeiro o teste que reproduz.
3. **Implementar** (Sonnet): `Agent` com `model: "sonnet"`, `subagent_type: "general-purpose"`, prompt = template abaixo preenchido. Para várias tarefas independentes, vários agentes em paralelo.
4. **Verificar** (Opus): rodar `.venv\Scripts\ruff check src tests`, `.venv\Scripts\ruff format --check src tests` e `.venv\Scripts\python -m pytest -q` (o agente já rodou; a sessão confirma). Ler `git diff --stat` e os trechos críticos (novas interfaces, mudanças em `pipeline/`, `filtergraph/`, `spec.py`). Se algo estiver errado: mandar o ajuste ao **mesmo agente** por `SendMessage` (mantém o contexto), não abrir outro.
5. **Entregar** (Opus): resumo de 5 a 10 linhas: o que mudou, arquivos, testes novos, o que ficou de fora. Commit só se o usuário pedir (mensagem em português com o `Co-Authored-By` da sessão).

## Formato do plano

```
Tarefa: <uma frase>
Toca: <arquivo> (<o que muda>), ...
Novo: <arquivo> - <classe/função e assinatura>, ...
Testes: <arquivo de teste> - <casos>
Aceite: <como saber que está pronto; comando e resultado esperado>
Fora do escopo: <o que não fazer>
```

## Template do prompt para o agente Sonnet

```
Você vai implementar uma mudança no DMaker, editor de vídeos por comando em D:\DMaker (Python 3.13, venv em .venv).
Leia D:\DMaker\CLAUDE.md antes de tudo: a arquitetura em pacotes e os padrões (SOLID, injeção de dependência,
teste junto de cada mudança, código limpo, mensagens em português, identificadores em inglês) são obrigatórios.

Contexto: <2 a 5 linhas do que existe hoje e onde>

Plano:
<plano no formato acima>

Regras:
- Coloque código novo no pacote certo (domain/, media/, text/, visuals/, filtergraph/, pipeline/); cli.py e
  mcp_server.py são adaptadores finos sobre pipeline/projects.py.
- Funções puras onde der; nada executa ffmpeg fora de um FFmpegRunner.
- Escreva os testes junto (unitários com fakes; ffmpeg real só em tests/test_render_integration.py).
- Sem travessão (—) em textos que vão para a tela ou para o usuário.
- Ao escrever arquivos com barras invertidas, use as ferramentas Write/Edit (heredoc do Bash colapsa `\\`).
- Ao terminar, rode e faça passar: .venv\Scripts\ruff check --fix src tests; .venv\Scripts\ruff format src tests;
  .venv\Scripts\python -m pytest -q. Não deixe teste falhando nem lint sujo.
- Não faça commit.

Relate no final: arquivos criados/alterados, testes adicionados, resultado do pytest (contagem), dúvidas ou
decisões que tomou sozinho.
```

## Onde as coisas estão (atalho para planejar sem ler tudo)

| Assunto | Arquivo |
|---|---|
| modelo da spec (Pydantic) | `src/dmaker/domain/spec.py` |
| presets e zonas seguras | `src/dmaker/domain/presets.py` |
| tema/marca | `src/dmaker/domain/brand.py`, `assets/brands/<nome>/brand.json` |
| runner ffmpeg, protocolo, progresso | `src/dmaker/media/ffmpeg.py` |
| grafos ffmpeg (puros) | `src/dmaker/filtergraph/*.py` |
| texto/legendas em ASS | `src/dmaker/text/overlays.py`, `text/ass.py` |
| legendas (cues, SRT, Whisper) | `src/dmaker/text/captions.py`, `text/transcribe.py` |
| cartões, fundos, movimento | `src/dmaker/visuals/cards.py`, `motion.py`, `reframe_image.py` |
| etapas do render | `src/dmaker/pipeline/{sources,segments,captions,textlayer,assembly,renderer}.py` |
| serviços (CLI/MCP/UI) | `src/dmaker/pipeline/projects.py`, `jobs.py`, `qa.py` |
| CLI / MCP / UI | `src/dmaker/cli.py`, `mcp_server.py`, `ui/` |
| testes | `tests/` (unit: `test_pipeline_unit.py` com fakes; integração: `test_render_integration.py`; MCP: `test_mcp.py`) |
