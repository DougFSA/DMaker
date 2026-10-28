# Exportar o vídeo para outras plataformas

Tarefa `exportar` do manual do DMaker. Gera o mesmo projeto em vários formatos de uma vez (Reels, Shorts, Facebook, feed), cada um com o tamanho, a zona segura e o limite da plataforma.

## Quando usar

O vídeo está aprovado e precisa sair para mais de uma rede. Cada formato é um render completo, então demora o mesmo que um render por formato.

**Pedidos que levam a esta tarefa:**
- "Exporta esse reel também para Shorts e Facebook"
- "Gera o vídeo para o feed quadrado"

## O que perguntar antes

- O nome do projeto e a lista de formatos (`dmaker presets` mostra todos; os atalhos `reels`, `stories`, `shorts`, `youtube`, `feed`, `square`, `tiktok`, `status` e `linkedin` também valem).
- Se o vídeo respeita o limite de cada formato (Stories do Facebook, 20 s; WhatsApp, 30 s).

## Ferramentas MCP, na ordem (nomes de ferramenta para a IA, não comandos do terminal)

1. `presets`: ver os formatos e limites de uma plataforma
   Argumentos de exemplo: `{"platform": "youtube"}`
2. `export_project`: exportar para os dois formatos
   Argumentos de exemplo: `{"name_or_path": "meu-reel", "presets": ["youtube/shorts", "facebook/reels"]}`
3. `job_status`: acompanhar o job (use o id devolvido)
   Argumentos de exemplo: `{"job_id": "exemplo-de-job"}`

## Equivalente na CLI

```powershell
dmaker presets
dmaker export projects\meu-reel\spec.json youtube/shorts facebook/reels
```

`--preview` gera versões rápidas de conferência; `--no-ui` roda só no terminal.

## Como conferir

Cada arquivo sai em `output/` com o nome do formato. `dmaker validate` e o relatório de QA avisam quando a duração passa do limite da plataforma.

## Erros comuns

- **Passou do limite da plataforma**: é um aviso (as redes mudam os números); corte o vídeo ou escolha outro formato.
- **Formato desconhecido**: confira o id com `dmaker presets`.
- **Demora**: use `--preview` para conferir e deixe o final para o fim.
