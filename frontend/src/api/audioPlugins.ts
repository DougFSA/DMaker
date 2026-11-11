/* Cliente dos plugins de efeito de terceiros (ui/audio_plugin_routes.py): a lista com os controles de cada plugin, a varredura e
   o habilitar e desabilitar. */
import { http } from './http'
import type { PluginCatalog } from './types/audioPlugins'

/** Os plugins da última varredura (o servidor faz uma se nunca houve). */
export function fetchAudioPlugins(): Promise<PluginCatalog> {
  return http.get<PluginCatalog>('/api/audio-plugins')
}

/** Varre as pastas de novo (depois de instalar um plugin ou o ffmpeg dos plugins). */
export function scanAudioPlugins(): Promise<PluginCatalog> {
  return http.post<PluginCatalog>('/api/audio-plugins/scan', {})
}

/** Habilita ou desabilita um plugin pelo id; devolve o catálogo só com ele. */
export function setAudioPluginEnabled(id: string, enabled: boolean): Promise<PluginCatalog> {
  return http.post<PluginCatalog>(`/api/audio-plugins/${encodeURIComponent(id)}/${enabled ? 'enable' : 'disable'}`, {})
}
