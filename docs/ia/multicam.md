# Fazer o vídeo do casamento com duas câmeras

Tarefa `multicam` do manual do DMaker. Monta o vídeo de uma cerimônia com duas câmeras sincronizadas pelo áudio, cortando entre elas pelas fases do rito reconhecidas na fala, com cartões de abertura e encerramento.

## Quando usar

Você tem duas pastas de câmera (a do altar e a lateral) de um casamento, e quer um primeiro corte automático para revisar. Para sincronizar câmeras e gravadores de outro evento, veja o passo a passo mais abaixo.

**Pedidos que levam a esta tarefa:**
- "Monta o vídeo do casamento com as duas câmeras dessas pastas"
- "Sincroniza as câmeras pelo áudio e faz o corte da cerimônia"

## O que perguntar antes

- As duas pastas (câmera do altar e câmera lateral), os nomes dos casais (um item por casal, no formato "Nome & Nome") e a data. O resto (celebrante, cidade, igreja, músicos, trilha) tem padrão.
- Se a cerimônia não começa no início da gravação: o segundo em que começa e termina (`inicio`, `fim`).
- Pergunte; nunca invente o caminho de uma pasta nem os nomes.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `new_from_template`: criar o projeto com as duas câmeras
   Argumentos de exemplo: `{"template": "casamento-pascom", "name": "casamento-ana-carlos", "params": {"camera_altar": "D:/casamento/altar", "camera_lateral": "D:/casamento/lateral", "nomes": ["Ana & Carlos"], "data": "15.08.2026"}}`
2. `plan_multicam`: reconhecer as fases e montar os clipes
   Argumentos de exemplo: `{"name_or_path": "casamento-ana-carlos"}`
3. `validate_project`: conferir duração e avisos
   Argumentos de exemplo: `{"name_or_path": "casamento-ana-carlos"}`
4. `render_project`: gerar a prévia do corte
   Argumentos de exemplo: `{"name_or_path": "casamento-ana-carlos", "preview": true}`
5. `qa_report`: conferir antes do render final
   Argumentos de exemplo: `{"name_or_path": "casamento-ana-carlos", "output": false}`

## Equivalente na CLI

```powershell
dmaker new-from-template casamento-pascom casamento-ana-carlos --param camera_altar=D:\casamento\altar --param camera_lateral=D:\casamento\lateral --param nomes="Ana & Carlos" --param data=15.08.2026
dmaker plan casamento-ana-carlos
dmaker validate projects\casamento-ana-carlos\spec.json
dmaker render projects\casamento-ana-carlos\spec.json --preview
```

**Para outro evento**: declare as fontes em `sources` com `sync: "auto"` e confira com `dmaker sync cam1.mp4 cam2.mp4 gravador.wav` (mostra o deslocamento e a confiança de cada fonte; abaixo de 4, confira à mão). Clipes com `source` usam o tempo da sessão: trocar de câmera é trocar o nome. Câmera que grava em vários arquivos usa `parts`. Para revisar um trecho: `dmaker render spec.json --preview --segments 12-20`. Um vídeo de 1 hora leva perto de 2 horas do começo ao fim.

## Como conferir

O `plan` devolve os avisos (buracos de cobertura, partes posicionadas pelo relógio do arquivo em vez de um link de áudio confiável) e as fases reconhecidas com o instante de cada uma. Confira esses avisos e a prévia antes do render final. O render recusa um projeto com o bloco `multicam` ainda sem planejar.

## Erros comuns

- **"bloco multicam pendente"**: rode `dmaker plan <projeto>` antes de validar ou renderizar.
- **Poucas fases reconhecidas**: a câmera de áudio (a do altar) tem fala baixa; informe `inicio` e `fim` ou ajuste os cortes depois.
- **Uma parte foi posicionada pelo relógio**: confira o trecho com `dmaker sync` ou olhando os quadros.
