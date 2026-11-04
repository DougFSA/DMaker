/* Cliente do catálogo dos geradores de som (GET /api/audio-generators, ui/audio_effect_routes.py): os geradores com os
   parâmetros, as faixas e as unidades. */
import { http, withQuery } from './http'
import type { AudioGeneratorCatalog } from './types/audioGenerators'

/** O catálogo inteiro; com `type`, só o desse gerador (o servidor responde 404 se o nome não existe). */
export function fetchAudioGenerators(type?: string): Promise<AudioGeneratorCatalog> {
  return http.get<AudioGeneratorCatalog>(withQuery('/api/audio-generators', { type }))
}
