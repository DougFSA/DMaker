/* Cliente dos modelos de IA: ver o que está baixado, baixar, apagar e limpar sobras (models_routes.py).
   Apagar exige `confirm: true`: a tela mostra o aviso de `removal` e só então manda a confirmação. */
import { http } from './http'
import type { JobStartResponse } from './types'
import type { ModelInventory, ModelRemovalPlan, ModelRemoved } from './types/models'

const enc = encodeURIComponent

export const modelsApi = {
  inventory: () => http.get<ModelInventory>('/api/models'),
  /** O que apagar este modelo levaria embora e quais funções param de funcionar. */
  removal: (modelId: string) => http.get<ModelRemovalPlan>(`/api/models/${enc(modelId)}/removal`),
  /** Baixa ou continua o download (job com progresso); clicar duas vezes acompanha o que já existe. */
  download: (modelId: string) => http.post<JobStartResponse>(`/api/models/${enc(modelId)}/download`),
  remove: (modelId: string, confirm: boolean) =>
    http.post<ModelRemoved>(`/api/models/${enc(modelId)}/remove`, { confirm }),
  /** Apaga as sobras de cache/models; `paths` limita às que a pessoa viu na lista. */
  prune: (confirm: boolean, paths?: string[]) => http.post<ModelRemoved>('/api/models/prune', { confirm, paths }),
}
