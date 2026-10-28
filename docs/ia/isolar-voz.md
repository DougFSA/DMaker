# Separar a voz da música e do ruído

Tarefa `isolar-voz` do manual do DMaker. Separa a fala da música e do ruído de fundo de um vídeo ou áudio, em dois arquivos: a voz limpa e o fundo.

## Quando usar

Você quer a voz sem a música, o fundo sem a voz (para dublar ou trocar a fala), ou limpar uma gravação antes de clonar uma voz. Usa o Demucs, local.

**Pedidos que levam a esta tarefa:**
- "Tira a música dessa gravação e deixa só a voz"
- "Separa a voz do fundo"

## O que perguntar antes

- O arquivo e, para poupar tempo, o trecho (`start` e `end` em segundos). Conte de 3 a 6 vezes a duração do trecho, mais cerca de 30 s para carregar o modelo na primeira vez; o resultado fica em cache.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `isolate_vocals`: separar a voz do fundo no trecho
   Argumentos de exemplo: `{"path": "C:/videos/entrevista.mp4", "start": 0, "end": 60, "format": "wav"}`
2. `job_status`: acompanhar o job (use o id devolvido)
   Argumentos de exemplo: `{"job_id": "exemplo-de-job"}`

## Equivalente na CLI

```powershell
dmaker audio isolate entrevista.mp4 --start 0 --end 60 --format wav
```

Grava `<nome>_voz` e `<nome>_fundo` em `output/isolamento` (`--out-dir` muda a pasta; `--format mp3` comprime).

## Como conferir

Ouça a voz sozinha e o fundo sozinho. Não é mágica: música muito alta, voz cantada ou várias pessoas falando ao mesmo tempo deixam resíduos de fundo na voz e pedaços de voz no fundo.

## Erros comuns

- **Muito lento**: use `--start` e `--end` estreitos; o cache evita separar de novo o mesmo trecho.
- **Sobrou música na voz**: normal em música alta ou cantada; tente um trecho mais limpo.
- **Falta o modelo**: ele baixa na primeira vez (`dmaker models download demucs-htdemucs` adianta).
