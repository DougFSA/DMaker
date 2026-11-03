/* Cliente do catálogo dos efeitos de áudio (GET /api/audio-effects, ui/audio_effect_routes.py): os efeitos com os
   parâmetros, as faixas e as unidades, os campos comuns e os lugares onde a cadeia pode ficar. */
import { http, withQuery } from './http'
import type { AudioEffectCatalog } from './types/audioEffects'

/** O catálogo inteiro; com `type`, só o desse efeito (o servidor responde 404 se o nome não existe). */
export function fetchAudioEffects(type?: string): Promise<AudioEffectCatalog> {
  return http.get<AudioEffectCatalog>(withQuery('/api/audio-effects', { type }))
}
