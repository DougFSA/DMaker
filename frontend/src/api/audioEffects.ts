/* Cliente do catálogo dos efeitos de áudio (GET /api/audio-effects, ui/audio_effect_routes.py): os efeitos com os
   parâmetros, as faixas e as unidades, os campos comuns e os lugares onde a cadeia pode ficar. */
import { http, withQuery } from './http'
import type { AudioEffectCatalog, AudioEffectPreset, AudioEffectSettings, EffectResponse } from './types/audioEffects'

/** O catálogo inteiro; com `type`, só o desse efeito (o servidor responde 404 se o nome não existe). */
export function fetchAudioEffects(type?: string): Promise<AudioEffectCatalog> {
  return http.get<AudioEffectCatalog>(withQuery('/api/audio-effects', { type }))
}

/** A resposta de frequência de um efeito de equalização, calculada no servidor sem rodar o ffmpeg (a mesma conta do render). */
export function fetchEffectResponse(effect: AudioEffectSettings, points?: number): Promise<EffectResponse> {
  return http.post<EffectResponse>('/api/audio-effects/response', { effect, ...(points ? { points } : {}) })
}

/** As predefinições que a pessoa salvou (as embutidas vêm no catálogo). */
export async function fetchUserPresets(): Promise<AudioEffectPreset[]> {
  return (await http.get<{ presets: AudioEffectPreset[] }>('/api/audio-effects/presets')).presets
}

/** Salva (ou troca, se o nome já existe) uma predefinição: a cadeia de efeitos com um nome. */
export function saveUserPreset(label: string, effects: AudioEffectSettings[], summary = ''): Promise<AudioEffectPreset> {
  return http.post<AudioEffectPreset>('/api/audio-effects/presets', { label, effects, summary })
}

/** Apaga uma predefinição salva pelo id. */
export function deleteUserPreset(id: string): Promise<AudioEffectPreset> {
  return http.delete<AudioEffectPreset>(`/api/audio-effects/presets/${encodeURIComponent(id)}`)
}
