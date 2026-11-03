# Clonar uma voz

Tarefa `clonar-voz` do manual do DMaker. Cria uma voz da biblioteca a partir de uma gravação limpa de quem fala, para usar na narração, na troca de voz e na correção de fala.

## Quando usar

Você quer que o DMaker fale com a sua voz, ou com a de uma pessoa que **autorizou** isso. Nunca clone a voz de alguém sem a permissão dele: é dado pessoal.

**Pedidos que levam a esta tarefa:**
- "Clona a minha voz com essa gravação"
- "Cria uma voz a partir deste áudio"

## O que perguntar antes

- **Pergunte se o dono da voz autorizou a clonagem. Sem autorização, não clone.** A interface exige marcar "Tenho permissão do dono desta voz para cloná-la"; a CLI e as ferramentas não perguntam, então a pergunta é sua.
- Uma gravação de fala limpa, sem música nem ruído, de 3 a 15 s (até 20 s vale inteira; acima disso o DMaker escolhe a janela de 15 s com mais fala). O ideal é a pessoa lendo uma frase natural.
- O que é dito na gravação, se souber (sem isso o Whisper transcreve).

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `clone_voice`: cadastrar a voz (só com a autorização do dono)
   Argumentos de exemplo: `{"name": "minha-voz", "reference_audio": "C:/audio/referencia.wav", "language": "pt"}`
2. `list_voices`: confirmar que a voz entrou na biblioteca
   Argumentos de exemplo: `{}`
3. `synthesize_speech`: ouvir uma amostra
   Argumentos de exemplo: `{"text": "Teste da minha voz clonada.", "voice": "minha-voz", "out": "C:/audio/teste-voz.wav", "draft": true}`

## Equivalente na CLI

```powershell
dmaker voice clone minha-voz referencia.wav --text "Esta é a frase que eu li na gravação, com calma e perto do microfone."
dmaker voice preview minha-voz --text "Teste da minha voz clonada."
dmaker voice list
dmaker voice remove minha-voz
```

As vozes ficam em `assets/voices/<id>/` (dado pessoal; fora do git). `voice remove` apaga uma voz sua; as prontas não se removem.

## Como conferir

`dmaker voice preview` gera uma amostra curta para ouvir. A voz clonada mantém o timbre, mas não o sotaque nem a melodia de quem não está na gravação.

## Erros comuns

- **A voz saiu diferente**: a gravação tinha ruído, eco ou música; grave de novo, mais perto do microfone e sem fundo. Use "Separar a voz da música e do ruído" para limpar uma gravação existente.
- **Ficou lento**: uma referência mais curta (5 a 10 s) acelera cada fala.
- **O texto da gravação saiu errado**: passe `--text` com o que foi dito.
