/* Os gestos de arrastar e redimensionar uma sobreposição no palco, sem tocar no navegador: para onde a caixa vai a cada
   movimento do mouse (com o ímã), quais alças cada caixa tem e que campos da spec o gesto grava ao soltar. Puro.
   A caixa de partida é a que o servidor calculou (a mesma conta do render e do QA); aqui só se desloca essa caixa e
   se traduz o resultado nos campos que a spec já tem (`x`, `y`, `width`, `height`, `style.max_width`), sem campo novo. */
import type { SafeZoneFractions, SafeZoneSide } from '@/api'
import { SNAP_PX } from './timeline'
import { textAlignOf, type PlacedBox } from './overlayBoxes'

/** Um retângulo em fração do quadro nativo. */
export interface Rect {
  left: number
  top: number
  width: number
  height: number
}

export type Handle = 'n' | 'e' | 's' | 'w' | 'ne' | 'nw' | 'se' | 'sw'

/** O quadro nativo do preset em px: só serve para a folga de 1 px da zona segura e para a proporção do PiP. */
export interface FrameSize {
  width: number
  height: number
}

/** Menor largura (fração do quadro) que uma imagem, um PiP ou uma área de HTML pode ter ao ser redimensionada. */
export const MIN_BOX_FRACTION = 0.05
/** Menor largura da quebra do texto: abaixo disso cada palavra ficaria sozinha numa linha. */
export const MIN_WRAP_FRACTION = 0.1

const round4 = (value: number) => Math.round(value * 10000) / 10000
const clamp = (value: number, low: number, high: number) => Math.min(Math.max(value, low), high)

/* ---------- o ímã ---------- */

/** As linhas que puxam a caixa: o centro do quadro, as bordas e as margens da zona segura, em cada eixo. */
export interface SnapLines {
  x: number[]
  y: number[]
}

/** O ímã de um gesto: as linhas e a tolerância (fração do quadro em cada eixo, vinda dos 8 px de tela). */
export interface SnapSettings {
  lines: SnapLines
  tolerance: { x: number; y: number }
}

export function snapLines(zone: SafeZoneFractions): SnapLines {
  return {
    x: [0, zone.left, 0.5, 1 - zone.right, 1],
    y: [0, zone.top, 0.5, 1 - zone.bottom, 1],
  }
}

/** A tolerância do ímã em fração do quadro, para o palco do tamanho dado em px de tela (`SNAP_PX`, como a linha do tempo). */
export function snapSettings(zone: SafeZoneFractions, stagePx: { width: number; height: number }): SnapSettings {
  return { lines: snapLines(zone), tolerance: { x: SNAP_PX / stagePx.width, y: SNAP_PX / stagePx.height } }
}

export interface Snapped {
  /** Quanto somar à posição para o ponto cair na linha (0 quando nenhuma está perto). */
  offset: number
  /** A linha que segura o ponto, para a guia desenhada; nula quando nada o segura. */
  line: number | null
}

/** Entre vários pontos da caixa (borda, centro, borda) e as linhas, o par mais próximo se estiver dentro da tolerância. */
export function snapPoints(points: readonly number[], lines: readonly number[], tolerance: number): Snapped {
  let best: Snapped = { offset: 0, line: null }
  let bestDistance = tolerance
  for (const point of points) {
    for (const line of lines) {
      const distance = Math.abs(line - point)
      if (distance < bestDistance) {
        bestDistance = distance
        best = { offset: line - point, line }
      }
    }
  }
  return best
}

/** As linhas-guia que estão segurando a caixa agora (uma vertical e uma horizontal, em fração do quadro). */
export interface Guides {
  x: number | null
  y: number | null
}

export interface GestureStep {
  /** A caixa como ficaria agora: o contorno, o texto, a imagem e o PiP do palco seguem esta. */
  box: PlacedBox
  guides: Guides
}

/* ---------- as alças ---------- */

/** As alças que a caixa tem, por tipo de redimensionamento (decisões 5 e 6) e, no texto, pelo alinhamento: a alça segue
 * a âncora, então o centralizado puxa as duas bordas, o alinhado à esquerda só a direita e o alinhado à direita só a esquerda. */
export function handlesOf(box: PlacedBox): Handle[] {
  if (!box.movable) return []
  if (box.resize === 'text_width') {
    const align = textAlignOf(box)
    return align === 'left' ? ['e'] : align === 'right' ? ['w'] : ['w', 'e']
  }
  if (box.resize === 'keep_aspect') return ['nw', 'ne', 'sw', 'se']
  if (box.resize === 'free') return ['n', 'ne', 'e', 'se', 's', 'sw', 'w', 'nw']
  return []
}

/** O retângulo onde as alças ficam: o da caixa, ou o da quebra no texto (a alça muda a largura da quebra). */
export function handleFrame(box: PlacedBox): Rect {
  if (box.resize === 'text_width' && box.wrap) return { left: box.wrap.left, top: box.top, width: box.wrap.width, height: box.height }
  return { left: box.left, top: box.top, width: box.width, height: box.height }
}

/* ---------- mover ---------- */

function anchorOf(box: PlacedBox): { x: number; y: number } {
  return box.anchor ?? { x: box.left + box.width / 2, y: box.top + box.height / 2 }
}

function shifted(box: PlacedBox, dx: number, dy: number): PlacedBox {
  return {
    ...box,
    left: box.left + dx,
    top: box.top + dy,
    anchor: box.anchor ? { x: box.anchor.x + dx, y: box.anchor.y + dy } : null,
    wrap: box.wrap ? { ...box.wrap, left: box.wrap.left + dx } : null,
  }
}

/**
 * A caixa deslocada `dx`, `dy` (fração do quadro) do ponto de partida. Com ímã, as bordas e o centro da caixa são
 * puxados para as linhas; o ponto de âncora nunca sai do quadro (`x` e `y` da spec ficam entre 0 e 1).
 */
export function moveStep(box: PlacedBox, dx: number, dy: number, snap: SnapSettings | null): GestureStep {
  const anchor = anchorOf(box)
  let moveX = dx
  let moveY = dy
  let guideX: number | null = null
  let guideY: number | null = null
  if (snap) {
    const horizontal = snapPoints([box.left + dx, box.left + box.width / 2 + dx, box.left + box.width + dx], snap.lines.x, snap.tolerance.x)
    const vertical = snapPoints([box.top + dy, box.top + box.height / 2 + dy, box.top + box.height + dy], snap.lines.y, snap.tolerance.y)
    moveX += horizontal.offset
    moveY += vertical.offset
    guideX = horizontal.line
    guideY = vertical.line
  }
  const limitedX = clamp(moveX, -anchor.x, 1 - anchor.x)
  const limitedY = clamp(moveY, -anchor.y, 1 - anchor.y)
  // a guia só vale quando a caixa chegou mesmo à linha: se o limite do quadro a segurou antes, não há linha a mostrar
  if (limitedX !== moveX) guideX = null
  if (limitedY !== moveY) guideY = null
  return { box: shifted(box, limitedX, limitedY), guides: { x: guideX, y: guideY } }
}

/* ---------- redimensionar ---------- */

/** O texto: a largura da quebra muda pela alça e a caixa em si só se refaz quando o servidor medir de novo. No
 * centralizado a quebra é simétrica em torno da âncora; nos alinhados, a borda do lado da âncora fica parada. */
function resizeWrap(box: PlacedBox, handle: Handle, dx: number, snap: SnapSettings | null): GestureStep {
  const align = textAlignOf(box)
  const wrap = box.wrap ?? { left: box.left, width: box.width }
  const anchor = anchorOf(box)
  const right = wrap.left + wrap.width
  const dragged = handle === 'e' ? right + dx : wrap.left + dx
  const snapped = snap ? snapPoints([dragged], snap.lines.x, snap.tolerance.x) : { offset: 0, line: null }
  const edge = dragged + snapped.offset
  let width: number
  if (align === 'center') width = handle === 'e' ? 2 * (edge - anchor.x) : 2 * (anchor.x - edge)
  else width = handle === 'e' ? edge - wrap.left : right - edge
  const limited = clamp(width, MIN_WRAP_FRACTION, 1)
  const left = align === 'center' ? anchor.x - limited / 2 : align === 'left' ? wrap.left : right - limited
  return { box: { ...box, wrap: { left, width: limited } }, guides: { x: limited === width ? snapped.line : null, y: null } }
}

/** Imagem e PiP: pelo canto, com o canto oposto parado e o aspecto mantido. O fator de escala é a projeção do ponteiro
 * na diagonal (em px do quadro, para a proporção não se perder), e o ímã segura o canto puxado numa linha. */
function resizeCorner(box: PlacedBox, handle: Handle, dx: number, dy: number, snap: SnapSettings | null, frame: FrameSize): GestureStep {
  const hx = handle.includes('e') ? 1 : -1
  const hy = handle.includes('s') ? 1 : -1
  const originX = hx > 0 ? box.left : box.left + box.width
  const originY = hy > 0 ? box.top : box.top + box.height
  const diagonalX = hx * box.width * frame.width
  const diagonalY = hy * box.height * frame.height
  const pointerX = (hx * box.width + dx) * frame.width
  const pointerY = (hy * box.height + dy) * frame.height
  let scale = (pointerX * diagonalX + pointerY * diagonalY) / (diagonalX * diagonalX + diagonalY * diagonalY)
  const guides: Guides = { x: null, y: null }
  if (snap) {
    let best: { scale: number; axis: 'x' | 'y'; line: number; weight: number } | null = null
    const candidates: Array<{ axis: 'x' | 'y'; lines: number[]; origin: number; direction: number; size: number; tolerance: number }> = [
      { axis: 'x', lines: snap.lines.x, origin: originX, direction: hx, size: box.width, tolerance: snap.tolerance.x },
      { axis: 'y', lines: snap.lines.y, origin: originY, direction: hy, size: box.height, tolerance: snap.tolerance.y },
    ]
    for (const candidate of candidates) {
      for (const line of candidate.lines) {
        const target = (line - candidate.origin) / (candidate.direction * candidate.size)
        if (target <= 0) continue
        const distance = Math.abs(target - scale) * candidate.size
        if (distance >= candidate.tolerance) continue
        const weight = distance / candidate.tolerance
        if (!best || weight < best.weight) best = { scale: target, axis: candidate.axis, line, weight }
      }
    }
    if (best) {
      scale = best.scale
      guides[best.axis] = best.line
    }
  }
  const minScale = MIN_BOX_FRACTION / box.width
  // a largura cabe no quadro e o centro (o `x`/`y` da spec) não passa da borda
  const reachX = (2 * (hx > 0 ? 1 - originX : originX)) / box.width
  const reachY = (2 * (hy > 0 ? 1 - originY : originY)) / box.height
  const maxScale = Math.max(minScale, Math.min(1 / box.width, reachX, reachY))
  const limited = clamp(scale, minScale, maxScale)
  if (limited !== scale) {
    guides.x = null
    guides.y = null
  }
  const width = box.width * limited
  const height = box.height * limited
  return {
    box: { ...box, left: hx > 0 ? originX : originX - width, top: hy > 0 ? originY : originY - height, width, height },
    guides,
  }
}

/** HTML: por bordas e cantos, com o lado oposto parado. Cada borda puxada tem o seu ímã. */
function resizeFree(box: PlacedBox, handle: Handle, dx: number, dy: number, snap: SnapSettings | null): GestureStep {
  let left = box.left
  let right = box.left + box.width
  let top = box.top
  let bottom = box.top + box.height
  const guides: Guides = { x: null, y: null }
  const pull = (edge: number, lines: number[] | undefined, tolerance: number | undefined) => {
    const snapped = snap && lines && tolerance ? snapPoints([edge], lines, tolerance) : { offset: 0, line: null }
    return { edge: edge + snapped.offset, line: snapped.line }
  }
  if (handle.includes('e')) {
    const moved = pull(right + dx, snap?.lines.x, snap?.tolerance.x)
    right = clamp(moved.edge, left + MIN_BOX_FRACTION, Math.min(left + 1, 2 - left))
    guides.x = right === moved.edge ? moved.line : null
  } else if (handle.includes('w')) {
    const moved = pull(left + dx, snap?.lines.x, snap?.tolerance.x)
    left = clamp(moved.edge, Math.max(right - 1, -right), right - MIN_BOX_FRACTION)
    guides.x = left === moved.edge ? moved.line : null
  }
  if (handle.includes('s')) {
    const moved = pull(bottom + dy, snap?.lines.y, snap?.tolerance.y)
    bottom = clamp(moved.edge, top + MIN_BOX_FRACTION, Math.min(top + 1, 2 - top))
    guides.y = bottom === moved.edge ? moved.line : null
  } else if (handle.includes('n')) {
    const moved = pull(top + dy, snap?.lines.y, snap?.tolerance.y)
    top = clamp(moved.edge, Math.max(bottom - 1, -bottom), bottom - MIN_BOX_FRACTION)
    guides.y = top === moved.edge ? moved.line : null
  }
  return { box: { ...box, left, top, width: right - left, height: bottom - top }, guides }
}

/** A caixa redimensionada pela alça `handle`, conforme o tipo de redimensionamento que o servidor diz que ela tem. */
export function resizeStep(box: PlacedBox, handle: Handle, dx: number, dy: number, snap: SnapSettings | null, frame: FrameSize): GestureStep {
  if (box.resize === 'text_width') return resizeWrap(box, handle, dx, snap)
  if (box.resize === 'keep_aspect') return resizeCorner(box, handle, dx, dy, snap, frame)
  if (box.resize === 'free') return resizeFree(box, handle, dx, dy, snap)
  return { box, guides: { x: null, y: null } }
}

/* ---------- a zona segura durante o gesto ---------- */

/**
 * Os lados da zona segura que a caixa invade, com 1 px de folga: a mesma conta do servidor (`sides_outside_safe_zone`),
 * refeita aqui porque o `outside_safe_zone` que veio com as caixas fica velho enquanto a caixa anda. A HTML que ocupa o
 * quadro inteiro não confere a zona segura (o que ela desenha dentro é decisão dela), como no servidor.
 */
export function sidesOutside(box: PlacedBox, zone: SafeZoneFractions, frame: FrameSize): SafeZoneSide[] {
  const slackX = 1 / frame.width
  const slackY = 1 / frame.height
  if (box.kind === 'html' && box.width >= 1 - slackX && box.height >= 1 - slackY) return []
  const sides: SafeZoneSide[] = []
  if (box.top < zone.top - slackY) sides.push('top')
  if (box.top + box.height > 1 - zone.bottom + slackY) sides.push('bottom')
  if (box.left < zone.left - slackX) sides.push('left')
  if (box.left + box.width > 1 - zone.right + slackX) sides.push('right')
  return sides
}

/* ---------- o que o gesto grava na spec ---------- */

/** O que mudar em uma sobreposição da spec: campos a escrever (caminho com ponto, relativo a ela) e campos a tirar. */
export interface OverlayPatch {
  set: Record<string, unknown>
  unset: string[]
}

type Loose = Record<string, unknown>

/** Uma fração de posição: com 4 casas (menos de 0,2 px num quadro de 1920) e dentro do quadro, como a spec exige. */
const position = (value: number) => clamp(round4(value), 0, 1)
/** Uma fração de tamanho: com 4 casas e em (0, 1]. */
const extent = (value: number) => clamp(round4(value), 0.0001, 1)

const centerOf = (box: PlacedBox) => ({ x: box.left + box.width / 2, y: box.top + box.height / 2 })

/** O que a região deixa de dar quando a sobreposição sai dela: sem isso, tirar o `region` mudaria o que se vê. O texto
 * em região é centralizado na largura dela e a imagem e o PiP cabem nela; o servidor já deu a caixa resultante. */
function regionFields(original: PlacedBox, overlay: Loose, frame: FrameSize): Loose {
  if (original.kind === 'text') {
    return { 'style.align': textAlignOf(original), ...(original.wrap ? { 'style.max_width': extent(original.wrap.width) } : {}) }
  }
  if (original.kind === 'image') return { width: extent(original.width) }
  if (original.kind === 'video') {
    const fields: Loose = { width: extent(original.width) }
    // sem `aspect` o PiP em região preenche a região cortando o excesso: a proporção dela precisa ir para a spec
    if (overlay.aspect === undefined && overlay.shape !== 'circle') {
      fields.aspect = `${Math.round(original.width * frame.width)}:${Math.round(original.height * frame.height)}`
    }
    return fields
  }
  return {}
}

/** `position` e `region` saem quando `x`/`y` passam a mandar. O PiP com `slide` guarda a posição: é dela que vem a
 * direção de onde ele entra. */
function released(original: PlacedBox, overlay: Loose): string[] {
  const names = ['region']
  if (original.kind === 'video' && overlay.animation === 'slide') return names
  return [...names, 'position']
}

/**
 * Os campos que o gesto grava: `original` é a caixa antes do gesto e `final` a que o gesto deixou. Mover é somar o
 * deslocamento à âncora (decisão 4); redimensionar muda `style.max_width` no texto (5) e a largura, com o centro, na
 * imagem e no PiP (6); a HTML sempre leva `x`, `y`, `width` e `height` juntos, porque só `x`/`y` a devolveria ao
 * quadro todo. A primeira vez que a sobreposição sai da região, a região deixa de dar o lugar e o que ela dava
 * (largura da quebra, tamanho) passa para a spec (7).
 */
export function gesturePatch(mode: 'move' | 'resize', original: PlacedBox, final: PlacedBox, overlay: Loose, frame: FrameSize): OverlayPatch {
  const set: Loose = {}
  const fromRegion = original.placement === 'region'
  if (fromRegion) Object.assign(set, regionFields(original, overlay, frame))
  if (original.kind === 'text') {
    if (mode === 'move' || fromRegion) {
      const anchor = anchorOf(mode === 'move' ? final : original)
      set.x = position(anchor.x)
      set.y = position(anchor.y)
    }
    if (mode === 'resize' && final.wrap) set['style.max_width'] = extent(final.wrap.width)
    return { set, unset: mode === 'move' || fromRegion ? ['position', 'region'] : [] }
  }
  // mover soma o deslocamento à âncora do servidor (sem a deriva do arredondamento do canto); redimensionar muda a
  // caixa, e o centro novo é o dela
  const point = mode === 'move' ? anchorOf(final) : centerOf(final)
  set.x = position(point.x)
  set.y = position(point.y)
  if (original.kind === 'html') {
    // mover não muda o tamanho: o valor que a spec já tem (0,12) vale mais que o da caixa, que vem arredondado em px.
    // Só vale quando concorda com a caixa: sem `width`/`height` explícitos a spec traz o padrão (1), e a área real é a
    // do esquema do infográfico, que é a da caixa
    const kept = (value: unknown, boxed: number, pixels: number) =>
      mode === 'move' && !fromRegion && typeof value === 'number' && Math.abs(value - boxed) * pixels <= 1 ? value : extent(boxed)
    set.width = kept(overlay.width, final.width, frame.width)
    set.height = kept(overlay.height, final.height, frame.height)
  } else if (mode === 'resize') {
    set.width = extent(final.width)
  }
  return { set, unset: released(original, overlay) }
}

/** Escreve o patch na sobreposição (que o `mutate` do store entrega editável). */
export function applyPatch(overlay: Loose, patch: OverlayPatch): void {
  for (const [path, value] of Object.entries(patch.set)) {
    const parts = path.split('.')
    let holder = overlay
    for (const part of parts.slice(0, -1)) {
      if (holder[part] === null || typeof holder[part] !== 'object') holder[part] = {}
      holder = holder[part] as Loose
    }
    holder[parts[parts.length - 1] as string] = value
  }
  for (const name of patch.unset) delete overlay[name]
}
