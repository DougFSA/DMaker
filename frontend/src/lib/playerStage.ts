/* O que o palco do player desenha em cada instante: o trecho da V1 (vídeo, imagem ou cartão), as imagens e a barra
   de progresso (GR), os vídeos sobrepostos (PiP) e o texto (TX), cada um com o estilo já calculado. Puro: a tela
   só traduz estas descrições em elementos. Não mostra transições, movimento de câmera, legendas nem cor: a prévia
   é aproximada, e o render é o que vale. */
import { api, type ProjectTheme, type SpecDocument, type TimelineItem, type TimelineView } from '@/api'
import { clipPlayback, fileTime, itemAt, mediaUrl, type SourceOffsetOf } from './player'

type Loose = Record<string, unknown>

/** Tamanhos de texto (px na base 1080) quando a sobreposição não define o seu, por papel. */
const DEFAULT_TEXT_SIZES: Record<string, number> = {
  hook: 90,
  title: 90,
  subtitle: 56,
  cta: 60,
  'lower-third': 56,
  custom: 60,
}

export type CssStyle = Record<string, string>

export interface StageInput {
  view: TimelineView
  spec: SpecDocument
  theme: ProjectTheme | null
  proxyUrls: Readonly<Record<string, string>>
}

export interface V1Layer {
  /** `none` quando não há trecho (projeto vazio). */
  kind: 'clip' | 'image' | 'card' | 'none'
  item: TimelineItem | null
  /** O arquivo do instante (numa fonte em partes, o da parte que grava o instante). */
  path: string | null
  /** O endereço a mostrar: o proxy leve ou o arquivo; no cartão, o PNG que o servidor desenha. */
  url: string | null
  /** O ponto do arquivo que o clipe mostra agora. */
  fileTime: number
  /** A velocidade do trecho. */
  speed: number
  /** O arquivo do trecho não está no disco. */
  missing: boolean
  /** O endereço do próximo clipe, para deixá-lo carregado e o corte não piscar. */
  nextUrl: string | null
}

export interface GrLayer {
  id: string
  kind: 'image' | 'progress-bar'
  url: string | null
  style: CssStyle
  /** Só na barra de progresso: quanto do vídeo já passou (0 a 1). */
  fraction: number
}

export interface PipLayer {
  id: string
  path: string | null
  url: string | null
  fileTime: number
  style: CssStyle
  missing: boolean
}

export interface TxLayer {
  id: string
  text: string
  role: string
  style: CssStyle
}

export interface StageLayers {
  v1: V1Layer
  gr: GrLayer[]
  pips: PipLayer[]
  tx: TxLayer[]
}

function record(value: unknown): Loose {
  return value && typeof value === 'object' ? (value as Loose) : {}
}

function numberOf(source: Loose, key: string, fallback: number): number {
  const value = source[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function stringOf(source: Loose, key: string): string | undefined {
  const value = source[key]
  return typeof value === 'string' && value ? value : undefined
}

function segmentOf(spec: SpecDocument, index: number): Loose {
  const timeline = spec.timeline
  return Array.isArray(timeline) ? record(timeline[index]) : {}
}

function overlayOf(spec: SpecDocument, index: number): Loose {
  const overlays = spec.overlays
  return Array.isArray(overlays) ? record(overlays[index]) : {}
}

/** O deslocamento de uma fonte nomeada no relógio da sessão, lido da vista. */
export function sourceOffsetFor(view: TimelineView): SourceOffsetOf {
  return (name) => view.sources[name]?.offset ?? 0
}

/** O caminho absoluto do arquivo por trás de um item: o que o servidor já resolveu (`path`), com o `src` e a fonte
 * nomeada como reforço. É por ele, e não pelo `src` cru, que a prévia mostra projetos com caminho relativo. */
export function sourcePathOf(item: TimelineItem, view: TimelineView): string | null {
  if (item.path) return item.path
  if (item.src) return item.src
  if (item.source) {
    const source = view.sources[item.source]
    return source ? source.path || source.src : null
  }
  return null
}

/** Posição (em %) para os quatro cantos, as bordas e o centro, usada pelas imagens e pelo PiP. */
export function cornerStyle(position: string, marginX: number, marginY: number): CssStyle {
  const x = `${marginX}%`
  const y = `${marginY}%`
  switch (position) {
    case 'top-left':
      return { top: y, left: x }
    case 'bottom-left':
      return { bottom: y, left: x }
    case 'bottom-right':
      return { bottom: y, right: x }
    case 'top':
      return { top: y, left: '50%', transform: 'translateX(-50%)' }
    case 'bottom':
      return { bottom: y, left: '50%', transform: 'translateX(-50%)' }
    case 'center':
      return { top: '50%', left: '50%', transform: 'translate(-50%, -50%)' }
    default:
      return { top: y, right: x }
  }
}

/** Onde o texto fica: a posição pedida, ou a do papel (gancho e título no alto, o resto embaixo). */
export function textPosition(role: string, position: unknown): 'top' | 'center' | 'bottom' {
  if (position === 'top' || position === 'center' || position === 'bottom') return position
  return role === 'hook' || role === 'title' ? 'top' : 'bottom'
}

/** O trecho da V1 que o palco mostra: o que cobre o instante ou, depois do fim, o último. */
export function v1ItemAt(view: TimelineView, t: number): TimelineItem | null {
  const items = view.tracks.find((track) => track.id === 'V1')?.items ?? []
  return itemAt(items, t) ?? items[items.length - 1] ?? null
}

function cardUrl(item: TimelineItem, input: StageInput): string | null {
  const segment = segmentOf(input.spec, item.index)
  if (!Object.keys(segment).length) return null
  const output = record(input.spec.output)
  return api.editor.cardPreviewUrl({
    title: stringOf(segment, 'title') ?? '',
    subtitle: stringOf(segment, 'subtitle'),
    variant: stringOf(segment, 'variant'),
    logo: segment.logo === false ? false : true,
    background: stringOf(segment, 'background'),
    brand: stringOf(input.spec, 'brand'),
    preset: stringOf(output, 'preset') ?? 'instagram/reels',
    width: Math.min(1080, input.view.width || 1080),
  })
}

function nextClipUrl(item: TimelineItem, input: StageInput): string | null {
  const items = input.view.tracks.find((track) => track.id === 'V1')?.items ?? []
  const next = items[items.findIndex((candidate) => candidate.id === item.id) + 1]
  if (!next || next.kind !== 'clip' || next.missing) return null
  const first = Array.isArray(next.extra?.pieces) ? (next.extra.pieces as Array<{ path: string }>)[0] : undefined
  return mediaUrl(first?.path ?? sourcePathOf(next, input.view), input.proxyUrls)
}

function v1Layer(t: number, input: StageInput): V1Layer {
  const item = v1ItemAt(input.view, t)
  const empty: V1Layer = { kind: 'none', item, path: null, url: null, fileTime: 0, speed: 1, missing: false, nextUrl: null }
  if (!item) return empty
  const missing = !!item.missing
  if (item.kind === 'image') {
    const path = sourcePathOf(item, input.view)
    return { ...empty, kind: 'image', path, url: mediaUrl(path, input.proxyUrls), missing }
  }
  if (item.kind === 'card') return { ...empty, kind: 'card', url: cardUrl(item, input) }
  if (item.kind === 'clip') {
    const segment = segmentOf(input.spec, item.index)
    const speed = numberOf(segment, 'speed', 1) > 0 ? numberOf(segment, 'speed', 1) : 1
    const playback = clipPlayback(item, t, speed, sourceOffsetFor(input.view), sourcePathOf(item, input.view))
    return {
      kind: 'clip',
      item,
      path: playback.path,
      url: mediaUrl(playback.path, input.proxyUrls),
      fileTime: playback.fileTime,
      speed,
      missing,
      nextUrl: nextClipUrl(item, input),
    }
  }
  return empty
}

/** "logo" e "logo:variante" saem do tema (não são arquivos); qualquer outra imagem é o caminho que o servidor resolveu. */
function overlayImageUrl(item: TimelineItem, input: StageInput): string | null {
  const src = item.src
  if (!src) return null
  if (src === 'logo' || src.startsWith('logo:')) {
    const kind = src.includes(':') ? (src.split(':')[1] ?? 'horizontal') : 'horizontal'
    return input.theme?.logos[kind] ?? null
  }
  return mediaUrl(item.path ?? src, {})
}

function grLayers(t: number, input: StageInput): GrLayer[] {
  const track = input.view.tracks.find((candidate) => candidate.id === 'GR')
  if (!track || track.hidden) return []
  const { view, spec } = input
  const layers: GrLayer[] = []
  for (const item of track.items) {
    if (!(t >= item.start && t < item.end)) continue
    const overlay = overlayOf(spec, item.index)
    if (item.kind === 'progress-bar') {
      const position = typeof item.extra?.position === 'string' ? item.extra.position : 'bottom'
      const fraction = view.total > 0 ? Math.min(1, t / view.total) : 0
      layers.push({
        id: item.id,
        kind: 'progress-bar',
        url: null,
        fraction,
        style: { [position === 'top' ? 'top' : 'bottom']: '0', height: `${numberOf(overlay, 'height', 10)}px` },
      })
      continue
    }
    const url = item.missing ? null : overlayImageUrl(item, input)
    if (!url) continue
    const margin = numberOf(overlay, 'margin', 24)
    const position = typeof item.extra?.position === 'string' ? item.extra.position : 'top-right'
    layers.push({
      id: item.id,
      kind: 'image',
      url,
      fraction: 0,
      style: {
        width: `${(numberOf(overlay, 'width', 0.22) * 100).toFixed(2)}%`,
        opacity: String(numberOf(overlay, 'opacity', 1)),
        ...cornerStyle(position, view.width ? (margin / view.width) * 100 : 3, view.height ? (margin / view.height) * 100 : 3),
      },
    })
  }
  return layers
}

/** A proporção do quadro do PiP: o círculo é sempre 1:1, `aspect` ("16:9", "1:1") manda, e sem ele vale 16:9. */
function pipAspect(overlay: Loose, shape: string): string {
  if (shape === 'circle') return '1 / 1'
  const [width, height] = (stringOf(overlay, 'aspect') ?? '').split(':').map(Number)
  return width && height ? `${width} / ${height}` : '16 / 9'
}

function pipStyle(item: TimelineItem, overlay: Loose, view: TimelineView): CssStyle {
  const shape = stringOf(overlay, 'shape') ?? 'rounded'
  const radius = shape === 'circle' ? '50%' : shape === 'rounded' ? `${numberOf(overlay, 'radius', 0.08) * 100}%` : '0'
  const margin = numberOf(overlay, 'margin', 20)
  const x = overlay.x
  const y = overlay.y
  const position =
    typeof x === 'number' && typeof y === 'number'
      ? { left: `${x * 100}%`, top: `${y * 100}%` }
      : cornerStyle(
          typeof item.extra?.position === 'string' ? item.extra.position : 'bottom-right',
          view.width ? (margin / view.width) * 100 : 3,
          view.height ? (margin / view.height) * 100 : 3,
        )
  return {
    width: `${numberOf(overlay, 'width', 0.28) * 100}%`,
    opacity: String(numberOf(overlay, 'opacity', 1)),
    aspectRatio: pipAspect(overlay, shape),
    borderRadius: radius,
    border: `${numberOf(overlay, 'border', 0)}px solid ${stringOf(overlay, 'border_color') ?? 'white'}`,
    ...position,
  }
}

function pipLayers(t: number, input: StageInput): PipLayer[] {
  const { view, spec } = input
  const layers: PipLayer[] = []
  for (const track of view.tracks) {
    if (track.kind !== 'video' || track.id === 'V1' || track.hidden) continue
    const item = itemAt(track.items, t)
    if (!item) continue
    const path = sourcePathOf(item, view)
    layers.push({
      id: item.id,
      path,
      url: mediaUrl(path, input.proxyUrls),
      fileTime: fileTime(item, t, 1, sourceOffsetFor(view)),
      style: pipStyle(item, overlayOf(spec, item.index), view),
      missing: !!item.missing,
    })
  }
  return layers
}

function txLayers(t: number, input: StageInput): TxLayer[] {
  const track = input.view.tracks.find((candidate) => candidate.id === 'TX')
  if (!track || track.hidden) return []
  const layers: TxLayer[] = []
  for (const item of track.items) {
    if (!(t >= item.start && t < item.end)) continue
    const overlay = overlayOf(input.spec, item.index)
    const role = typeof item.extra?.role === 'string' ? item.extra.role : 'custom'
    const style = record(overlay.style)
    const size = numberOf(style, 'size', DEFAULT_TEXT_SIZES[role] ?? 60)
    const position = textPosition(role, overlay.position)
    layers.push({
      id: item.id,
      text: item.label || '',
      role,
      style: {
        ...(position === 'top'
          ? { top: '8%' }
          : position === 'center'
            ? { top: '50%', transform: 'translateY(-50%)' }
            : { bottom: '10%' }),
        fontSize: `calc(var(--stage-h, 600px) * ${size / 1080})`,
        color: stringOf(style, 'color') ?? input.theme?.colors.text ?? '#FFFFFF',
        fontFamily: input.theme?.font || 'inherit',
        ...(style.uppercase ? { textTransform: 'uppercase' } : {}),
      },
    })
  }
  return layers
}

/** Tudo que o palco desenha no instante `t`. */
export function stageLayers(t: number, input: StageInput): StageLayers {
  return { v1: v1Layer(t, input), gr: grLayers(t, input), pips: pipLayers(t, input), tx: txLayers(t, input) }
}
