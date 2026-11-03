import { describe, expect, it } from 'vitest'
import type { TimelineView } from '@/api'
import { boxLayout, overlayBox, timelineItem, timelineTrack, timelineView } from '@/test/editorFixtures'
import {
  boxActiveAt,
  boxLabel,
  boxRectStyle,
  hasArea,
  isOverlayTrack,
  overlayItemOf,
  placedBoxOf,
  safeZoneStyles,
  sidesText,
  stageBoxes,
  textAlignOf,
  type PlacedBox,
} from './overlayBoxes'

const placed = (extra: Parameters<typeof overlayBox>[0] = {}) => overlayBox(extra) as PlacedBox

/** Uma vista com um texto (TX), uma imagem (GR) e um PiP (V2) cujos índices na spec são 0, 1 e 2. */
function overlayView(extra: Partial<TimelineView> = {}): TimelineView {
  return {
    ...timelineView(),
    total: 12,
    tracks: [
      timelineTrack('V2', [timelineItem(2, { id: 'V2-2', kind: 'video', start: 0, end: 12 })]),
      timelineTrack('TX', [timelineItem(0, { id: 'TX-0', kind: 'text', start: 0, end: 12 })], { kind: 'text' }),
      timelineTrack('GR', [timelineItem(1, { id: 'GR-1', kind: 'image', start: 0, end: 12 })], { kind: 'graphics' }),
      timelineTrack('V1', [timelineItem(0, { id: 'V1-0' }), timelineItem(1, { id: 'V1-1' })]),
    ],
    ...extra,
  }
}

describe('geometria da caixa', () => {
  it('só tem área quando as quatro medidas vieram', () => {
    expect(hasArea(overlayBox())).toBe(true)
    expect(hasArea(overlayBox({ left: null, top: null, width: null, height: null }))).toBe(false)
    expect(hasArea(overlayBox({ width: null }))).toBe(false)
  })

  it('a caixa do índice pedido, só com área e, se dito, só do tipo esperado', () => {
    const layout = boxLayout([overlayBox({ index: 0 }), overlayBox({ index: 1, kind: 'image' }), overlayBox({ index: 2, left: null, top: null, width: null, height: null })])
    expect(placedBoxOf(layout, 1)?.kind).toBe('image')
    expect(placedBoxOf(layout, 1, 'image')?.index).toBe(1)
    // uma caixa de antes da troca de tipo não vale para o tipo novo
    expect(placedBoxOf(layout, 1, 'video')).toBeNull()
    expect(placedBoxOf(layout, 2)).toBeNull()
    expect(placedBoxOf(layout, 9)).toBeNull()
    expect(placedBoxOf(null, 0)).toBeNull()
  })

  it('o estilo da caixa é o retângulo em % do palco', () => {
    expect(boxRectStyle(placed({ left: 0.1, top: 0.2, width: 0.8, height: 0.07 }))).toEqual({
      left: '10.0000%',
      top: '20.0000%',
      width: '80.0000%',
      height: '7.0000%',
    })
  })

  it('o texto se alinha pela âncora que o servidor calculou: antes do meio da caixa, no meio ou depois dele', () => {
    expect(textAlignOf(placed({ left: 0.1, width: 0.4, anchor: { x: 0.1, y: 0.2 } }))).toBe('left')
    // a caixa de fundo tem folga: a âncora do texto à esquerda fica dentro da borda, e não colada nela
    expect(textAlignOf(placed({ left: 0.1, width: 0.4, anchor: { x: 0.12, y: 0.2 } }))).toBe('left')
    expect(textAlignOf(placed({ left: 0.1, width: 0.4, anchor: { x: 0.48, y: 0.2 } }))).toBe('right')
    expect(textAlignOf(placed({ left: 0.1, width: 0.4, anchor: { x: 0.5, y: 0.2 } }))).toBe('right')
    expect(textAlignOf(placed({ left: 0.1, width: 0.4, anchor: { x: 0.3, y: 0.2 } }))).toBe('center')
    expect(textAlignOf(placed({ anchor: null }))).toBe('center')
  })
})

describe('rótulo e instante', () => {
  it('o rótulo é o tipo e o número da sobreposição, o mesmo do cartão', () => {
    expect(boxLabel(overlayBox({ index: 0, kind: 'text' }))).toBe('Texto 1')
    expect(boxLabel(overlayBox({ index: 2, kind: 'video' }))).toBe('PiP 3')
    expect(boxLabel(overlayBox({ index: 4, kind: 'html' }))).toBe('HTML 5')
    expect(boxLabel(overlayBox({ index: 1, kind: 'progress-bar' }))).toBe('Barra 2')
  })

  it('está ativa de `start` até `end`, e sem `end` até o fim do vídeo', () => {
    const box = overlayBox({ start: 2, end: 6 })
    expect(boxActiveAt(box, 1.9, 12)).toBe(false)
    expect(boxActiveAt(box, 2, 12)).toBe(true)
    expect(boxActiveAt(box, 5.99, 12)).toBe(true)
    expect(boxActiveAt(box, 6, 12)).toBe(false)
    const toTheEnd = overlayBox({ start: 2, end: null })
    expect(boxActiveAt(toTheEnd, 11.9, 12)).toBe(true)
    expect(boxActiveAt(toTheEnd, 12, 12)).toBe(false)
  })
})

describe('a sobreposição na linha do tempo', () => {
  it('trilhas de sobreposição são TX, GR e os vídeos acima da V1', () => {
    const tracks = overlayView().tracks
    expect(tracks.filter(isOverlayTrack).map((track) => track.id)).toEqual(['V2', 'TX', 'GR'])
    expect(isOverlayTrack(timelineTrack('A1', [], { kind: 'audio' }))).toBe(false)
  })

  it('acha o item pelo índice na spec, sem confundir com o trecho da V1 de mesmo número', () => {
    const view = overlayView()
    expect(overlayItemOf(view, 0)).toMatchObject({ trackId: 'TX', hidden: false })
    expect(overlayItemOf(view, 0)?.item.id).toBe('TX-0')
    expect(overlayItemOf(view, 2)?.trackId).toBe('V2')
    expect(overlayItemOf(view, 7)).toBeNull()
    expect(overlayItemOf(null, 0)).toBeNull()
  })
})

describe('as caixas do palco num instante', () => {
  const layout = boxLayout([
    overlayBox({ index: 0, kind: 'text', start: 0, end: 4 }),
    overlayBox({ index: 1, kind: 'image', start: 2, end: null, left: 0.7, top: 0.05, width: 0.2, height: 0.1 }),
    overlayBox({ index: 2, kind: 'video', start: 0, end: null }),
  ])

  it('só as ativas, na ordem da spec', () => {
    expect(stageBoxes(1, overlayView(), layout).map((entry) => entry.label)).toEqual(['Texto 1', 'PiP 3'])
    expect(stageBoxes(3, overlayView(), layout).map((entry) => entry.label)).toEqual(['Texto 1', 'Imagem 2', 'PiP 3'])
    expect(stageBoxes(5, overlayView(), layout).map((entry) => entry.label)).toEqual(['Imagem 2', 'PiP 3'])
  })

  it('cada caixa leva o item e a trilha dela', () => {
    const [text] = stageBoxes(1, overlayView(), layout)
    expect(text).toMatchObject({ itemId: 'TX-0', trackId: 'TX', label: 'Texto 1' })
  })

  it('trilha oculta não vai ao render e por isso não ganha caixa', () => {
    const hidden = overlayView()
    hidden.tracks = hidden.tracks.map((track) => (track.id === 'TX' ? { ...track, hidden: true } : track))
    expect(stageBoxes(1, hidden, layout).map((entry) => entry.label)).toEqual(['PiP 3'])
  })

  it('sem área (HTML presa a palavra) ou sem item na vista, não há o que desenhar', () => {
    const noArea = boxLayout([overlayBox({ index: 0, left: null, top: null, width: null, height: null, movable: false })])
    expect(stageBoxes(1, overlayView(), noArea)).toEqual([])
    const unknown = boxLayout([overlayBox({ index: 9 })])
    expect(stageBoxes(1, overlayView(), unknown)).toEqual([])
    expect(stageBoxes(1, null, layout)).toEqual([])
    expect(stageBoxes(1, overlayView(), null)).toEqual([])
  })
})

describe('zona segura', () => {
  it('quatro faixas e o retângulo livre, em % do quadro', () => {
    const styles = safeZoneStyles({ top: 0.115, bottom: 0.219, left: 0.056, right: 0.139 })
    expect(styles.top).toEqual({ top: '0', left: '0', right: '0', height: '11.5000%' })
    expect(styles.bottom).toEqual({ bottom: '0', left: '0', right: '0', height: '21.9000%' })
    // as laterais ficam entre as faixas de cima e de baixo
    expect(styles.left).toEqual({ top: '11.5000%', bottom: '21.9000%', left: '0', width: '5.6000%' })
    expect(styles.right).toEqual({ top: '11.5000%', bottom: '21.9000%', right: '0', width: '13.9000%' })
    expect(styles.inside).toEqual({ top: '11.5000%', bottom: '21.9000%', left: '5.6000%', right: '13.9000%' })
  })

  it('os lados saem por extenso, na ordem do quadro', () => {
    expect(sidesText([])).toBe('')
    expect(sidesText(['bottom'])).toBe('embaixo')
    expect(sidesText(['left', 'top'])).toBe('em cima e à esquerda')
    expect(sidesText(['right', 'bottom', 'top'])).toBe('em cima, embaixo e à direita')
  })
})
