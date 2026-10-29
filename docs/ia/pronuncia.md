# Ensinar o DMaker a pronunciar um nome

Tarefa `pronuncia` do manual do DMaker. Cadastra como a voz deve falar um termo (uma marca, um nome estrangeiro, uma sigla) sem mudar o que está escrito na legenda.

## Quando usar

O modelo leu "DMaker" como "DeMaker", ou um nome próprio saiu torto. O dicionário troca só a fala; legendas, SRT e o texto mostrado mantêm a grafia escrita.

**Pedidos que levam a esta tarefa:**
- "A voz fala 'DMaker' errado, ensina a pronúncia"
- "Faz ele falar MedlyCare como 'Medly Quér'"

## O que perguntar antes

- O termo como é escrito e como deve soar (escreva do jeito que o modelo fala certo, por exemplo "Di Mêiker").
- O idioma da fala: cada termo vale por idioma (a grafia feita para o português estraga a fala em inglês). O dicionário é global ou de uma marca (a da marca vale por cima).

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `pronunciation`: cadastrar a pronúncia
   Argumentos de exemplo: `{"action": "add", "term": "DMaker", "spoken": "Di Mêiker", "language": "pt"}`
2. `pronunciation`: conferir o dicionário
   Argumentos de exemplo: `{"action": "list"}`
3. `synthesize_speech`: ouvir o resultado
   Argumentos de exemplo: `{"text": "O DMaker narra o seu roteiro.", "out": "C:/audio/teste-pronuncia.wav", "draft": true}`

## Equivalente na CLI

```powershell
dmaker voice lexicon add DMaker "Di Mêiker" --language pt
dmaker voice lexicon list
dmaker voice lexicon remove DMaker --language pt
```

`--brand medlycare` cadastra só para aquela marca. Na dublagem, vale a pronúncia do idioma de destino.

## Como conferir

Narre uma frase com o termo e ouça. O casamento ignora maiúsculas, vale só para a palavra inteira e usa o termo mais longo primeiro. Mudar o dicionário ressintetiza só as falas afetadas, porque a pronúncia entra na chave do cache.

## Erros comuns

- **Continua errado**: tente outra grafia fonética; o que importa é como o modelo lê.
- **Ficou errado em inglês**: o termo está cadastrado só em `pt`; cadastre também em `en` (ou deixe sem entrada, e ele é lido como está).
