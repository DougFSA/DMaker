# Usar plugins de efeito de terceiros (LV2 e LADSPA)

Tarefa `plugins-de-efeito` do manual do DMaker. Usa no som de um item um plugin de efeito que não é do DMaker (um reverb de estúdio, um de-esser), como o menu de efeitos do Audacity faz com LV2 e LADSPA, sem mexer no arquivo original.

## Quando usar

Você tem um plugin de efeito que o DMaker não traz e quer ouvi-lo na narração, na música ou no som de um clipe.

**Pedidos que levam a esta tarefa:**
- "Quais plugins de áudio eu tenho instalados?"
- "Aplica o plugin de de-esser na narração"
- "Desliga o plugin de reverb que está dando erro"

## O que perguntar antes

- Formatos: **LV2** e **LADSPA**, hospedados pelo ffmpeg. O LADSPA roda no ffmpeg principal (o completo, que o `dmaker setup` instala, trocando o essentials sem `--force`). O LV2 roda num segundo ffmpeg: `dmaker setup --plugins` o instala em `bin/ffmpeg-lv2`. Rode o `setup` com a interface fechada; o `dmaker doctor` mostra o que está disponível.
- A varredura lê as pastas padrão do sistema (só leitura: `LV2_PATH`, `LADSPA_PATH`, `%APPDATA%\LV2`...) e a pasta `plugins/` do DMaker (`plugins/lv2/<pacote>.lv2`, `plugins/ladspa/<arquivo>.dll`). Depois de instalar um plugin, rode `dmaker audio plugins scan`.
- O efeito: `{"type": "plugin", "format": "lv2", "plugin": "<URI>", "params": {"<controle>": 0.5}}`. No LADSPA, `plugin` é `arquivo#rótulo` e os controles são `c0`, `c1`... Controles, faixas e padrões vêm do próprio plugin.
- Plugin mono em item estéreo roda uma vez por canal. `start`, `end` e `enabled` valem; a cauda do plugin é cortada no fim do item; não vale em `audio.master`.
- Ausente, desabilitado ou que o ffmpeg não hospeda: o `validate` avisa com o nome, e o render pula só aquele efeito e segue.
- Na narração sintetizada, o plugin pode apagar a marca d'água inaudível, e ela não é reaplicada (decisão de 03/11).

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `audio_plugins`: ver os plugins, com os controles, as faixas e os padrões
   Argumentos de exemplo: `{"action": "list"}`
2. `edit_project`: pôr o plugin na voz gravada
   Argumentos de exemplo: `{"name": "abertura", "op": {"type": "audio_effect", "action": "add", "target": "audio.voiceover.0", "effect": {"type": "plugin", "format": "lv2", "plugin": "urn:exemplo:eco", "params": {"delay_ms": 300}}}}`
3. `validate_project`: conferir se o plugin está instalado
   Argumentos de exemplo: `{"name_or_path": "abertura"}`

## Equivalente na CLI

```powershell
dmaker setup --plugins
dmaker audio plugins scan
dmaker audio plugins show urn:exemplo:eco
dmaker audio plugins disable urn:exemplo:eco
```

## Como conferir

Rode `dmaker validate` e ouça a prévia. Medido com um plugin de teste (um eco) nos dois formatos: contra o ffmpeg rodando o mesmo filtro, a diferença máxima de amostra foi 0; atraso de 100, 300 e 600 ms pôs o primeiro eco a 0,2, 0,4 e 0,7 s; realimentação de 0,2, 0,5 e 0,8 deu razão 0,200, 0,500 e 0,800 entre os ecos.

## Erros comuns

- **"O plugin ... não está instalado"** ou **"desabilitado"**: ponha o plugin numa pasta e rode `dmaker audio plugins scan`, ou `dmaker audio plugins enable <id>`. O render segue sem o efeito.
- **"falta o ffmpeg que hospeda o LV2"**: `dmaker setup --plugins`.
- **"Options feature missing, cannot continue!"**: o ffmpeg só oferece o mapa de URIs ao plugin LV2. Os que exigem `options` e `worker` (feitos com DPF, como o Dragonfly Reverb 3.2.10) não instanciam e aparecem como não usáveis.
- **VST3**: o DMaker não hospeda; o ffmpeg não o carrega e hospedá-lo pediria uma dependência nova pesada (decisão de 03/11). Use a versão LV2 ou LADSPA do plugin, ou trate o arquivo onde há VST3 e traga o resultado como faixa.
- **Nyquist**: os efeitos embutidos do Audacity que importavam já são nativos aqui. Um script `.ny` de terceiros roda no Audacity ou num interpretador à parte, e o arquivo tratado entra pela importação.
