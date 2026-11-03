# Criar uma voz descrevendo como ela soa

Tarefa `desenhar-voz` do manual do DMaker. Cria uma voz sem gravação nenhuma, só descrevendo gênero, idade, tom e sotaque.

## Quando usar

Você precisa de um narrador que não é ninguém em particular, ou não tem uma gravação limpa para clonar. A voz desenhada ganha uma frase âncora gerada uma vez, para o timbre não mudar entre as falas.

**Pedidos que levam a esta tarefa:**
- "Cria uma voz feminina, grave, de meia-idade"
- "Preciso de um narrador masculino com sotaque britânico"

## O que perguntar antes

- Gênero (`male` ou `female`), faixa etária (`child`, `teenager`, `young adult`, `middle-aged`, `elderly`), tom (`very low pitch`, `low pitch`, `moderate pitch`, `high pitch`, `very high pitch`) e sotaque (`american`, `british`, `australian`, `portuguese`... seguido de ` accent`). Apelidos em português (feminino, grave, idoso) também valem.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `design_voice`: cadastrar a voz descrita
   Argumentos de exemplo: `{"name": "narradora", "gender": "female", "age": "middle-aged", "pitch": "low pitch"}`
2. `synthesize_speech`: ouvir a voz
   Argumentos de exemplo: `{"text": "Bem-vindos ao nosso canal.", "voice": "narradora", "out": "C:/audio/teste-narradora.wav", "draft": true}`

## Equivalente na CLI

```powershell
dmaker voice design narradora --gender female --age middle-aged --pitch "low pitch"
dmaker voice preview narradora --text "Bem-vindos ao nosso canal."
```

`--accent "british accent"` põe sotaque, `--whisper` deixa a voz sussurrada, `--instruct "female, low pitch"` passa a descrição inteira de uma vez.

## Como conferir

Ouça a amostra de `dmaker voice preview`. A voz desenhada é do tipo `design` na lista (`dmaker voice list`).

## Erros comuns

- **Termo não aceito**: use os termos em inglês da lista acima ou os apelidos em português.
- **A voz mudou entre falas**: não deveria; a âncora é gerada uma vez. Apague e crie de novo se o problema persistir.
