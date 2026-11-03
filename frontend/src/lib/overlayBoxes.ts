/* As caixas das sobreposições no palco: quais estão ativas num instante, onde caem no quadro e como se chamam.
   Puro. O lugar de cada caixa vem pronto do servidor (`POST /boxes`, a mesma conta do render e do QA da zona
   segura); aqui só se escolhe o que mostrar e se traduz a fração do quadro em estilo CSS. */
import type {
  BoxKind,
  BoxLayout,
  OverlayBox,
  SafeZoneFractions,
  SafeZoneSide,
  TimelineItem,
  TimelineTrack,
  TimelineView,
} from '@/api'

type CssStyle = Record<string, string>

/** Como cada tipo de caixa se chama no rótulo curto sobre o palco. */
export const BOX_KIND_LABEL: Record<BoxKind, string> = {
  text: 'Texto',
  image: 'Imagem',
  video: 'PiP',
  html: 'HTML',
  'progress-bar': 'Barra',
  audiogram: 'Audiograma',
}

/** Os lados da zona segura, para frases como "saiu da zona segura embaixo". */
export const SIDE_LABEL: Record<SafeZoneSide, string> = {
  top: 'em cima',
  bottom: 'embaixo',
  left: 'à esquerda',
  right: 'à direita',
}

/** Uma caixa que tem área calculada (as da HTML presa a palavra e as de mídia sumida não têm). */
export type PlacedBox = OverlayBox & { left: number; top: number; width: number; height: number }

export function hasArea(box: OverlayBox): box is PlacedBox {
  return box.left !== null && box.top !== null && box.width !== null && box.height !== null
}

/** A caixa de uma sobreposição pelo índice dela na spec, só quando tem área para desenhar. Com `kind`, só se for do
 * tipo esperado: as caixas chegam um pouco depois da spec, e uma caixa de antes da troca de tipo não vale. */
export function placedBoxOf(layout: BoxLayout | null, index: number, kind?: BoxKind): PlacedBox | null {
  const box = layout?.boxes.find((candidate) => candidate.index === index)
  return box && hasArea(box) && (kind === undefined || box.kind === kind) ? box : null
}

/** Como o texto se alinha, lido da âncora que o servidor calculou (o `align` da spec pode vir do papel): no centro
 * da caixa é centralizado, antes dele é alinhado à esquerda e depois, à direita. A caixa de fundo tem folga nas
 * pontas, por isso a âncora do alinhado à esquerda fica um pouco dentro da borda e não colada nela. */
export function textAlignOf(box: PlacedBox): 'left' | 'center' | 'right' {
  if (!box.anchor) return 'center'
  const offset = box.anchor.x - (box.left + box.width / 2)
  if (Math.abs(offset) <= 0.002) return 'center'
  return offset < 0 ? 'left' : 'right'
}

/** O rótulo curto de uma caixa: o tipo e o número da sobreposição, o mesmo do cartão no inspetor ("Texto 2"). */
export function boxLabel(box: OverlayBox): string {
  return `${BOX_KIND_LABEL[box.kind] ?? box.kind} ${box.index + 1}`
}

/** A sobreposição está na tela neste instante (sem `end`, vale até o fim do vídeo). */
export function boxActiveAt(box: OverlayBox, t: number, total: number): boolean {
  return t >= box.start && t < (box.end ?? total)
}

/** O tamanho e o lugar de um retângulo (a caixa, ou a área da quebra do texto) em % do palco, que tem a mesma
 * proporção do quadro. */
export function boxRectStyle(box: Pick<PlacedBox, 'left' | 'top' | 'width' | 'height'>): CssStyle {
  return {
    left: `${(box.left * 100).toFixed(4)}%`,
    top: `${(box.top * 100).toFixed(4)}%`,
    width: `${(box.width * 100).toFixed(4)}%`,
    height: `${(box.height * 100).toFixed(4)}%`,
  }
}

/** A trilha é de sobreposição (PiP, texto ou gráficos), e não do trecho principal, do áudio ou das legendas. */
export function isOverlayTrack(track: TimelineTrack): boolean {
  return track.id === 'TX' || track.id === 'GR' || (track.kind === 'video' && track.id !== 'V1')
}

export interface OverlayItemRef {
  trackId: string
  item: TimelineItem
  hidden: boolean
}

/** O item da linha do tempo de uma sobreposição (pelo índice dela na spec) e se a trilha está oculta. */
export function overlayItemOf(view: TimelineView | null, index: number): OverlayItemRef | null {
  for (const track of view?.tracks ?? []) {
    if (!isOverlayTrack(track)) continue
    const item = track.items.find((candidate) => candidate.index === index)
    if (item) return { trackId: track.id, item, hidden: track.hidden }
  }
  return null
}

/** Uma caixa a desenhar no palco: a do servidor, o item da linha do tempo e o rótulo. */
export interface StageBox {
  box: PlacedBox
  itemId: string
  trackId: string
  label: string
}

/** As caixas ativas em `t`, na ordem da spec (a de cima é a última). Sobreposição de trilha oculta não vai ao render,
 * então não ganha caixa; a sem área calculada também não. */
export function stageBoxes(t: number, view: TimelineView | null, layout: BoxLayout | null): StageBox[] {
  if (!view || !layout) return []
  const result: StageBox[] = []
  for (const box of layout.boxes) {
    if (!hasArea(box) || !boxActiveAt(box, t, view.total)) continue
    const ref = overlayItemOf(view, box.index)
    if (!ref || ref.hidden) continue
    result.push({ box, itemId: ref.item.id, trackId: ref.trackId, label: boxLabel(box) })
  }
  return result
}

/** Cada margem da zona segura em % do palco: quatro faixas a escurecer e o retângulo de dentro. */
export interface SafeZoneStyles {
  top: CssStyle
  bottom: CssStyle
  left: CssStyle
  right: CssStyle
  inside: CssStyle
}

export function safeZoneStyles(zone: SafeZoneFractions): SafeZoneStyles {
  const pct = (value: number) => `${(value * 100).toFixed(4)}%`
  return {
    top: { top: '0', left: '0', right: '0', height: pct(zone.top) },
    bottom: { bottom: '0', left: '0', right: '0', height: pct(zone.bottom) },
    // as laterais ficam entre as faixas de cima e de baixo, para o canto não escurecer duas vezes
    left: { top: pct(zone.top), bottom: pct(zone.bottom), left: '0', width: pct(zone.left) },
    right: { top: pct(zone.top), bottom: pct(zone.bottom), right: '0', width: pct(zone.right) },
    inside: {
      top: pct(zone.top),
      bottom: pct(zone.bottom),
      left: pct(zone.left),
      right: pct(zone.right),
    },
  }
}

/** "em cima", "embaixo e à esquerda", "em cima, à esquerda e à direita": os lados por extenso, na ordem do quadro. */
export function sidesText(sides: readonly SafeZoneSide[]): string {
  const order: SafeZoneSide[] = ['top', 'bottom', 'left', 'right']
  const names = order.filter((side) => sides.includes(side)).map((side) => SIDE_LABEL[side])
  if (names.length <= 1) return names[0] ?? ''
  return `${names.slice(0, -1).join(', ')} e ${names[names.length - 1]}`
}
