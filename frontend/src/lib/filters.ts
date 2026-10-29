/* As contas do painel Filtros, todas puras: do item selecionado na linha do tempo ao tipo do catálogo, quais grupos
   já saem do padrão ("aplicados") e quais caminhos o "×" de um grupo devolve ao padrão. Os padrões vêm do schema da
   spec (GET /api/schema), nunca de uma cópia escrita à mão. */
import type { TimelineItem, TimelineView } from '@/api'
import { getPath, setPath } from './editorPaths'
import { schemaDef } from './editorSchema'
import { FILTER_TARGETS, type FilterGroup, type FilterTarget } from './filterCatalog'

type Schema = Record<string, unknown> | null

/** O item escolhido na linha do tempo, traduzido para o que o painel precisa saber. */
export interface FilterContext {
  target: Exclude<FilterTarget, 'project'>
  /** Onde o item mora na spec: "timeline.2", "overlays.0", "audio.tracks.1", "audio.music" ou "captions". */
  base: string
}

const SEGMENT_KINDS = ['clip', 'image', 'card']

/**
 * Do item selecionado (e da trilha dele) ao tipo de filtros e ao caminho dele na spec. A faixa A1 é só a sombra de
 * áudio de um clipe da V1, então escolher um item dela edita o clipe correspondente. Devolve null quando o item não
 * tem filtros próprios (a narração, por exemplo): o painel então mostra os do projeto.
 */
export function selectionFor(
  trackId: string,
  item: Pick<TimelineItem, 'kind' | 'index'>,
  view: Pick<TimelineView, 'tracks'>,
): FilterContext | null {
  if (trackId === 'A1') {
    const v1Item = view.tracks.find((track) => track.id === 'V1')?.items.find((candidate) => candidate.index === item.index)
    return v1Item ? segmentContext(v1Item) : null
  }
  if (trackId === 'V1') return segmentContext(item)
  if (trackId === 'TX') return { target: 'text', base: `overlays.${item.index}` }
  if (trackId === 'GR') {
    return { target: item.kind === 'progress-bar' ? 'progress-bar' : 'image-overlay', base: `overlays.${item.index}` }
  }
  if (/^V\d+$/.test(trackId)) return { target: 'video', base: `overlays.${item.index}` }
  if (/^A[2-9]\d*$/.test(trackId)) return { target: 'track', base: `audio.tracks.${item.index}` }
  if (trackId === 'MUS') return { target: 'music', base: 'audio.music' }
  if (trackId === 'CC') return { target: 'captions', base: 'captions' }
  return null
}

function segmentContext(item: Pick<TimelineItem, 'kind' | 'index'>): FilterContext | null {
  return SEGMENT_KINDS.includes(item.kind) ? { target: item.kind as FilterContext['target'], base: `timeline.${item.index}` } : null
}

/** Uma chave que muda quando a pessoa seleciona outra coisa: os grupos que ela abriu com o "+" não passam para o item novo. */
export function contextKey(context: FilterContext | null): string {
  return context ? `${context.target}:${context.base}` : 'project'
}

/** O título do painel para o tipo escolhido ("Clipe", "Projeto (nada selecionado)"). */
export function targetTitle(target: FilterTarget): string {
  return FILTER_TARGETS[target].title
}

/** A definição do schema que dá os padrões do grupo: a do próprio grupo (projeto) ou a do tipo de item. */
export function defaultsDefOf(group: FilterGroup, target: FilterTarget): string | null {
  return group.defaultsDef ?? FILTER_TARGETS[target].def
}

function propertyNode(schema: Schema, defName: string | null, key: string): Record<string, unknown> | null {
  if (!defName) return null
  const properties = schemaDef(schema, defName)?.properties
  const node = properties && typeof properties === 'object' ? (properties as Record<string, unknown>)[key] : undefined
  return node && typeof node === 'object' ? (node as Record<string, unknown>) : null
}

/**
 * O valor padrão de um caminho do item (por exemplo `reframe.zoom` no clipe): o padrão da propriedade do primeiro
 * nível e, dentro dele, o resto do caminho. `undefined` quando o schema não o diz.
 */
export function defaultAt(schema: Schema, defName: string | null, path: string): unknown {
  const [first = '', ...rest] = path.split('.')
  const node = propertyNode(schema, defName, first)
  if (!node || !('default' in node)) return undefined
  let value: unknown = node.default
  for (const part of rest) {
    if (value === null || typeof value !== 'object') return undefined
    value = (value as Record<string, unknown>)[part]
  }
  return value
}

/** A propriedade do primeiro nível existe no schema e não tem padrão: o item não vale sem ela (o `src` da música). */
function isRequired(schema: Schema, defName: string | null, key: string): boolean {
  const node = propertyNode(schema, defName, key)
  return node !== null && !('default' in node)
}

function sameValue(a: unknown, b: unknown): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null)
}

function topLevelKeys(group: FilterGroup): string[] {
  return [...new Set(group.fields.map((field) => field.key.split('.')[0] as string))]
}

/** Grupo com um campo obrigatório (o texto, a música) fica sempre à mostra e não tem "×": sem ele o item não existe. */
export function isPinned(group: FilterGroup, defName: string | null, schema: Schema): boolean {
  return topLevelKeys(group).some((key) => isRequired(schema, defName, key))
}

/**
 * O grupo está "aplicado" quando algum campo dele sai do padrão do schema. `read` lê o valor da spec por caminho
 * relativo ao item; campo ausente vale o padrão, e `null` e ausente são a mesma coisa.
 */
export function isGroupApplied(
  group: FilterGroup,
  defName: string | null,
  schema: Schema,
  read: (path: string) => unknown,
): boolean {
  if (isPinned(group, defName, schema)) return true
  return group.fields.some((field) => {
    const fallback = defaultAt(schema, defName, field.key)
    const stored = read(field.key)
    return !sameValue(stored === undefined ? fallback : stored, fallback)
  })
}

/**
 * Os caminhos que o "×" apaga para o grupo voltar ao padrão: o contêiner de cada campo (`reframe`, `style`) ou o
 * próprio campo. O que o schema marca como obrigatório fica, para a spec não ficar inválida.
 */
export function resetPaths(group: FilterGroup, base: string, defName: string | null, schema: Schema): string[] {
  return topLevelKeys(group)
    .filter((key) => !isRequired(schema, defName, key))
    .map((key) => `${base}.${key}`)
}

/** Apaga os caminhos da spec: o campo some e passa a valer o padrão do servidor. O que já não existe fica como está. */
export function resetPathsIn(spec: Record<string, unknown>, paths: readonly string[]): void {
  for (const path of paths) {
    // `setPath` cria os contêineres que faltam; para apagar, isso inventaria um caminho que não existia
    if (getPath(spec, path) !== undefined) setPath(spec, path, undefined)
  }
}
