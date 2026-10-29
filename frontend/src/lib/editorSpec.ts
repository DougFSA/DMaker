/* Operações do formulário sobre a spec: trechos e sobreposições novos, trocar o tipo, subir e descer, fontes
   sincronizadas (renomear atualiza as referências) e os valores medidos pela sincronização. Funções puras que
   mudam o objeto recebido e dizem o que fizeram; quem decide o que entra no histórico de desfazer é o store. */
import { toRaw } from 'vue'
import type { SpecDocument, SyncResult } from '@/api'
import { baseName } from './format'
import { getPath, setPath } from './editorPaths'

export type SegmentType = 'clip' | 'image' | 'card'
export type OverlayType = 'text' | 'image' | 'video' | 'progress-bar'
type Item = Record<string, unknown>

export const SEGMENT_TYPES: readonly SegmentType[] = ['clip', 'image', 'card']
export const OVERLAY_TYPES: readonly OverlayType[] = ['text', 'image', 'video', 'progress-bar']

export const SEGMENT_TYPE_LABEL: Record<SegmentType, string> = { clip: 'Clipe', image: 'Imagem', card: 'Cartão' }
export const OVERLAY_TYPE_LABEL: Record<OverlayType, string> = {
  text: 'Texto',
  image: 'Imagem',
  video: 'Vídeo (PiP)',
  'progress-bar': 'Barra de progresso',
}

/** Os campos que as seções da spec sempre têm, para o formulário e a lista nunca tropeçarem em `undefined`. */
export function normalizeSpec(spec: SpecDocument): SpecDocument {
  spec.output = (spec.output as Item | undefined) ?? {}
  spec.audio = (spec.audio as Item | undefined) ?? {}
  spec.overlays = (spec.overlays as unknown[] | undefined) ?? []
  spec.timeline = (spec.timeline as unknown[] | undefined) ?? []
  spec.sources = (spec.sources as Item | undefined) ?? {}
  return spec
}

/* ---------- trechos ---------- */

/** Um trecho novo, com os valores que o formulário mostra (o servidor completa o resto com os padrões). */
export function newSegment(type: SegmentType): Item {
  if (type === 'clip') {
    return { type: 'clip', src: '', start: 0, speed: 1, volume: 1, mute: false, fade_in: 0, fade_out: 0 }
  }
  if (type === 'image') {
    return { type: 'image', src: '', duration: 3, motion: 'zoom-in', motion_amount: 0.12, fade_in: 0, fade_out: 0 }
  }
  return { type: 'card', title: '', duration: 3, logo: true, motion: 'zoom-in', motion_amount: 0.04, fade_in: 0, fade_out: 0 }
}

/** Trocar o tipo do trecho refaz os campos próprios dele e leva o que vale para qualquer tipo. */
export function convertSegment(old: Item, type: SegmentType): Item {
  const fresh = newSegment(type)
  for (const key of ['label', 'transition', 'reframe', 'color', 'look']) {
    if (old[key] !== undefined) fresh[key] = old[key]
  }
  fresh.fade_in = old.fade_in ?? 0
  fresh.fade_out = old.fade_out ?? 0
  return fresh
}

/* ---------- sobreposições ---------- */

export function newOverlay(type: OverlayType): Item {
  if (type === 'text') return { type: 'text', text: '', role: 'title', start: 0 }
  if (type === 'image') return { type: 'image', src: 'logo', position: 'top-right', width: 0.22, opacity: 1, start: 0 }
  if (type === 'video') {
    return {
      type: 'video',
      src: '',
      start: 0,
      offset: 0,
      position: 'bottom-right',
      width: 0.28,
      shape: 'rounded',
      radius: 0.08,
      border: 6,
      border_color: 'white',
      shadow: true,
      opacity: 1,
      margin: 40,
      volume: 1,
      animation: 'fade',
      fade: 0.3,
    }
  }
  return { type: 'progress-bar', position: 'bottom', height: 10 }
}

/** Trocar o tipo da sobreposição mantém o início e o fim, que existem em quase todos os tipos. */
export function convertOverlay(old: Item, type: OverlayType): Item {
  const fresh = newOverlay(type)
  if ('start' in fresh && old.start !== undefined) fresh.start = old.start
  if (type !== 'progress-bar' && old.end !== undefined) fresh.end = old.end
  return fresh
}

/* ---------- como cada item aparece na lista ---------- */

const keys = new WeakMap<object, number>()
let nextKey = 1

/**
 * Uma chave estável para o item da lista, que acompanha o item quando ele sobe, desce ou muda de posição. O
 * índice não serve de chave: ao mover um trecho, a tela trocaria os dados sem trocar o cartão que o mostra.
 */
export function stableKey(item: unknown): number {
  if (item === null || typeof item !== 'object') return 0
  const raw = toRaw(item)
  let key = keys.get(raw)
  if (key === undefined) {
    key = nextKey
    nextKey += 1
    keys.set(raw, key)
  }
  return key
}

function fileLabel(item: Item): string {
  if (typeof item.source === 'string' && item.source) return item.source
  return typeof item.src === 'string' && item.src ? baseName(item.src) : ''
}

/** Um resumo curto do trecho para o cabeçalho do cartão recolhido: o arquivo, a fonte ou o título do cartão. */
export function describeSegment(segment: Item): string {
  if (typeof segment.label === 'string' && segment.label) return segment.label
  if (segment.type === 'card') return typeof segment.title === 'string' ? segment.title : ''
  return fileLabel(segment)
}

/** Um resumo curto da sobreposição: o texto, o arquivo ou a fonte. */
export function describeOverlay(overlay: Item): string {
  if (overlay.type === 'text') return typeof overlay.text === 'string' ? overlay.text : ''
  if (overlay.type === 'image' && typeof overlay.src === 'string' && overlay.src.startsWith('logo')) return 'logo da marca'
  return fileLabel(overlay)
}

/* ---------- listas ---------- */

/** Sobe (`-1`) ou desce (`+1`) o item; devolve false quando já está na ponta. */
export function moveInList(list: unknown[], index: number, delta: -1 | 1): boolean {
  const target = index + delta
  if (index < 0 || index >= list.length || target < 0 || target >= list.length) return false
  const moved = list[index]
  list[index] = list[target]
  list[target] = moved
  return true
}

/** Insere uma cópia do item logo depois dele. */
export function duplicateInList(list: unknown[], index: number): boolean {
  if (index < 0 || index >= list.length) return false
  list.splice(index + 1, 0, JSON.parse(JSON.stringify(list[index])))
  return true
}

/** Remove o item, a não ser que a lista ficasse com menos de `minimum` itens. */
export function removeFromList(list: unknown[], index: number, minimum = 0): boolean {
  if (index < 0 || index >= list.length || list.length <= minimum) return false
  list.splice(index, 1)
  return true
}

/* ---------- fontes sincronizadas ---------- */

export function sourceNames(spec: SpecDocument): string[] {
  return Object.keys((spec.sources as Item | undefined) ?? {})
}

/** "fonte1", "fonte2"...: o primeiro nome livre. */
export function nextSourceName(spec: SpecDocument): string {
  const taken = new Set(sourceNames(spec))
  let n = 1
  while (taken.has(`fonte${n}`)) n += 1
  return `fonte${n}`
}

/** O nome de fonte como o formulário aceita: sem espaços nas pontas e com hífen no lugar dos espaços do meio. */
export function cleanSourceName(raw: string): string {
  return raw.trim().replace(/\s+/g, '-')
}

export function addSource(spec: SpecDocument): string {
  const name = nextSourceName(spec)
  const sources = (spec.sources ??= {}) as Item
  sources[name] = { src: '', sync: 'auto', audio_stream: 0 }
  return name
}

/** Segue a lista de fontes de uma lista de itens da spec e aplica `change` aos que usam a fonte. */
function eachSourceUser(spec: SpecDocument, name: string, change: (item: Item) => void): void {
  for (const segment of (spec.timeline as Item[] | undefined) ?? []) {
    if (segment.type === 'clip' && segment.source === name) change(segment)
  }
  for (const overlay of (spec.overlays as Item[] | undefined) ?? []) {
    if (overlay.type === 'video' && overlay.source === name) change(overlay)
  }
}

export type RenameResult = 'renamed' | 'same' | 'empty' | 'exists'

/**
 * Renomeia a fonte e leva junto tudo que a cita: a fonte principal, os clipes, os vídeos sobrepostos, as faixas
 * externas e o bloco multicâmera. A ordem das fontes se mantém (a primeira vale como principal quando `master` falta).
 */
export function renameSource(spec: SpecDocument, oldName: string, rawName: string): RenameResult {
  const next = cleanSourceName(rawName)
  if (!next) return 'empty'
  if (next === oldName) return 'same'
  const sources = (spec.sources as Item | undefined) ?? {}
  if (sources[next] !== undefined) return 'exists'
  spec.sources = Object.fromEntries(Object.entries(sources).map(([key, value]) => [key === oldName ? next : key, value]))
  if (spec.master === oldName) spec.master = next
  eachSourceUser(spec, oldName, (item) => {
    item.source = next
  })
  for (const track of ((spec.audio as Item | undefined)?.tracks as Item[] | undefined) ?? []) {
    if (track.source === oldName) track.source = next
  }
  const multicam = spec.multicam as Item | undefined
  if (multicam) {
    if (Array.isArray(multicam.cameras)) multicam.cameras = multicam.cameras.map((c) => (c === oldName ? next : c))
    if (multicam.main === oldName) multicam.main = next
    if (multicam.audio === oldName) multicam.audio = next
  }
  return 'renamed'
}

/**
 * Remove a fonte. Os clipes e vídeos que a usavam ficam sem origem (para a pessoa escolher outra) e as faixas
 * externas dela saem, porque uma faixa sem fonte não vale.
 */
export function removeSource(spec: SpecDocument, name: string): void {
  const sources = (spec.sources as Item | undefined) ?? {}
  delete sources[name]
  if (spec.master === name) delete spec.master
  eachSourceUser(spec, name, (item) => {
    delete item.source
    item.src ??= ''
  })
  const audio = spec.audio as Item | undefined
  if (audio && Array.isArray(audio.tracks)) {
    audio.tracks = (audio.tracks as Item[]).filter((track) => track.source !== name)
  }
}

/** Troca a origem de um clipe ou vídeo sobreposto: uma fonte sincronizada (`source`) ou um arquivo avulso (`src`). */
export function setOrigin(spec: SpecDocument, base: string, sourceName: string): void {
  if (sourceName) {
    setPath(spec, `${base}.source`, sourceName)
    setPath(spec, `${base}.src`, undefined)
  } else {
    setPath(spec, `${base}.source`, undefined)
  }
}

/**
 * O foco do enquadramento é um par (x, y). Quando a pessoa preenche só um dos dois, o outro fica no centro (0,5),
 * para a spec nunca guardar um par pela metade.
 */
export function completeFocusPair(spec: SpecDocument, path: string): void {
  if (!/\.focus\.[01]$/.test(path)) return
  const pair = getPath(spec, path.replace(/\.[01]$/, ''))
  if (!Array.isArray(pair)) return
  if (pair[0] === undefined) pair[0] = 0.5
  if (pair[1] === undefined) pair[1] = 0.5
}

export type SyncMode = 'auto' | 'manual'

export function syncModeOf(source: Item | undefined): SyncMode {
  return source?.sync === 'auto' ? 'auto' : 'manual'
}

export function setSyncMode(spec: SpecDocument, name: string, mode: SyncMode): void {
  const path = `sources.${name}.sync`
  if (mode === 'auto') {
    setPath(spec, path, 'auto')
    return
  }
  const current = getPath(spec, path)
  setPath(spec, path, typeof current === 'number' ? current : 0)
}

/** As fontes e as outras para sincronizar: a principal (ou a primeira) é o relógio e as demais são medidas contra ela. */
export interface SyncPlan {
  master: string
  masterStream: number
  masterFile: string
  others: Array<{ name: string; file: string }>
}

export type SyncPlanResult = { ok: true; plan: SyncPlan } | { ok: false; reason: string }

export function planSync(spec: SpecDocument): SyncPlanResult {
  const sources = (spec.sources as Record<string, Item> | undefined) ?? {}
  const names = Object.keys(sources)
  if (names.length < 2) return { ok: false, reason: 'Cadastre ao menos duas fontes para sincronizar.' }
  const master = typeof spec.master === 'string' && sources[spec.master] ? spec.master : (names[0] as string)
  const fileOf = (name: string) => String(sources[name]?.src ?? '')
  const others = names.filter((name) => name !== master).map((name) => ({ name, file: fileOf(name) }))
  if (!fileOf(master) || others.some((other) => !other.file)) {
    return { ok: false, reason: 'Preencha o arquivo de cada fonte antes de sincronizar.' }
  }
  return {
    ok: true,
    plan: { master, masterStream: Number(sources[master]?.audio_stream ?? 0), masterFile: fileOf(master), others },
  }
}

/** Grava o deslocamento medido em cada fonte cujo arquivo bate com o da medição; devolve quantas foram atualizadas. */
export function applySyncValues(spec: SpecDocument, rows: SyncResult[]): number {
  const sources = (spec.sources as Record<string, Item> | undefined) ?? {}
  let applied = 0
  for (const row of rows) {
    const name = Object.keys(sources).find((key) => sources[key]?.src === row.path)
    if (!name) continue
    ;(sources[name] as Item).sync = row.offset_s
    applied += 1
  }
  return applied
}

/** O nome do arquivo para mostrar na tabela de sincronização. */
export function syncRowName(row: SyncResult): string {
  return baseName(row.path)
}

/* ---------- legendas automáticas e música ---------- */

/** Liga as legendas automáticas com os valores iniciais ou as desliga (a spec guarda `null`). */
export function setCaptionsEnabled(spec: SpecDocument, enabled: boolean): void {
  spec.captions = enabled ? ((spec.captions as Item | null) ?? { source: 'auto', language: 'pt', model: 'small' }) : null
}

export function setMusicEnabled(spec: SpecDocument, enabled: boolean): void {
  const audio = (spec.audio ??= {}) as Item
  audio.music = enabled ? ((audio.music as Item | null) ?? { src: '' }) : null
}

export function addAudioTrack(spec: SpecDocument): boolean {
  const names = sourceNames(spec)
  if (names.length === 0) return false
  const audio = (spec.audio ??= {}) as Item
  const tracks = (audio.tracks ??= []) as Item[]
  tracks.push({ source: names[0], volume: 1 })
  return true
}
