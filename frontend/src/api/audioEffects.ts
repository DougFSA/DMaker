/* Cliente do catálogo dos efeitos de áudio (GET /api/audio-effects, ui/audio_effect_routes.py): os efeitos com os
   parâmetros, as faixas e as unidades, os campos comuns e os lugares onde a cadeia pode ficar. */
import { http, withQuery } from './http'
import type { AudioEffectCatalog, AudioEffectPreset, AudioEffectSettings, EffectResponse, MacroScope } from './types/audioEffects'

/** O catálogo inteiro; com `type`, só o desse efeito (o servidor responde 404 se o nome não existe). Com `brand`, as
 * macros salvas dessa marca vêm junto com as globais. */
export function fetchAudioEffects(type?: string, brand?: string): Promise<AudioEffectCatalog> {
  return http.get<AudioEffectCatalog>(withQuery('/api/audio-effects', { type, brand }))
}

/** A resposta de frequência de um efeito de equalização, calculada no servidor sem rodar o ffmpeg (a mesma conta do render). */
export function fetchEffectResponse(effect: AudioEffectSettings, points?: number): Promise<EffectResponse> {
  return http.post<EffectResponse>('/api/audio-effects/response', { effect, ...(points ? { points } : {}) })
}

/** As macros que a pessoa salvou, as globais e, com `brand`, as da marca (as embutidas vêm no catálogo). */
export async function fetchUserPresets(brand?: string): Promise<AudioEffectPreset[]> {
  return (await http.get<{ presets: AudioEffectPreset[] }>(withQuery('/api/audio-effects/presets', { brand }))).presets
}

/** Salva (ou troca, se o nome já existe) uma macro: a cadeia de efeitos com um nome. Com `brand`, fica na pasta da marca. */
export function saveUserPreset(label: string, effects: AudioEffectSettings[], summary = '', brand?: string): Promise<AudioEffectPreset> {
  return http.post<AudioEffectPreset>('/api/audio-effects/presets', { label, effects, summary, ...(brand ? { brand } : {}) })
}

/** Apaga uma macro salva pelo id (da pasta da marca, com `brand`). */
export function deleteUserPreset(id: string, brand?: string): Promise<AudioEffectPreset> {
  return http.delete<AudioEffectPreset>(withQuery(`/api/audio-effects/presets/${encodeURIComponent(id)}`, { brand }))
}

/** "Salvar a cadeia como macro": a cadeia de efeitos do item `target` da spec na tela vira uma macro, global ou da marca do projeto. */
export function saveChainAsMacro(
  project: string,
  body: { spec: unknown; target: string; label: string; scope: MacroScope; summary?: string },
): Promise<AudioEffectPreset> {
  return http.post<AudioEffectPreset>(`/api/projects/${encodeURIComponent(project)}/audio-macros`, body)
}
