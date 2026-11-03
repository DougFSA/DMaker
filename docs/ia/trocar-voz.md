# Trocar a voz de uma gravação inteira

Tarefa `trocar-voz` do manual do DMaker. Troca o timbre de quem fala por uma voz da biblioteca, mantendo as palavras, o ritmo, as pausas, a entonação e o fundo.

## Quando usar

Você quer outra voz na mesma fala, sem refazer o texto. Não traduz (isso é a dublagem) nem refaz um trecho (isso é a correção). Cada quadro da fala original vira um quadro da fala nova, então a duração não muda.

**Pedidos que levam a esta tarefa:**
- "Troca a voz dessa gravação pela voz `narradora`"
- "Faz a minha fala soar com outra voz"

## O que perguntar antes

- O arquivo e o id da voz (`dmaker voice list`). Para testar, converta só 20 a 30 s (`start` e `end`) antes do arquivo todo.
- Se a voz de destino é de uma pessoa real, a **autorização** dela.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `list_voices`: escolher a voz de destino
   Argumentos de exemplo: `{}`
2. `convert_voice`: testar nos primeiros 30 segundos
   Argumentos de exemplo: `{"path": "C:/videos/gravacao.mp4", "voice": "narradora", "start": 0, "end": 30}`
3. `convert_voice`: converter o arquivo inteiro
   Argumentos de exemplo: `{"path": "C:/videos/gravacao.mp4", "voice": "narradora"}`

## Equivalente na CLI

```powershell
dmaker voice convert gravacao.mp4 --voice narradora --start 0 --end 30
dmaker voice convert gravacao.mp4 --voice narradora
```

A saída padrão é `output/troca-de-voz/<nome>.<voz>-<id>.<ext>`. Vídeo inteiro passa sem recodificar a imagem; trecho de vídeo é recortado e recodificado.

## Como conferir

Ouça a prévia de 30 s e compare com o original. O motor muda o timbre, não o sotaque nem a melodia: a fala nova mantém o jeito de falar da original. A voz é separada do fundo (em cache) e o fundo volta como estava. Conte de 1,5 a 2 s por segundo de fala, mais a separação.

## Erros comuns

- **Resultado ruim**: gravação com muita reverberação ou ruído; confira a fala isolada antes (tarefa "Separar a voz da música e do ruído").
- **Voz "não encontrada"**: confira o id em `dmaker voice list`.
- **Baixando modelo**: o conversor baixa os pesos (131 MB) na primeira troca.
