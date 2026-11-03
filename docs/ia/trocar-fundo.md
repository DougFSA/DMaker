# Trocar o fundo atrás da pessoa

Tarefa `trocar-fundo` do manual do DMaker. Troca o fundo atrás de quem fala por uma cor lisa (branca ou da marca), sem tela verde, recortando a pessoa com uma rede neural.

## Quando usar

A pessoa gravou de frente, parada, com o fundo bagunçado, e você quer um fundo liso. Funciona melhor com fundo parado; movimentos rápidos podem falhar na borda.

**Pedidos que levam a esta tarefa:**
- "Tira o fundo desse vídeo e põe branco"
- "Troca o fundo atrás da pessoa pela cor da marca"

## O que perguntar antes

- Qual trecho (índice na linha do tempo) e a cor do fundo novo (hex ou chave da marca: `primary`, `accent`, `mint`, `white`).
- `resnet50` (padrão) separa melhor; `mobilenetv3` é mais leve e rápido, bom para rascunho.

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `edit_project`: ligar o recorte no primeiro trecho
   Argumentos de exemplo: `{"name": "meu-reel", "op": {"type": "set_field", "path": "timeline.0.matte", "value": {"background": "#FFFFFF", "model": "mobilenetv3"}}}`
2. `render_project`: gerar a prévia com o recorte
   Argumentos de exemplo: `{"name_or_path": "meu-reel", "preview": true}`
3. `qa_report`: conferir o resultado
   Argumentos de exemplo: `{"name_or_path": "meu-reel", "output": false}`

## Equivalente na CLI

```powershell
dmaker setup
dmaker render projects\meu-reel\spec.json --preview
```

O `dmaker setup` baixa o modelo de recorte (ResNet50, 100 MB; o MobileNetV3 tem 15 MB). Na spec, o clipe leva `"matte": {"background": "#FFFFFF", "model": "mobilenetv3"}`.

## Como conferir

Veja a borda do cabelo e das mãos na prévia. Gravação com movimento rápido pode "piscar" na borda; nesse caso use `resnet50` ou grave com a pessoa mais parada.

## Erros comuns

- **Modelo não encontrado**: rode `dmaker setup` (ou `dmaker models download rvm-resnet50`).
- **Render lento**: o recorte pesa na CPU; use `mobilenetv3` para rascunho e `downsample` menor.
- **A cadeira ou um objeto some**: use `resnet50`, que separa melhor o que encosta na pessoa.
