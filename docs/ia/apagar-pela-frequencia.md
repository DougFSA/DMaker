# Apagar um som pela frequência: espectrograma e edição espectral

Tarefa `apagar-pela-frequencia` do manual do DMaker. Mostra o espectrograma do áudio e apaga um som só naquela faixa de frequência e naquele instante (um apito, o toque de um celular, um plim), sem cortar a fala em volta.

## Quando usar

Um apito de microfonia, o toque de um celular ou um "plim" no meio de uma frase. Cortar o trecho levaria a fala junto; aqui só aquela faixa daquele trecho some.

**Pedidos que levam a esta tarefa:**
- "Tem um apito em 3 kHz perto dos 20 segundos, tira sem cortar a fala"
- "O celular tocou no meio da frase, apaga só o toque"
- "Quero ver o espectrograma da voz gravada"
- "Abaixa em 12 dB tudo acima de 6 kHz nesse trecho"

## O que perguntar antes

- **Interface nova, Editor.** No painel **Áudio** (duplo clique no item), troque a **Vista** para **Espectrograma** ou **Onda e espectro** (as duas no mesmo eixo de tempo). A imagem mostra o som como ele soa, vem do servidor por zoom e fica em cache; uma hora de áudio abre sem ler a hora.
- Os efeitos espectrais não valem em `audio.master`.
- O **Apagar espectral** pode apagar a marca d'água inaudível da voz sintetizada, e ela não é reaplicada (decisão de 03/11, igual aos outros efeitos que mexem na voz).

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `edit_project`: apagar o apito de 2,8 a 3,2 kHz entre 19,4 e 20,1 s do item
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "audio_effect", "action": "add", "target": "audio.voiceover.0", "effect": {"type": "spectral_delete", "start": 19.4, "end": 20.1, "low_hz": 2800, "high_hz": 3200}}}`
2. `edit_project`: o mesmo, pelo marcador espectral
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "audio_effect", "action": "add", "target": "audio.voiceover.0", "region": "marker:plim", "effect": {"type": "spectral_delete"}}}`
3. `edit_project`: abaixar 12 dB tudo acima de 6 kHz entre 5 e 9 s
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "audio_effect", "action": "add", "target": "audio.voiceover.0", "effect": {"type": "spectral_shelves", "start": 5, "end": 9, "low_hz": 6000, "gain_db": -12}}}`
4. `undo_edit`: desfazer
   Argumentos de exemplo: `{"name": "entrevista"}`

## Equivalente na CLI

Não há espectrograma na linha de comando; os efeitos são os mesmos.

```powershell
dmaker audio effect add projects/entrevista/spec.json audio.voiceover.0 spectral_delete --start 19.4 --end 20.1 --param low_hz=2800 --param high_hz=3200
dmaker audio effect add projects/entrevista/spec.json audio.voiceover.0 spectral_delete --region "marker:plim"
dmaker undo projects/entrevista/spec.json
```

## Como conferir

Com um tom de 3 kHz de 0,5 s numa fala sintética, o espectrograma o mostra na linha e na coluna certas em todas as escalas; o Apagar espectral derruba a energia em 3 kHz em mais de 30 dB, a fala em volta muda menos de 1 dB e a energia rente às bordas do retângulo fica igual à do original. A mesma operação pela spec dá o mesmo arquivo processado.

## Erros comuns

- **"informe `low_hz` e/ou `high_hz`"** ou **"as duas bordas"**: o efeito precisa da faixa (o EQ espectral, das duas); marque o retângulo ou passe os Hz.
- **"informe `start` e `end`"**: o Apagar espectral exige o trecho.
- **"é um instante, não uma região"**: o `region` pede um marcador de região.
- **A voz ficou metálica**: o retângulo é largo demais ou pega a própria voz; estreite a faixa.
