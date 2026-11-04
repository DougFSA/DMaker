# Abaixar uma trilha enquanto outra fala (Auto Duck)

Tarefa `auto-duck` do manual do DMaker. Abaixa o volume de uma trilha (a música, o DJ) enquanto outra (a voz, o celebrante) soa, como o Auto Duck do Audacity, sem mexer no arquivo original.

## Quando usar

A música cobre a narração, ou a faixa do DJ cobre a fala do celebrante.

**Pedidos que levam a esta tarefa:**
- "Abaixa a música 15 dB quando a voz falar"
- "Abaixa a faixa do DJ enquanto o celebrante fala"

## O que perguntar antes

- Cada regra (`audio.ducks`) diz qual trilha abaixa (`background`) e qual a comanda (`key`), pelos ids da linha do tempo: `A1`, `A2...`, `MUS`, `NAR`, `VO`, `SFX`. Os padrões são os do Audacity: `amount_db` -12, `threshold_db` -30, `max_pause` 1 s, rampas de 0,5 s.
- **Limite:** uma faixa externa (A2, A3...) só abaixa sob **outra faixa externa**, porque ela é misturada dentro do clipe, antes da música e das vozes existirem. E o `A1`, que já contém as faixas externas, **não abaixa sob elas**. Qualquer outra combinação vale (a música sob a voz, a narração sob a voz gravada, o DJ sob o celebrante). O programa recusa a combinação com a explicação.
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

Renderize e ouça, ou meça. Medido em duas faixas externas de teste: o fundo caiu 12,00 dB só enquanto a outra falava (3 a 5 s e 7 a 8 s), e ficou a 0,00 dB fora das regiões e das rampas; a faixa que comanda não mudou. Um projeto antigo com `music.ducking` gera o mesmo grafo de antes.

## Erros comuns

- **"a faixa externa A2 só abaixa sob outra faixa externa"**: a combinação não vale; escolha outra faixa externa como chave, ou abaixe a música (`MUS`).
- **A música não abaixa**: veja com `dmaker audio duck list` se a regra existe e se as duas trilhas existem no projeto (a regra de uma trilha ausente não faz nada e avisa).
- **O fundo sobe entre duas frases**: suba `max_pause`.
