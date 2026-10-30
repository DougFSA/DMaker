/* O layout de tela do editor, em funções puras: quais painéis existem, em que encaixe cada um fica, o tamanho dos
   divisores e o que está oculto. O formato é o mesmo da interface clássica (`{version, areas, sizes, hidden, tab}`),
   porque os layouts salvos ficam no mesmo arquivo do servidor e valem nas duas interfaces. */
import type { ScreenLayout } from '@/api'

/** Os painéis que o servidor aceita num layout (o `LAYOUT_PANELS` de `ui/server.py`). */
export const LAYOUT_PANELS = ['player', 'filters', 'media', 'timeline', 'progress', 'properties', 'sidebar', 'voice'] as const
export type LayoutPanelId = (typeof LAYOUT_PANELS)[number]

/** Os quatro painéis que trocam de lugar entre si na bancada do editor. */
export const MOVABLE_PANELS = ['player', 'filters', 'media', 'timeline'] as const
export type MovablePanel = (typeof MOVABLE_PANELS)[number]

/** As abas que um layout pode abrir ao ser escolhido: a linha do tempo (o editor) ou o estúdio de voz. */
export const LAYOUT_TABS = ['timeline', 'voice'] as const
export type LayoutTab = (typeof LAYOUT_TABS)[number]

/** Os encaixes da grade. `top-center` é a faixa de cima, inteira; os outros três dividem a faixa de baixo. */
export const KNOWN_SLOTS = ['top-left', 'top-center', 'top-right', 'bottom', 'dock-bottom', 'sidebar'] as const
export const WORKBENCH_SLOTS = ['top-center', 'top-left', 'bottom', 'top-right'] as const
export type WorkbenchSlot = (typeof WORKBENCH_SLOTS)[number]

export const SIZE_KEYS = ['row-top', 'col-left', 'col-right', 'col-sidebar'] as const
export type SizeKey = (typeof SIZE_KEYS)[number]

/** `row-top` é a fração da altura da bancada que a faixa de cima ocupa; os outros, pixels. O da barra lateral é o
 * da interface nova (15,5 rem); a clássica usa 300. */
export const SIZE_DEFAULTS: Record<SizeKey, number> = { 'row-top': 0.42, 'col-left': 240, 'col-right': 240, 'col-sidebar': 248 }
export const SIZE_RANGES: Record<SizeKey, readonly [number, number]> = {
  'row-top': [0.1, 0.85],
  'col-left': [160, 560],
  'col-right': [160, 560],
  'col-sidebar': [200, 520],
}

export const DEFAULT_LAYOUT_NAME = 'Edição'

/** Um layout já limpo: só o que a interface conhece, com todos os tamanhos dentro da faixa. */
export interface NormalizedLayout extends ScreenLayout {
  version: 1
  tab?: LayoutTab
}

const isPanel = (value: unknown): value is LayoutPanelId => LAYOUT_PANELS.includes(value as LayoutPanelId)
export const isMovablePanel = (value: unknown): value is MovablePanel => MOVABLE_PANELS.includes(value as MovablePanel)
const isSlot = (value: unknown): boolean => KNOWN_SLOTS.includes(value as (typeof KNOWN_SLOTS)[number])

export function clampSize(key: SizeKey, value: number): number {
  const [min, max] = SIZE_RANGES[key]
  return Math.min(max, Math.max(min, value))
}

/**
 * Um layout completo e são a partir de qualquer objeto (o navegador, o servidor, um embutido): encaixes e painéis
 * que a interface não conhece são descartados, tamanhos fora da faixa são cortados e os que faltam recebem o
 * padrão. Nunca lança erro.
 */
export function normalizeLayout(raw: unknown): NormalizedLayout {
  const source = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {}
  const rawAreas = source.areas && typeof source.areas === 'object' ? (source.areas as Record<string, unknown>) : {}
  const areas: Record<string, string> = {}
  for (const [slot, panel] of Object.entries(rawAreas)) {
    if (isSlot(slot) && isPanel(panel)) areas[slot] = panel
  }
  const hidden = Array.isArray(source.hidden) ? [...new Set(source.hidden.filter(isPanel))] : []
  const rawSizes = source.sizes && typeof source.sizes === 'object' ? (source.sizes as Record<string, unknown>) : {}
  const sizes: Record<string, number> = {}
  for (const key of SIZE_KEYS) {
    const value = rawSizes[key]
    sizes[key] = clampSize(key, typeof value === 'number' && Number.isFinite(value) ? value : SIZE_DEFAULTS[key])
  }
  const layout: NormalizedLayout = { version: 1, areas, sizes, hidden }
  if (LAYOUT_TABS.includes(source.tab as LayoutTab)) layout.tab = source.tab as LayoutTab
  return layout
}

/**
 * O layout com os painéis `a` e `b` trocados de encaixe. Se só um dos dois estiver na grade, ele assume o encaixe do
 * outro (o que não estava na grade continua fora dela).
 */
export function swapPanels(layout: ScreenLayout, a: string, b: string): NormalizedLayout {
  const normalized = normalizeLayout(layout)
  const areas = { ...normalized.areas }
  const slotOf = (panel: string) => Object.keys(areas).find((slot) => areas[slot] === panel)
  const slotA = slotOf(a)
  const slotB = slotOf(b)
  if (slotA && slotB) {
    areas[slotA] = b
    areas[slotB] = a
  } else if (slotA) {
    areas[slotA] = b
  } else if (slotB) {
    areas[slotB] = a
  }
  return { ...normalized, areas }
}

/** O encaixe de cada painel quando ninguém mexeu: o player em cima; filtros, linha do tempo e mídia embaixo. */
export const EDITING_AREAS: Record<WorkbenchSlot, MovablePanel> = {
  'top-center': 'player',
  'top-left': 'filters',
  bottom: 'timeline',
  'top-right': 'media',
}

/**
 * Os layouts embutidos, os mesmos da interface clássica (inspirados no menu "Layout" do Shotcut). "Edição" é a
 * disposição padrão; os outros mudam tamanhos e o que fica oculto. "Voz" abre o estúdio de voz.
 */
export function builtinLayouts(): Record<string, NormalizedLayout> {
  const make = (sizes: Partial<Record<SizeKey, number>>, hidden: LayoutPanelId[], tab: LayoutTab) =>
    normalizeLayout({ areas: EDITING_AREAS, sizes, hidden, tab })
  return {
    Edição: make({}, ['progress'], 'timeline'),
    Efeitos: make({ 'col-left': 420 }, ['progress', 'media'], 'timeline'),
    Áudio: make({ 'row-top': 0.16 }, ['progress'], 'timeline'),
    Player: make({ 'row-top': 0.72 }, ['progress'], 'timeline'),
    Revisão: make({ 'row-top': 0.22 }, [], 'timeline'),
    Voz: make({}, ['progress'], 'voice'),
  }
}

export const BUILTIN_NAMES = Object.keys(builtinLayouts())

export function isBuiltinName(name: string): boolean {
  return BUILTIN_NAMES.includes(name)
}

/**
 * Qual painel mora em cada encaixe da bancada. Um layout salvo pela metade (sem todos os painéis) completa o que
 * falta pelo padrão, e um painel repetido vale só no primeiro encaixe.
 */
export function placement(layout: ScreenLayout): Record<WorkbenchSlot, MovablePanel | null> {
  const result: Record<WorkbenchSlot, MovablePanel | null> = {
    'top-center': null,
    'top-left': null,
    bottom: null,
    'top-right': null,
  }
  const placed = new Set<MovablePanel>()
  for (const slot of WORKBENCH_SLOTS) {
    const panel = layout.areas[slot]
    if (isMovablePanel(panel) && !placed.has(panel)) {
      result[slot] = panel
      placed.add(panel)
    }
  }
  for (const panel of MOVABLE_PANELS) {
    if (placed.has(panel)) continue
    const preferred = (Object.keys(EDITING_AREAS) as WorkbenchSlot[]).find((slot) => EDITING_AREAS[slot] === panel)
    const slot = preferred && result[preferred] === null ? preferred : WORKBENCH_SLOTS.find((candidate) => result[candidate] === null)
    if (slot) {
      result[slot] = panel
      placed.add(panel)
    }
  }
  return result
}

/** O layout com todos os encaixes da bancada preenchidos (o que `placement` decidiu), para trocar painéis sem lacuna. */
export function withFullAreas(layout: ScreenLayout): NormalizedLayout {
  const normalized = normalizeLayout(layout)
  const areas = { ...normalized.areas }
  for (const [slot, panel] of Object.entries(placement(normalized))) if (panel) areas[slot] = panel
  return { ...normalized, areas }
}

export type MoveDirection = 'up' | 'down' | 'left' | 'right'

/** O tipo que marca, no arrastar e soltar, que o que se arrasta é um painel (e não uma mídia da linha do tempo). */
export const PANEL_DRAG_MIME = 'application/x-dmaker-panel'

/** As teclas que trocam o painel de lugar com o vizinho, quando a pessoa não usa o mouse. */
export const MOVE_KEYS: Record<string, MoveDirection> = {
  ArrowUp: 'up',
  ArrowDown: 'down',
  ArrowLeft: 'left',
  ArrowRight: 'right',
}

/**
 * O encaixe vizinho numa direção, para trocar de lugar pelo teclado. A faixa de cima fica sobre a do meio; a faixa
 * de baixo tem esquerda, meio e direita. Devolve null onde não há vizinho.
 */
export function neighborSlot(slot: WorkbenchSlot, direction: MoveDirection): WorkbenchSlot | null {
  const map: Record<WorkbenchSlot, Partial<Record<MoveDirection, WorkbenchSlot>>> = {
    'top-center': { down: 'bottom' },
    'top-left': { up: 'top-center', right: 'bottom' },
    bottom: { up: 'top-center', left: 'top-left', right: 'top-right' },
    'top-right': { up: 'top-center', left: 'bottom' },
  }
  return map[slot][direction] ?? null
}

/** A mesma disposição, tamanhos e painéis ocultos (a ordem dos ocultos não importa). Diz se o layout foi alterado. */
export function sameLayout(a: ScreenLayout, b: ScreenLayout): boolean {
  const left = withFullAreas(a)
  const right = withFullAreas(b)
  const areasMatch = WORKBENCH_SLOTS.every((slot) => left.areas[slot] === right.areas[slot])
  const sizesMatch = SIZE_KEYS.every((key) => Math.abs((left.sizes[key] ?? 0) - (right.sizes[key] ?? 0)) < 0.005)
  const hiddenMatch = [...left.hidden].sort().join() === [...right.hidden].sort().join()
  return areasMatch && sizesMatch && hiddenMatch
}

/** As colunas e linhas da grade (valores de `grid-template-*`), recolhendo o que não tem painel visível. */
export interface WorkbenchGrid {
  columns: string
  rows: string
  showRowDivider: boolean
  showLeftDivider: boolean
  showRightDivider: boolean
}

export function workbenchGrid(layout: ScreenLayout, visible: Record<WorkbenchSlot, boolean>): WorkbenchGrid {
  const sizes = normalizeLayout(layout).sizes
  const left = visible['top-left']
  const right = visible['top-right']
  const middle = visible.bottom
  const topRow = visible['top-center']
  const bottomRow = left || right || middle
  const showRowDivider = topRow && bottomRow
  // os divisores de coluna só existem ao lado da linha do tempo; sem ela, as colunas que sobram dividem a largura
  const showLeftDivider = middle && left
  const showRightDivider = middle && right
  const ratio = sizes['row-top'] ?? SIZE_DEFAULTS['row-top']
  const fill = 'minmax(0, 1fr)'
  const columns = middle
    ? [left ? `${sizes['col-left']}px` : '0px', showLeftDivider ? '6px' : '0px', fill, showRightDivider ? '6px' : '0px', right ? `${sizes['col-right']}px` : '0px']
    : [left ? fill : '0px', '0px', '0px', '0px', right ? fill : '0px']
  return {
    columns: columns.join(' '),
    rows: showRowDivider ? `${(ratio * 100).toFixed(1)}% 6px ${fill}` : topRow ? `${fill} 0px 0px` : `0px 0px ${fill}`,
    showRowDivider,
    showLeftDivider,
    showRightDivider,
  }
}
