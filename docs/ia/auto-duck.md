# Abaixar uma trilha enquanto outra fala (Auto Duck)

Tarefa `auto-duck` do manual do DMaker. Abaixa o volume de uma trilha (a música, o DJ) enquanto outra (a voz, o celebrante) soa, como o Auto Duck do Audacity, sem mexer no arquivo original.

## Quando usar

A música cobre a narração, ou a faixa do DJ cobre a fala do celebrante, seja ela dita na câmera, na narração ou na voz gravada.

**Pedidos que levam a esta tarefa:**
- "Abaixa a música 15 dB quando a voz falar"
- "Abaixa a faixa do DJ enquanto o celebrante fala"
- "Abaixa a faixa do DJ quando eu falo na câmera ou entra a narração"

## O que perguntar antes

- Cada regra (`audio.ducks`) diz qual trilha abaixa (`background`) e qual a comanda (`key`), pelos ids da linha do tempo: `A1`, `A2...`, `MUS`, `NAR`, `VO`, `SFX`. Os padrões são os do Audacity: `amount_db` -12, `threshold_db` -30, `max_pause` 1 s, rampas de 0,5 s.
- **Limite:** o `A1`, que já contém as faixas externas, **não abaixa sob elas** (para a câmera aparecer por cima do DJ, abaixe a faixa do DJ sob o `A1`). Qualquer outra combinação vale (a música sob a voz, a narração sob a voz gravada, o DJ sob a câmera, a narração, a voz gravada, os efeitos ou a música). O programa recusa a combinação com a explicação.
- **A chave `A1` é só a câmera:** o som dos próprios trechos (com os efeitos e o volume do clipe), **sem as faixas externas e sem os PiPs**, para qualquer fundo. Clipe mudo ou com o `A1` desligado não conta.
- **Faixa externa de fundo:** a chave `MUS`, `NAR`, `VO` ou `SFX` é medida antes de os clipes serem montados, na própria trilha; a `SFX` vale com o volume da spec, **antes** de os efeitos serem nivelados contra a voz. O render, a prévia e o render só de áudio medem igual.
- O ducking antigo da música (`music.ducking`, ligado por padrão) continua igual enquanto não há regra para a música. Uma regra com `background: "MUS"` o **substitui**: os dois não rodam juntos, e a música passa a abaixar pela curva da regra.
- A chave é medida como se ouve (com os efeitos e o volume dela), em janelas de 20 ms, e a medida fica em cache.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `edit_project`: a faixa do DJ abaixa 12 dB enquanto a do celebrante fala
   Argumentos de exemplo: `{"name": "casamento", "op": {"type": "auto_duck_add", "background": "A2", "key": "A3", "amount_db": -12}}`
2. `edit_project`: só voltar o fundo depois de 2 s de pausa
   Argumentos de exemplo: `{"name": "casamento", "op": {"type": "auto_duck_set", "index": 0, "max_pause": 2}}`
3. `qa_report`: conferir a saída
   Argumentos de exemplo: `{"name_or_path": "casamento"}`

## Equivalente na CLI

```powershell
dmaker audio duck add projects/casamento/spec.json A2 A3 --param amount_db=-12
dmaker audio duck list projects/casamento/spec.json
dmaker audio duck set projects/casamento/spec.json 0 --param max_pause=2
dmaker audio duck remove projects/casamento/spec.json 0
```

Tudo entra no histórico (`dmaker undo`).

## Como conferir

Renderize e ouça, ou meça. Medido em duas faixas externas de teste: o fundo caiu 12,00 dB só enquanto a outra falava (3 a 5 s e 7 a 8 s), e ficou a 0,00 dB fora das regiões e das rampas; a faixa que comanda não mudou. O mesmo teste com a faixa externa sob a câmera, a voz gravada, a narração e a música: a queda foi de 12 dB (com 0,5 dB de tolerância) só enquanto a chave soava. Um projeto antigo com `music.ducking` gera o mesmo grafo de antes.

## Erros comuns

- **"A1 já contém as faixas externas, então não abaixa sob A2"**: a combinação não vale; abaixe a faixa externa sob o `A1` (ou sob outra trilha), e não o contrário.
- **A música não abaixa**: veja com `dmaker audio duck list` se a regra existe e se as duas trilhas existem no projeto (a regra de uma trilha ausente não faz nada e avisa).
- **O fundo sobe entre duas frases**: suba `max_pause`.
