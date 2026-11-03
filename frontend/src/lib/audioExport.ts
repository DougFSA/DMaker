/* A exportação de áudio: o que a janela mostra para cada formato e como o formulário vira o pedido da API.
   Funções puras, sem tela nem rede; o diálogo `AudioExportDialog` só as chama. */
import type { AudioExportMode, AudioExportRequest, AudioPresetInfo, LoudnessTargets } from '@/api'

export interface ExportModeInfo {
  value: AudioExportMode
  title: string
  hint: string
}

export const EXPORT_MODES: ExportModeInfo[] = [
  { value: 'mix', title: 'O projeto inteiro', hint: 'Um arquivo com todo o som do projeto.' },
  {
    value: 'regions',
    title: 'Uma região por arquivo',
    hint: 'Um arquivo para cada região de marcador, com o texto do marcador no nome.',
  },
  {
    value: 'stems',
    title: 'Uma trilha por arquivo',
    hint: 'Narração, voz gravada, música e efeitos separados. Somados, dão a mixagem.',
  },
  { value: 'selection', title: 'Só um trecho', hint: 'Um intervalo do projeto, em segundos ou de marcador a marcador.' },
]

export const STEM_TRACKS: Array<{ id: string; label: string }> = [
  { id: 'A1', label: 'Som dos trechos' },
  { id: 'NAR', label: 'Narração' },
  { id: 'VO', label: 'Voz gravada' },
  { id: 'MUS', label: 'Música' },
  { id: 'SFX', label: 'Efeitos' },
]

const BITRATE_MODE_LABELS: Record<string, string> = {
  cbr: 'Taxa constante (CBR)',
  vbr: 'Qualidade variável (VBR)',
  abr: 'Taxa média (ABR)',
}

export const CHANNEL_OPTIONS = [
  { value: '', label: 'Do formato' },
  { value: '1', label: 'Mono' },
  { value: '2', label: 'Estéreo' },
]

export function isAudioPresetId(id: string | null | undefined): boolean {
  return typeof id === 'string' && id.startsWith('audio/')
}

export function bitrateModeLabel(mode: string): string {
  return BITRATE_MODE_LABELS[mode] ?? mode
}

/** Os alvos de loudness como lista de escolha: "Podcast (-16 LUFS)". */
export function loudnessOptions(targets: LoudnessTargets): Array<{ value: string; label: string }> {
  const names: Record<string, string> = { redes: 'Redes', podcast: 'Podcast', broadcast: 'Broadcast (EBU R128)' }
  return Object.entries(targets).map(([name, lufs]) => ({
    value: name,
    label: `${names[name] ?? name} (${lufs} LUFS)`,
  }))
}

/** O nome do alvo de loudness que corresponde ao valor da spec (-16 vira "podcast"); vazio se for outro número. */
export function loudnessName(targets: LoudnessTargets, lufs: unknown): string {
  return Object.entries(targets).find(([, value]) => value === lufs)?.[0] ?? ''
}

/** O que a janela de um formato oferece: profundidade (sem perda) ou modo e taxa de bits (com perda). */
export interface FormatControls {
  bitDepths: number[]
  bitrateModes: Array<'cbr' | 'vbr' | 'abr'>
  /** O modo escolhido usa taxa de bits em kbps (CBR e ABR) ou qualidade (VBR). */
  usesBitrate: boolean
  usesQuality: boolean
  sampleRates: number[]
}

export function formatControls(preset: AudioPresetInfo | undefined, mode: string): FormatControls {
  if (!preset) return { bitDepths: [], bitrateModes: [], usesBitrate: false, usesQuality: false, sampleRates: [] }
  const effective = mode || preset.bitrate_mode || ''
  return {
    bitDepths: preset.bit_depths,
    bitrateModes: preset.bitrate_modes,
    usesBitrate: preset.bitrate_modes.length > 0 && effective !== 'vbr',
    usesQuality: preset.bitrate_modes.includes('vbr') && effective === 'vbr',
    sampleRates: preset.allowed_sample_rates,
  }
}

/** Um instante digitado: segundos (aceita vírgula decimal) ou `marker:<texto>`. Vazio = nenhum. */
export function parseInstant(text: string): number | string | undefined | null {
  const value = text.trim()
  if (!value) return undefined
  if (value.toLowerCase().startsWith('marker:')) return value
  const seconds = Number(value.replace(',', '.'))
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null
}

export interface AudioExportForm {
  preset: string
  mode: AudioExportMode
  loudness: string
  group: string
  pauses: boolean
  numbered: boolean
  start: string
  end: string
  tracks: string[]
  sampleRate: string
  channels: string
  bitDepth: string
  bitrateMode: string
  bitrateK: string
  quality: string
}

export function emptyForm(preset = ''): AudioExportForm {
  return {
    preset,
    mode: 'mix',
    loudness: '',
    group: '',
    pauses: false,
    numbered: false,
    start: '',
    end: '',
    tracks: [],
    sampleRate: '',
    channels: '',
    bitDepth: '',
    bitrateMode: '',
    bitrateK: '',
    quality: '',
  }
}

export interface BuiltRequest {
  request: AudioExportRequest | null
  error: string | null
}

const positiveNumber = (text: string): number | null => {
  const value = Number(text.replace(',', '.'))
  return text.trim() && Number.isFinite(value) && value > 0 ? value : null
}

/** O pedido da API a partir do formulário: só leva o que vale no modo e no formato escolhidos. */
export function buildAudioExportRequest(form: AudioExportForm): BuiltRequest {
  if (!form.preset) return { request: null, error: 'Escolha o formato do arquivo.' }
  const request: AudioExportRequest = { preset: form.preset, mode: form.mode }
  if (form.loudness) request.loudness = form.loudness
  if (form.mode === 'regions') {
    if (form.group.trim()) request.group = form.group.trim()
    if (form.pauses) request.pauses = true
    if (form.numbered) request.numbered = true
  }
  if (form.mode === 'selection') {
    const start = parseInstant(form.start)
    const end = parseInstant(form.end)
    if (start === null || end === null) {
      return { request: null, error: 'O início e o fim do trecho são segundos (12,5) ou um marcador (marker:Introdução).' }
    }
    if (start === undefined) return { request: null, error: 'Diga onde o trecho começa.' }
    if (typeof start === 'number' && typeof end === 'number' && end <= start) {
      return { request: null, error: 'O fim do trecho precisa vir depois do início.' }
    }
    request.start = start
    if (end !== undefined) request.end = end
  }
  if (form.mode === 'stems' && form.tracks.length > 0) request.tracks = form.tracks
  const sampleRate = positiveNumber(form.sampleRate)
  if (form.sampleRate.trim() && sampleRate === null) return { request: null, error: 'A taxa de amostragem é um número em Hz.' }
  if (sampleRate !== null) request.sample_rate = Math.round(sampleRate)
  if (form.channels) request.channels = Number(form.channels)
  if (form.bitDepth) request.bit_depth = Number(form.bitDepth)
  if (form.bitrateMode) request.bitrate_mode = form.bitrateMode as AudioExportRequest['bitrate_mode']
  const bitrate = positiveNumber(form.bitrateK)
  if (form.bitrateK.trim() && bitrate === null) return { request: null, error: 'A taxa de bits é um número em kbps.' }
  if (bitrate !== null) request.bitrate_k = Math.round(bitrate)
  if (form.quality.trim()) {
    const quality = Number(form.quality.replace(',', '.'))
    if (!Number.isFinite(quality)) return { request: null, error: 'A qualidade é um número.' }
    request.quality = quality
  }
  return { request, error: null }
}

/** A frase da confirmação quando o servidor diz que os arquivos já existem. */
export function conflictQuestion(existing: string[]): string {
  const names = existing.map((path) => path.split(/[\\/]/).pop() ?? path)
  const shown = names.slice(0, 4).join(', ')
  const extra = names.length > 4 ? ` e mais ${names.length - 4}` : ''
  return names.length === 1
    ? `O arquivo ${shown} já existe. Quer substituí-lo?`
    : `Estes arquivos já existem: ${shown}${extra}. Quer substituí-los?`
}
