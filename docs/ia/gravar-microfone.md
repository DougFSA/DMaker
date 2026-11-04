# Gravar do microfone: narração, punch-in, hora marcada, ativada por som e clonagem

Tarefa `gravar-microfone` do manual do DMaker. Grava a voz pelo microfone direto numa trilha de voz gravada, sobre o vídeo e com a latência compensada, regrava um trecho sem perder o antigo, grava numa hora marcada ou só quando há som, recupera a gravação de uma aba que fechou e grava os 15 s de referência para clonar uma voz.

## Quando usar

Uma narração de verdade (em vez da sintetizada) sobre o vídeo, regravar uma frase que saiu errada, gravar uma live ou um culto sem ficar na frente do computador, ou clonar a própria voz sem passar por arquivo.

**Pedidos que levam a esta tarefa:**
- "Quero gravar a narração do vídeo pelo microfone"
- "Regrava só essa frase, sem perder a que eu gravei"
- "Recupera a gravação que ficou aberta quando a aba fechou"

## O que perguntar antes

- **A gravação é feita pelo navegador** (interface nova, Chrome, Edge ou Firefox atuais, em localhost): ele precisa da permissão do microfone. A IA e a CLI não gravam; elas recuperam o que a interface deixou no disco (`audio_recordings`) e editam os takes (`edit_project`).
- Nada sai da máquina. O som vai em pedaços de um segundo para `projects/<nome>/recordings/<id>/`, numerados: reenviar um pedaço não duplica, e fechar a aba no meio não perde o que já chegou.
- **Gravação com hora marcada e ativada por som rodam na aba**: ela precisa ficar aberta, e o computador acordado, até o fim.
- Use fone ao gravar sobre o vídeo e ao escutar o microfone: com o alto-falante o som volta ao microfone. Para **calibrar a latência** é o contrário: tire o fone, o microfone precisa ouvir o clique do alto-falante.
- Para o punch-in, o projeto precisa de uma voz gravada (`audio.voiceover`); a voz sintetizada (`audio.narration`) não tem um arquivo para regravar.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `audio_recordings`: ver as gravações que a aba deixou abertas, com a duração que chegou
   Argumentos de exemplo: `{"name": "entrevista", "action": "list", "unfinished": true}`
2. `audio_recordings`: finalizar a gravação aberta com o que chegou e pô-la como voz gravada nova
   Argumentos de exemplo: `{"name": "entrevista", "action": "recover"}`
3. `edit_project`: regravar de 12 a 15 s com uma gravação que começou em 9 s
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "audio_punch", "target": "audio.voiceover.0", "start": 12.0, "end": 15.0, "src": "recordings/20261104-190000-ab12/gravacao.wav", "recorded_at": 9.0, "duration": 8.0}}`
4. `edit_project`: voltar ao take antigo do trecho regravado
   Argumentos de exemplo: `{"name": "entrevista", "op": {"type": "voiceover_take_set", "target": "audio.voiceover.1", "take": 0}}`
5. `undo_edit`: desfazer a troca
   Argumentos de exemplo: `{"name": "entrevista"}`

## Equivalente na CLI

```powershell
dmaker audio recordings list projects/entrevista/spec.json --unfinished
dmaker audio recordings recover projects/entrevista/spec.json
dmaker audio punch projects/entrevista/spec.json audio.voiceover.0 20261104-190000-ab12 --start 12 --end 15
dmaker audio take projects/entrevista/spec.json audio.voiceover.1 0
dmaker undo projects/entrevista/spec.json
```

## Como conferir

Medido: dez minutos de pedaços mandados por um cliente que some no meio ficam no disco e a recuperação devolve a duração certa; um clique gravado sobre um da prévia cai a menos de 10 ms depois da compensação; o punch-in de 3 s troca só o trecho, sem estalo nas emendas, e o take antigo continua na lista; a gravação ativada por som deixa de fora o silêncio entre as falas.

## Erros comuns

- **"Sem acesso ao microfone"**: libere a permissão do navegador para o endereço do DMaker.
- **"Não ouvi o clique"** na calibração: tire o fone, aproxime o microfone do alto-falante e aumente o volume do computador.
- **"Sem conexão com o servidor"**: a gravação continua e os pedaços são reenviados quando o servidor volta; se a aba fechar antes, use **Recuperar**.
- **"Selecione na onda o trecho da voz gravada"**: o punch-in pede um trecho selecionado numa voz gravada.
- **"não há som gravado no trecho"**: a gravação não cobre o trecho pedido; grave de novo com a pré-rolagem.
