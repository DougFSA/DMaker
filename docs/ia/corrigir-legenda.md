# Corrigir uma palavra errada na legenda

Tarefa `corrigir-legenda` do manual do DMaker. Troca uma palavra que o Whisper ouviu errado nas legendas automáticas (um nome próprio, um termo técnico) sem transcrever tudo de novo.

## Quando usar

A legenda saiu com "Medicare" em vez de "MedlyCare", ou com um nome trocado. Isto corrige o **texto da legenda**; para corrigir o que a pessoa **disse** no áudio, veja "Corrigir uma palavra errada sem regravar".

**Pedidos que levam a esta tarefa:**
- "A legenda escreveu o nome errado, corrige"
- "Troca 'medly care' por 'MedlyCare' nas legendas"

## O que perguntar antes

- O nome do projeto e as duas grafias: a errada, como saiu, e a certa.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `read_captions`: ver as legendas suspeitas
   Argumentos de exemplo: `{"name_or_path": "meu-reel", "mode": "compact"}`
2. `fix_captions`: trocar a grafia em todas as falas
   Argumentos de exemplo: `{"name_or_path": "meu-reel", "replacements": {"medly care": "MedlyCare"}}`
3. `render_project`: gerar a prévia com o texto corrigido
   Argumentos de exemplo: `{"name_or_path": "meu-reel", "preview": true}`

## Equivalente na CLI

```powershell
dmaker captions gravacao.mp4 --lang pt --model small
```

Este comando só transcreve e grava `.srt` e `.json`. A troca de palavras em um projeto é feita pela IA (`fix_captions`) ou na interface; na CLI, edite `projects\meu-reel\captions.auto.json`/`.srt` ou acrescente o termo em `captions.replacements` na spec.

## Como conferir

Gere a prévia e procure a palavra: o próximo render usa o texto corrigido, sem transcrever de novo (a transcrição fica em cache enquanto as fontes não mudam).

## Erros comuns

- **A palavra voltou errada**: acrescente-a em `captions.vocabulary` (nomes) ou `captions.replacements` ("errado": "certo") na spec; a marca já traz o vocabulário dela.
- **Quero refazer a transcrição**: rode o render com `--force`.
