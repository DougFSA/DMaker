import { describe, expect, it } from 'vitest'
import { overlayBox } from '@/test/editorFixtures'
import {
  applyPatch,
  gesturePatch,
  handleFrame,
  handlesOf,
  moveStep,
  resizeStep,
  sidesOutside,
  snapLines,
  snapPoints,
  snapSettings,
  type FrameSize,
  type SnapSettings,
} from './overlayGesture'
import type { PlacedBox } from './overlayBoxes'

const FRAME: FrameSize = { width: 1080, height: 1920 }
const ZONE = { top: 0.115, bottom: 0.219, left: 0.056, right: 0.139 }
// um palco de 270 x 480 px na tela: 8 px de ímã são 0,0296 do quadro na largura e 0,0167 na altura
const SNAP: SnapSettings = snapSettings(ZONE, { width: 270, height: 480 })

function placed(extra: Parameters<typeof overlayBox>[0] = {}): PlacedBox {
  return overlayBox(extra) as PlacedBox
}

/** Um texto centralizado: a âncora no meio do bloco, e a quebra simétrica em torno dela. */
const centeredText = (extra: Parameters<typeof overlayBox>[0] = {}) =>
  placed({ left: 0.3, top: 0.4, width: 0.4, height: 0.05, anchor: { x: 0.5, y: 0.425 }, wrap: { left: 0.1, width: 0.8 }, ...extra })
/** Alinhado à esquerda: a âncora é a borda do texto, antes do meio do bloco. */
const leftText = (extra: Parameters<typeof overlayBox>[0] = {}) =>
  placed({ left: 0.1, top: 0.7, width: 0.5, height: 0.06, anchor: { x: 0.12, y: 0.73 }, wrap: { left: 0.1, width: 0.7 }, ...extra })
const rightText = (extra: Parameters<typeof overlayBox>[0] = {}) =>
  placed({ left: 0.4, top: 0.7, width: 0.5, height: 0.06, anchor: { x: 0.88, y: 0.73 }, wrap: { left: 0.2, width: 0.7 }, ...extra })
const image = (extra: Parameters<typeof overlayBox>[0] = {}) =>
  placed({ index: 1, kind: 'image', left: 0.4, top: 0.4, width: 0.2, height: 0.1, anchor: { x: 0.5, y: 0.45 }, resize: 'keep_aspect', wrap: null, ...extra })
const html = (extra: Parameters<typeof overlayBox>[0] = {}) =>
  placed({ index: 3, kind: 'html', left: 0.2, top: 0.3, width: 0.6, height: 0.3, anchor: { x: 0.5, y: 0.45 }, resize: 'free', wrap: null, ...extra })

describe('o ímã', () => {
  it('puxa para o centro do quadro, as bordas e as margens da zona segura, nos dois eixos', () => {
    expect(snapLines(ZONE)).toEqual({ x: [0, 0.056, 0.5, 1 - 0.139, 1], y: [0, 0.115, 0.5, 1 - 0.219, 1] })
  })

  it('a tolerância são 8 px de tela, em fração do palco', () => {
    expect(SNAP.tolerance.x).toBeCloseTo(8 / 270, 9)
    expect(SNAP.tolerance.y).toBeCloseTo(8 / 480, 9)
  })

  it('escolhe o par ponto-linha mais próximo dentro da tolerância, e não puxa nada além dela', () => {
    expect(snapPoints([0.48, 0.2], [0.5], 0.03)).toEqual({ offset: expect.closeTo(0.02, 9), line: 0.5 })
    expect(snapPoints([0.46], [0.5], 0.03)).toEqual({ offset: 0, line: null })
    expect(snapPoints([0.2, 0.495], [0, 0.5], 0.03).line).toBe(0.5)
  })
})

describe('as alças de cada caixa', () => {
  it('o texto segue a âncora: as duas bordas no centralizado, a direita no alinhado à esquerda, a esquerda no à direita', () => {
    expect(handlesOf(centeredText())).toEqual(['w', 'e'])
    expect(handlesOf(leftText())).toEqual(['e'])
    expect(handlesOf(rightText())).toEqual(['w'])
  })

  it('imagem e PiP têm os quatro cantos, a HTML tem bordas e cantos', () => {
    expect(handlesOf(image())).toEqual(['nw', 'ne', 'sw', 'se'])
    expect(handlesOf(placed({ kind: 'video', resize: 'keep_aspect' }))).toHaveLength(4)
    expect(handlesOf(html())).toHaveLength(8)
  })

  it('a caixa travada ou sem redimensionamento não tem alça', () => {
    expect(handlesOf(html({ movable: false, locked_reason: 'Presa à palavra.' }))).toEqual([])
    expect(handlesOf(placed({ kind: 'progress-bar', resize: 'none' }))).toEqual([])
  })

  it('as alças do texto ficam na quebra, e as dos outros tipos na própria caixa', () => {
    expect(handleFrame(centeredText())).toEqual({ left: 0.1, top: 0.4, width: 0.8, height: 0.05 })
    expect(handleFrame(image())).toEqual({ left: 0.4, top: 0.4, width: 0.2, height: 0.1 })
  })
})

describe('mover', () => {
  it('soma o deslocamento à caixa, à âncora e à quebra', () => {
    const { box, guides } = moveStep(centeredText(), 0.1, -0.05, null)
    expect(box.left).toBeCloseTo(0.4, 9)
    expect(box.top).toBeCloseTo(0.35, 9)
    expect(box.anchor).toEqual({ x: expect.closeTo(0.6, 9), y: expect.closeTo(0.375, 9) })
    expect(box.wrap?.left).toBeCloseTo(0.2, 9)
    expect(box.wrap?.width).toBe(0.8)
    expect(guides).toEqual({ x: null, y: null })
  })

  it('o centro da caixa é puxado para o centro do quadro, e a guia mostra a linha', () => {
    // o bloco está a 0,015 do centro em x: dentro dos 8 px
    const { box, guides } = moveStep(centeredText({ left: 0.315, anchor: { x: 0.515, y: 0.425 } }), 0, 0, SNAP)
    expect(box.left + box.width / 2).toBeCloseTo(0.5, 9)
    expect(guides.x).toBe(0.5)
    expect(guides.y).toBeNull()
  })

  it('a borda de cima da caixa é puxada para a margem da zona segura', () => {
    const { box, guides } = moveStep(image({ top: 0.12 }), 0, 0, SNAP)
    expect(box.top).toBeCloseTo(0.115, 9)
    expect(guides.y).toBe(0.115)
  })

  it('a borda de baixo é puxada para a margem de baixo da zona segura', () => {
    const { box } = moveStep(image({ top: 0.69, height: 0.1 }), 0, 0, SNAP)
    expect(box.top + box.height).toBeCloseTo(1 - 0.219, 9)
  })

  it('além dos 8 px o ímã não puxa, e sem ímã (Alt) a caixa vai exatamente onde o mouse a levou', () => {
    const far = centeredText({ left: 0.34, anchor: { x: 0.54, y: 0.425 } })
    expect(moveStep(far, 0, 0, SNAP).guides).toEqual({ x: null, y: null })
    const near = centeredText({ left: 0.315, anchor: { x: 0.515, y: 0.425 } })
    const free = moveStep(near, 0, 0, null)
    expect(free.box.left).toBe(0.315)
    expect(free.guides.x).toBeNull()
  })

  it('a âncora fica dentro do quadro: x e y da spec nunca passam de 0 a 1', () => {
    const { box, guides } = moveStep(leftText(), -0.5, 0.9, SNAP)
    expect(box.anchor?.x).toBeCloseTo(0, 9)
    expect(box.anchor?.y).toBeCloseTo(1, 9)
    expect(guides.x).toBeNull()
    expect(guides.y).toBeNull()
  })
})

describe('redimensionar o texto', () => {
  it('no centralizado as duas bordas andam juntas, simétricas em torno da âncora', () => {
    const east = resizeStep(centeredText(), 'e', 0.1, 0, null, FRAME).box
    expect(east.wrap?.width).toBeCloseTo(1, 9)
    expect(east.wrap?.left).toBeCloseTo(0, 9)
    const west = resizeStep(centeredText(), 'w', 0.1, 0, null, FRAME).box
    // a borda esquerda andou para dentro, então a quebra encolhe dos dois lados
    expect(west.wrap?.width).toBeCloseTo(0.6, 9)
    expect(west.wrap?.left).toBeCloseTo(0.2, 9)
  })

  it('no alinhado à esquerda só a borda direita anda, e a esquerda fica parada', () => {
    const { box } = resizeStep(leftText(), 'e', 0.1, 0, null, FRAME)
    expect(box.wrap).toEqual({ left: 0.1, width: expect.closeTo(0.8, 9) })
  })

  it('no alinhado à direita só a borda esquerda anda, e a direita fica parada', () => {
    const { box } = resizeStep(rightText(), 'w', -0.1, 0, null, FRAME)
    expect(box.wrap?.width).toBeCloseTo(0.8, 9)
    expect(box.wrap!.left + box.wrap!.width).toBeCloseTo(0.9, 9)
  })

  it('a quebra tem um mínimo e cabe no quadro', () => {
    expect(resizeStep(leftText(), 'e', -0.9, 0, null, FRAME).box.wrap?.width).toBe(0.1)
    expect(resizeStep(leftText(), 'e', 2, 0, null, FRAME).box.wrap?.width).toBe(1)
  })

  it('a borda puxada é segurada pelo ímã numa margem da zona segura', () => {
    // a borda direita da quebra (0,8) a 0,06 da margem direita: +0,04 a leva para 0,84, a 0,021 da linha em 0,861
    const { box, guides } = resizeStep(leftText(), 'e', 0.04, 0, SNAP, FRAME)
    expect(box.wrap!.left + box.wrap!.width).toBeCloseTo(1 - 0.139, 9)
    expect(guides.x).toBeCloseTo(1 - 0.139, 9)
  })

  it('a caixa do texto não muda durante o gesto: só o servidor sabe como o texto vai quebrar', () => {
    const before = centeredText()
    const after = resizeStep(before, 'e', 0.1, 0, null, FRAME).box
    expect([after.left, after.top, after.width, after.height]).toEqual([before.left, before.top, before.width, before.height])
  })
})

describe('redimensionar imagem e PiP pelo canto', () => {
  const ratio = (box: PlacedBox) => (box.width * FRAME.width) / (box.height * FRAME.height)

  it('o canto oposto fica parado e o aspecto se mantém', () => {
    const start = image()
    const { box } = resizeStep(start, 'se', 0.1, 0.1 * (FRAME.width / FRAME.height), null, FRAME)
    expect(box.left).toBeCloseTo(0.4, 9)
    expect(box.top).toBeCloseTo(0.4, 9)
    expect(box.width).toBeGreaterThan(0.2)
    expect(ratio(box)).toBeCloseTo(ratio(start), 9)
  })

  it('puxar o canto de cima à esquerda mantém o de baixo à direita no lugar', () => {
    const start = image()
    const { box } = resizeStep(start, 'nw', -0.1, -0.05, null, FRAME)
    expect(box.left + box.width).toBeCloseTo(0.6, 9)
    expect(box.top + box.height).toBeCloseTo(0.5, 9)
    expect(box.width).toBeGreaterThan(0.2)
    expect(ratio(box)).toBeCloseTo(ratio(start), 9)
  })

  it('o fator é a projeção do ponteiro na diagonal: andar só na horizontal também muda o tamanho', () => {
    const { box } = resizeStep(image(), 'se', 0.1, 0, null, FRAME)
    expect(box.width).toBeGreaterThan(0.2)
    expect(box.width).toBeLessThan(0.3)
  })

  it('tem tamanho mínimo e a largura não passa do quadro todo', () => {
    expect(resizeStep(image(), 'se', -0.9, -0.9, null, FRAME).box.width).toBeCloseTo(0.05, 9)
    expect(resizeStep(image({ left: 0, anchor: { x: 0.1, y: 0.45 } }), 'se', 5, 5, null, FRAME).box.width).toBeLessThanOrEqual(1)
  })

  it('o centro não passa da borda do quadro: x e y da spec ficam entre 0 e 1', () => {
    const { box } = resizeStep(image({ left: 0.7, anchor: { x: 0.8, y: 0.45 } }), 'se', 0.9, 0.9, null, FRAME)
    expect(box.left + box.width / 2).toBeLessThanOrEqual(1 + 1e-9)
  })

  it('o canto puxado é segurado por uma linha do ímã', () => {
    // largura 0,2, canto de baixo à direita em x = 0,6: a 0,0267 da linha do centro? não, a linha mais perto é 0,861
    const start = image({ left: 0.6, top: 0.4, anchor: { x: 0.7, y: 0.45 } })
    const { box, guides } = resizeStep(start, 'se', 0.05, 0.05 * (FRAME.width / FRAME.height) * 0.5, SNAP, FRAME)
    expect(box.left + box.width).toBeCloseTo(1 - 0.139, 9)
    expect(guides.x).toBeCloseTo(1 - 0.139, 9)
    expect(ratio(box)).toBeCloseTo(ratio(start), 9)
  })
})

describe('redimensionar a HTML por bordas e cantos', () => {
  it('a borda do meio muda um eixo só, com a oposta parada', () => {
    const { box } = resizeStep(html(), 'e', 0.1, 0.3, null, FRAME)
    expect(box.left).toBeCloseTo(0.2, 9)
    expect(box.width).toBeCloseTo(0.7, 9)
    expect(box.top).toBeCloseTo(0.3, 9)
    expect(box.height).toBeCloseTo(0.3, 9)
  })

  it('o canto muda os dois eixos, com o canto oposto parado', () => {
    const { box } = resizeStep(html(), 'nw', 0.05, 0.1, null, FRAME)
    expect(box.left).toBeCloseTo(0.25, 9)
    expect(box.top).toBeCloseTo(0.4, 9)
    expect(box.left + box.width).toBeCloseTo(0.8, 9)
    expect(box.top + box.height).toBeCloseTo(0.6, 9)
  })

  it('largura e altura têm mínimo e cabem no quadro', () => {
    expect(resizeStep(html(), 'e', -2, 0, null, FRAME).box.width).toBeCloseTo(0.05, 9)
    expect(resizeStep(html({ left: 0, anchor: { x: 0.3, y: 0.45 } }), 'e', 5, 0, null, FRAME).box.width).toBeLessThanOrEqual(1)
    expect(resizeStep(html(), 's', 0, -3, null, FRAME).box.height).toBeCloseTo(0.05, 9)
  })

  it('cada borda puxada tem o seu ímã', () => {
    // a borda de cima (0,3) vai para 0,12, a 0,005 da margem de cima (0,115)
    const { box, guides } = resizeStep(html(), 'n', 0, -0.18, SNAP, FRAME)
    expect(box.top).toBeCloseTo(0.115, 9)
    expect(guides.y).toBe(0.115)
  })
})

describe('a zona segura durante o gesto', () => {
  it('diz os lados que a caixa invade, com 1 px de folga', () => {
    expect(sidesOutside(image({ top: 0.1 }), ZONE, FRAME)).toEqual(['top'])
    expect(sidesOutside(image({ top: 0.75 }), ZONE, FRAME)).toEqual(['bottom'])
    expect(sidesOutside(image({ left: 0.01, top: 0.4 }), ZONE, FRAME)).toEqual(['left'])
    expect(sidesOutside(image({ left: 0.75, top: 0.4 }), ZONE, FRAME)).toEqual(['right'])
    expect(sidesOutside(image({ left: 0.3, top: 0.4 }), ZONE, FRAME)).toEqual([])
  })

  it('encostar exatamente na margem não é invadir', () => {
    expect(sidesOutside(image({ top: 0.115 }), ZONE, FRAME)).toEqual([])
    // 1 px de folga: 0,5 px acima da margem ainda passa
    expect(sidesOutside(image({ top: 0.115 - 0.5 / 1920 }), ZONE, FRAME)).toEqual([])
    expect(sidesOutside(image({ top: 0.115 - 2 / 1920 }), ZONE, FRAME)).toEqual(['top'])
  })

  it('a HTML que ocupa o quadro todo não confere a zona segura', () => {
    expect(sidesOutside(html({ left: 0, top: 0, width: 1, height: 1 }), ZONE, FRAME)).toEqual([])
    expect(sidesOutside(image({ left: 0, top: 0, width: 1, height: 1 }), ZONE, FRAME)).toEqual(['top', 'bottom', 'left', 'right'])
  })
})

describe('o que o gesto grava: mover', () => {
  it('o texto centralizado soma o deslocamento à âncora e tira a posição nomeada', () => {
    const start = centeredText({ placement: 'position' })
    const { box } = moveStep(start, 0.1, 0.2, null)
    const patch = gesturePatch('move', start, box, { type: 'text', position: 'center' }, FRAME)
    expect(patch.set).toEqual({ x: 0.6, y: 0.625 })
    expect(patch.unset).toEqual(['position', 'region'])
  })

  it('o texto alinhado à esquerda move a BORDA (a âncora), e não o centro do bloco', () => {
    const start = leftText()
    const { box } = moveStep(start, 0.1, 0, null)
    expect(gesturePatch('move', start, box, { type: 'text', style: { align: 'left' } }, FRAME).set).toEqual({ x: 0.22, y: 0.73 })
  })

  it('o texto em região vira texto com lugar próprio e leva a largura e o alinhamento que a região dava', () => {
    const start = centeredText({ placement: 'region', region: 'topo', anchor: { x: 0.5, y: 0.3 }, wrap: { left: 0.2, width: 0.6 } })
    const { box } = moveStep(start, 0.05, 0.05, null)
    const patch = gesturePatch('move', start, box, { type: 'text', region: 'topo' }, FRAME)
    expect(patch.set).toEqual({ 'style.align': 'center', 'style.max_width': 0.6, x: 0.55, y: 0.35 })
    expect(patch.unset).toContain('region')
  })

  it('a imagem grava o centro e tira a região e a posição nomeada, sem mexer na largura', () => {
    const start = image()
    const { box } = moveStep(start, 0.1, 0.1, null)
    const patch = gesturePatch('move', start, box, { type: 'image', position: 'top-right' }, FRAME)
    expect(patch.set).toEqual({ x: 0.6, y: 0.55 })
    expect(patch.unset).toEqual(['region', 'position'])
  })

  it('a imagem em região leva a largura que a região dava', () => {
    const start = image({ placement: 'region', region: 'lado', width: 0.31 })
    const { box } = moveStep(start, 0.1, 0, null)
    expect(gesturePatch('move', start, box, { type: 'image', region: 'lado' }, FRAME).set).toEqual({ width: 0.31, x: 0.6, y: 0.45 })
  })

  it('o PiP com slide guarda a posição (é dela que vem a direção), e sem slide ela sai', () => {
    const start = placed({ index: 2, kind: 'video', resize: 'keep_aspect', wrap: null, left: 0.5, top: 0.6, width: 0.4, height: 0.225, anchor: { x: 0.7, y: 0.7125 } })
    const { box } = moveStep(start, -0.1, 0, null)
    expect(gesturePatch('move', start, box, { type: 'video', animation: 'slide', position: 'bottom-right' }, FRAME).unset).toEqual(['region'])
    expect(gesturePatch('move', start, box, { type: 'video', animation: 'fade', position: 'bottom-right' }, FRAME).unset).toEqual(['region', 'position'])
  })

  it('o PiP em região sem proporção leva a proporção da região, para não mudar de forma ao sair dela', () => {
    const start = placed({ index: 2, kind: 'video', resize: 'keep_aspect', wrap: null, placement: 'region', region: 'cam', left: 0.1, top: 0.1, width: 0.5, height: 0.28125, anchor: { x: 0.35, y: 0.240625 } })
    const { box } = moveStep(start, 0.1, 0, null)
    const patch = gesturePatch('move', start, box, { type: 'video', region: 'cam' }, FRAME)
    expect(patch.set.aspect).toBe('540:540')
    expect(patch.set.width).toBe(0.5)
    // com a proporção já dita na spec, ela fica como está
    expect(gesturePatch('move', start, box, { type: 'video', region: 'cam', aspect: '16:9' }, FRAME).set.aspect).toBeUndefined()
  })

  it('a HTML grava sempre x, y, width e height juntos, ou só x e y a devolveriam ao quadro todo', () => {
    const start = html()
    const { box } = moveStep(start, 0.1, 0, null)
    const patch = gesturePatch('move', start, box, { type: 'html', infographic: 'barra' }, FRAME)
    expect(patch.set).toEqual({ x: 0.6, y: 0.45, width: 0.6, height: 0.3 })
    expect(patch.unset).toEqual(['region', 'position'])
  })

  it('mover a HTML mantém a largura e a altura da spec, e não as da caixa (arredondadas em px)', () => {
    // 0,12 de uma altura de 1920 px são 230,4 px: a caixa vem com 230 (0,1198), e a spec não deve ganhar essa deriva
    const start = html({ height: 230 / 1920 })
    const { box } = moveStep(start, 0.1, 0, null)
    const patch = gesturePatch('move', start, box, { type: 'html', src: 'a.html', width: 0.6, height: 0.12 }, FRAME)
    expect(patch.set).toMatchObject({ width: 0.6, height: 0.12 })
  })

  it('a HTML sem tamanho próprio na spec (o padrão é o quadro todo) leva o da caixa, que é a área do esquema', () => {
    const start = html({ width: 0.72, height: 0.135 })
    const { box } = moveStep(start, 0.05, 0, null)
    const patch = gesturePatch('move', start, box, { type: 'html', infographic: 'barra', width: 1, height: 1 }, FRAME)
    expect(patch.set).toMatchObject({ width: 0.72, height: 0.135 })
  })

  it('os campos ficam entre 0 e 1, com quatro casas', () => {
    const start = image()
    const { box } = moveStep(start, 0.123456789, -5, null)
    const { x, y } = gesturePatch('move', start, box, { type: 'image' }, FRAME).set as { x: number; y: number }
    expect(x).toBe(0.6235)
    expect(y).toBe(0)
  })
})

describe('o que o gesto grava: redimensionar', () => {
  it('o texto muda a largura da quebra e mais nada', () => {
    const start = leftText()
    const { box } = resizeStep(start, 'e', 0.1, 0, null, FRAME)
    const patch = gesturePatch('resize', start, box, { type: 'text', x: 0.12, y: 0.73 }, FRAME)
    expect(patch.set).toEqual({ 'style.max_width': 0.8 })
    expect(patch.unset).toEqual([])
  })

  it('o texto em região, ao ser redimensionado, sai da região mantendo a âncora e o alinhamento', () => {
    const start = centeredText({ placement: 'region', region: 'topo', anchor: { x: 0.5, y: 0.3 }, wrap: { left: 0.2, width: 0.6 } })
    const { box } = resizeStep(start, 'e', 0.1, 0, null, FRAME)
    const patch = gesturePatch('resize', start, box, { type: 'text', region: 'topo' }, FRAME)
    expect(patch.set).toEqual({ 'style.align': 'center', 'style.max_width': 0.8, x: 0.5, y: 0.3 })
    expect(patch.unset).toEqual(['position', 'region'])
  })

  it('a imagem e o PiP gravam o centro novo e a largura nova', () => {
    const start = image()
    const { box } = resizeStep(start, 'se', 0.1, 0.1 * (FRAME.width / FRAME.height) * 0.5, null, FRAME)
    const patch = gesturePatch('resize', start, box, { type: 'image' }, FRAME)
    expect(patch.set.width).toBeCloseTo(box.width, 3)
    expect(patch.set.x).toBeCloseTo(box.left + box.width / 2, 3)
    expect(patch.set.y).toBeCloseTo(box.top + box.height / 2, 3)
  })

  it('a HTML grava o retângulo inteiro', () => {
    const start = html()
    const { box } = resizeStep(start, 'se', 0.1, 0.1, null, FRAME)
    expect(gesturePatch('resize', start, box, { type: 'html', src: 'a.html' }, FRAME).set).toEqual({ x: 0.55, y: 0.5, width: 0.7, height: 0.4 })
  })
})

describe('aplicar o patch na sobreposição', () => {
  it('escreve os campos, inclusive os de dentro do estilo, e tira os que saem', () => {
    const overlay: Record<string, unknown> = { type: 'text', position: 'bottom', region: 'x', style: { size: 60 } }
    applyPatch(overlay, { set: { x: 0.2, 'style.max_width': 0.5 }, unset: ['position', 'region'] })
    expect(overlay).toEqual({ type: 'text', x: 0.2, style: { size: 60, max_width: 0.5 } })
  })

  it('cria o estilo quando a sobreposição ainda não tinha um', () => {
    const overlay: Record<string, unknown> = { type: 'text' }
    applyPatch(overlay, { set: { 'style.align': 'left' }, unset: [] })
    expect(overlay.style).toEqual({ align: 'left' })
  })
})
