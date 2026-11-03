/* A mídia que um projeto usa, para as telas de áudio escolherem um arquivo dele, e a troca de um arquivo por outro
   na spec ("Usar no projeto" depois de corrigir a fala, trocar a voz ou dublar). Funções puras, sem rede. */
import type { EditOperation, ProjectSpec, TimelineView } from '@/api'
import { baseName } from './format'

export type MediaEntryKind = 'clip' | 'image' | 'audio'

export interface MediaEntry {
  /** `source:<nome>` para fonte sincronizada, `file:<caminho>` para arquivo avulso. */
  id: string
  kind: MediaEntryKind
  label: string
  /** Caminho absoluto quando o servidor o resolveu; sem a vista, o `src` como está na spec. */
  path: string
  /** O `src` cru como está na spec (é o que a troca de arquivo compara). Só nos arquivos avulsos. */
  src?: string
  /** O nome da fonte sincronizada. Só nas fontes. */
  source?: string
}

/** Uma opção do seletor: a entrada e o caminho que as rotas de áudio recebem. */
export interface MediaOption {
  value: string
  label: string
  path: string
  entry: MediaEntry
}

interface SpecItem {
  type?: string
  src?: string | null
}

/** O pedaço da spec que interessa aqui; o resto é do backend. */
export interface MediaSpec {
  sources?: Record<string, { src?: string | null; parts?: string[] | null }>
  timeline?: SpecItem[]
  overlays?: SpecItem[]
  audio?: { music?: { src?: string | null } | null } | null
}

const MEDIA_KINDS: readonly MediaEntryKind[] = ['clip', 'audio']
const ABSOLUTE_PATH = /^([a-zA-Z]:[\\/]|[\\/])/

/** `src` cru -> caminho absoluto que o servidor resolveu, lido dos itens da vista de qualquer trilha. */
function resolvedPaths(view: TimelineView | null): Map<string, string> {
  const map = new Map<string, string>()
  for (const track of view?.tracks ?? []) {
    for (const item of track.items) {
      if (item.src && item.path) map.set(item.src, item.path)
    }
  }
  return map
}

/**
 * As fontes sincronizadas e os arquivos avulsos da spec (trechos, sobreposições e música), sem repetir arquivo.
 * `view` (a vista de linha do tempo) só serve para trocar caminho relativo pelo absoluto que o render usa.
 */
export function collectMediaEntries(spec: ProjectSpec | MediaSpec, view: TimelineView | null = null): MediaEntry[] {
  const media = spec as MediaSpec
  const entries: MediaEntry[] = []
  const seen = new Set<string>()
  const resolved = resolvedPaths(view)

  for (const [name, ref] of Object.entries(media.sources ?? {})) {
    const files = ref.parts?.length ? ref.parts : ref.src ? [ref.src] : []
    const path = view?.sources[name]?.path || files[0]
    if (!path) continue
    entries.push({ id: `source:${name}`, kind: 'clip', label: name, path, source: name })
    for (const file of files) seen.add(file)
  }

  const addFile = (src: string | null | undefined, kind: MediaEntryKind): void => {
    if (!src || seen.has(src)) return
    seen.add(src)
    entries.push({ id: `file:${src}`, kind, label: baseName(src), path: resolved.get(src) || src, src })
  }

  for (const segment of media.timeline ?? []) {
    if (segment.type === 'clip') addFile(segment.src, 'clip')
    else if (segment.type === 'image') addFile(segment.src, 'image')
  }
  for (const overlay of media.overlays ?? []) {
    // "logo" e "logo:variante" são imagens da marca, não arquivos
    if (overlay.type === 'image' && overlay.src && overlay.src !== 'logo' && !overlay.src.startsWith('logo:')) {
      addFile(overlay.src, 'image')
    } else if (overlay.type === 'video') {
      addFile(overlay.src, 'clip')
    }
  }
  addFile(media.audio?.music?.src, 'audio')
  return entries
}

/** Alguma entrada ainda tem caminho relativo? Só então vale pedir ao servidor a vista para resolvê-lo. */
export function hasRelativePaths(entries: MediaEntry[]): boolean {
  return entries.some((entry) => !ABSOLUTE_PATH.test(entry.path))
}

/** Os arquivos com som (vídeos e áudios) em forma de opção do seletor. Imagem não entra: não tem fala para tratar. */
export function projectMediaOptions(entries: MediaEntry[]): MediaOption[] {
  return entries
    .filter((entry) => MEDIA_KINDS.includes(entry.kind) && entry.path)
    .map((entry, index) => ({ value: `project:${index}`, label: entry.label, path: entry.path, entry }))
}

export type SetFieldOperation = Extract<EditOperation, { type: 'set_field' }>

/**
 * As operações `set_field` que trocam o arquivo original pelo novo em tudo que o usa no projeto: a fonte sincronizada
 * (multicâmera), os trechos de vídeo e os vídeos sobrepostos (picture-in-picture). `entry` vem de `collectMediaEntries`.
 * Sem entrada ou sem spec, não há o que trocar.
 */
export function replaceSourceOps(
  spec: ProjectSpec | MediaSpec | null,
  entry: MediaEntry | null,
  newPath: string,
): SetFieldOperation[] {
  if (!entry || !spec) return []
  if (entry.source) return [{ type: 'set_field', path: `sources.${entry.source}.src`, value: newPath }]

  const media = spec as MediaSpec
  const ops: SetFieldOperation[] = []
  ;(media.timeline ?? []).forEach((segment, index) => {
    if (segment.type === 'clip' && segment.src === entry.src) {
      ops.push({ type: 'set_field', path: `timeline.${index}.src`, value: newPath })
    }
  })
  ;(media.overlays ?? []).forEach((overlay, index) => {
    if (overlay.type === 'video' && overlay.src === entry.src) {
      ops.push({ type: 'set_field', path: `overlays.${index}.src`, value: newPath })
    }
  })
  return ops
}
