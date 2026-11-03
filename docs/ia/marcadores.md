# Marcar instantes e trechos com marcadores

Tarefa `marcadores` do manual do DMaker. Põe marcadores com nome na linha do tempo (um instante ou uma região, com cor e grupo), importa e exporta o `.txt` de marcadores do Audacity, gera marcadores regulares e corta no instante de um marcador.

## Quando usar

Você quer nomear um ponto ("aqui entra a música", "trecho bom"), trazer as marcações do Audacity, dividir um áudio em partes iguais ou cortar exatamente num ponto marcado. Os marcadores ficam no tempo do **vídeo final** e acompanham os cortes: cortar 3 s antes de um marcador o puxa 3 s para trás, e o que estava no trecho cortado some, com aviso. Não mudam a imagem nem o som.

**Pedidos que levam a esta tarefa:**
- "Marca o refrão aos 42 segundos"
- "Importa as marcações que eu fiz no Audacity"
- "Divide o episódio em partes de 15 segundos, numeradas"
- "Corta o vídeo no marcador do refrão"

## O que perguntar antes

- Para importar, o `.txt` exportado do Audacity (**Arquivo, Exportar, Exportar rótulos**); para exportar, o caminho do `.txt` que o Audacity vai abrir (**Arquivo, Importar, Rótulos**).
- Cada grupo é uma trilha de marcadores: o grupo vazio é a trilha **MK**, e o grupo `análise` vira **MK análise**.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `edit_project`: marcar um instante com texto e cor
   Argumentos de exemplo: `{"name": "meu-podcast", "op": {"type": "marker_add", "at": 42.0, "text": "refrão", "color": "#e0a020"}}`
2. `markers_regular`: uma região a cada 15 segundos, numeradas
   Argumentos de exemplo: `{"name": "meu-podcast", "interval": 15, "prefix": "Parte ", "group": "partes"}`
3. `markers_import`: trazer as marcações do Audacity
   Argumentos de exemplo: `{"name": "meu-podcast", "file": "C:/audios/rotulos.txt", "group": "audacity"}`
4. `edit_project`: cortar exatamente no marcador
   Argumentos de exemplo: `{"name": "meu-podcast", "op": {"type": "split", "at": "marker:refrão"}}`
5. `timeline_view`: conferir as trilhas MK e os tempos
   Argumentos de exemplo: `{"name": "meu-podcast"}`
6. `markers_export`: devolver as marcações ao Audacity
   Argumentos de exemplo: `{"name": "meu-podcast", "out": "C:/audios/marcadores.txt", "group": "audacity"}`

## Equivalente na CLI

```powershell
dmaker markers add projects\meu-podcast\spec.json --at 42 --text refrão --color "#e0a020"
dmaker markers regular projects\meu-podcast\spec.json --interval 15 --prefix "Parte " --digits 2
dmaker markers import projects\meu-podcast\spec.json C:\audios\rotulos.txt --group audacity
dmaker markers export projects\meu-podcast\spec.json --out C:\audios\marcadores.txt --group audacity
dmaker markers list projects\meu-podcast\spec.json
dmaker markers remove projects\meu-podcast\spec.json "marker:refrão"
```

Na spec: `"markers": [{"at": 42, "text": "refrão"}, {"start": 60, "end": 75, "text": "verso", "group": "meus"}]`. O arquivo do Audacity tem uma linha por marcador (início, fim e texto separados por tabulação, em segundos com seis casas; o instante repete o tempo): exportar e importar de volta devolve o mesmo arquivo, byte a byte. A quebra de linha é a do sistema, como no Audacity (`--newline lf` ou `crlf` fixa uma).

## Como conferir

`dmaker markers list` mostra o que ficou. Num áudio de 60 s, `--interval 15` cria 4 regiões. Depois de um corte, o aviso `edit_warnings` do `edit_project` diz quais marcadores saíram; `validate_project` avisa de marcador depois do fim do vídeo e de texto repetido no grupo.

## Erros comuns

- **"há 2 marcadores chamados ..."**: use `marker:grupo/texto` ou renomeie um.
- **"não existe o marcador ..."**: a busca ignora maiúscula, acento e espaço; `timeline_view` lista os marcadores.
- **Linha ignorada ao importar**: o aviso cita a linha do `.txt`; o resto entra.
- **O marcador sumiu depois de um corte**: estava no trecho removido; **Desfazer** (`Ctrl+Z`) o traz de volta.
