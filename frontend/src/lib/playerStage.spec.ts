import { describe, expect, it } from 'vitest'
import type { ProjectTheme, TimelineView } from '@/api'
import { timelineItem, timelineTrack, timelineView } from '@/test/editorFixtures'
import { cornerStyle, sourceOffsetFor, sourcePathOf, stageLayers, textPosition, v1ItemAt, type StageInput } from './playerStage'

const theme: ProjectTheme = {
  colors: { text: '#EEEEEE' },
  font: 'Poppins',
  logos: { horizontal: '/api/file?path=logo-h.png', symbol: '/api/file?path=logo-s.png' },
  no_dash: true,
}

function input(view: TimelineView, spec: Record<string, unknown>, extra: Partial<StageInput> = {}): StageInput {
  return { view, spec, theme, proxyUrls: {}, ...extra }
}

function viewOf(tracks: ReturnType<typeof timelineTrack>[], extra: Partial<TimelineView> = {}): TimelineView {
  return { ...timelineView([]), total: 20, tracks, ...extra }
}

const clip = (index: number, extra: Parameters<typeof timelineItem>[1] = {}) =>
  timelineItem(index, { start: index * 4, end: index * 4 + 4, path: `C:/clip${index}.mp4`, ...extra })

describe('v1ItemAt', () => {
  it('o trecho que cobre o instante e, depois do fim, o último', () => {
    const view = viewOf([timelineTrack('V1', [clip(0), clip(1)])])
    expect(v1ItemAt(view, 1)?.index).toBe(0)
    expect(v1ItemAt(view, 4)?.index).toBe(1)
    expect(v1ItemAt(view, 99)?.index).toBe(1)
    expect(v1ItemAt(viewOf([]), 0)).toBeNull()
  })
})

describe('camada V1', () => {
  it('clipe: o arquivo, o ponto nele e a velocidade do trecho', () => {
    const view = viewOf([timelineTrack('V1', [clip(0, { in_point: 5 }), clip(1)])])
    const spec = { timeline: [{ type: 'clip', speed: 2 }, { type: 'clip' }] }
    const { v1 } = stageLayers(1, input(view, spec))
    expect(v1).toMatchObject({ kind: 'clip', path: 'C:/clip0.mp4', fileTime: 7, speed: 2, missing: false })
    expect(v1.url).toBe(`/api/file?path=${encodeURIComponent('C:/clip0.mp4')}`)
    expect(v1.nextUrl).toBe(`/api/file?path=${encodeURIComponent('C:/clip1.mp4')}`)
  })

  it('o proxy pronto troca o endereço sem trocar o arquivo', () => {
    const view = viewOf([timelineTrack('V1', [clip(0)])])
    const { v1 } = stageLayers(1, input(view, { timeline: [{}] }, { proxyUrls: { 'C:/clip0.mp4': '/api/file?path=proxy' } }))
    expect(v1.url).toBe('/api/file?path=proxy')
    expect(v1.path).toBe('C:/clip0.mp4')
  })

  it('fonte em partes: a parte que grava o instante, com o ponto dela', () => {
    const crossing = clip(0, {
      start: 0,
      end: 20,
      extra: {
        pieces: [
          { start: 0, end: 10, in_point: 50, path: 'C:/cam_a.mp4' },
          { start: 10, end: 20, in_point: 0, path: 'C:/cam_b.mp4' },
        ],
      },
    })
    const view = viewOf([timelineTrack('V1', [crossing])])
    expect(stageLayers(12, input(view, { timeline: [{}] })).v1).toMatchObject({ path: 'C:/cam_b.mp4', fileTime: 2 })
    expect(stageLayers(2, input(view, { timeline: [{}] })).v1).toMatchObject({ path: 'C:/cam_a.mp4', fileTime: 52 })
  })

  it('arquivo ausente abre marcado e não pede o próximo se ele também falta', () => {
    const view = viewOf([timelineTrack('V1', [clip(0, { missing: true }), clip(1, { missing: true })])])
    const { v1 } = stageLayers(1, input(view, { timeline: [{}, {}] }))
    expect(v1.missing).toBe(true)
    expect(v1.nextUrl).toBeNull()
  })

  it('imagem usa o arquivo; cartão pede o PNG ao servidor com os campos da spec ainda não salva', () => {
    const image = timelineItem(0, { kind: 'image', start: 0, end: 3, path: 'C:/foto.png' })
    const card = timelineItem(1, { kind: 'card', start: 3, end: 6, path: null })
    const view = viewOf([timelineTrack('V1', [image, card])])
    const spec = {
      brand: 'medlycare',
      output: { preset: 'instagram/reels' },
      timeline: [{ type: 'image' }, { type: 'card', title: 'Fim', subtitle: 'Até já', variant: 'dark', logo: false }],
    }
    expect(stageLayers(1, input(view, spec)).v1).toMatchObject({ kind: 'image', url: `/api/file?path=${encodeURIComponent('C:/foto.png')}` })
    const cardLayer = stageLayers(4, input(view, spec)).v1
    expect(cardLayer.kind).toBe('card')
    expect(cardLayer.url).toBe(
      '/api/card-preview?title=Fim&brand=medlycare&preset=instagram%2Freels&subtitle=At%C3%A9%20j%C3%A1&variant=dark&logo=false&width=1080',
    )
  })

  it('sem trecho nenhum, nada a desenhar', () => {
    expect(stageLayers(0, input(viewOf([]), {})).v1.kind).toBe('none')
  })
})

describe('camada GR', () => {
  const view = viewOf([
    timelineTrack(
      'GR',
      [
        timelineItem(0, { id: 'GR-0', kind: 'image', start: 0, end: 10, src: 'logo:symbol', path: null, extra: { position: 'top-left' } }),
        timelineItem(1, { id: 'GR-1', kind: 'image', start: 0, end: 10, src: 'selo.png', path: 'C:/selo.png', extra: { position: 'bottom-right' } }),
        timelineItem(2, { id: 'GR-2', kind: 'progress-bar', start: 0, end: 20, src: null, path: null, extra: { position: 'top' } }),
      ],
      { kind: 'graphics' },
    ),
  ])
  const spec = {
    overlays: [
      { type: 'image', src: 'logo:symbol', width: 0.1, opacity: 0.5, margin: 54 },
      { type: 'image', src: 'selo.png' },
      { type: 'progress-bar', height: 14 },
    ],
  }

  it('o logo sai do tema, a imagem do arquivo, e cada uma ganha posição, largura e opacidade', () => {
    const { gr } = stageLayers(5, input(view, spec))
    expect(gr.map((layer) => layer.id)).toEqual(['GR-0', 'GR-1', 'GR-2'])
    expect(gr[0]).toMatchObject({ url: '/api/file?path=logo-s.png' })
    // a margem de 54 px vale 5% da largura de 1080 e 2,8125% da altura de 1920
    expect(gr[0]?.style).toMatchObject({ width: '10.00%', opacity: '0.5', top: '2.8125%', left: '5%' })
    expect(gr[1]?.url).toBe(`/api/file?path=${encodeURIComponent('C:/selo.png')}`)
    expect(gr[1]?.style).toMatchObject({ bottom: expect.any(String), right: expect.any(String) })
  })

  it('a barra de progresso anda com o tempo e fica no alto ou embaixo', () => {
    const bar = stageLayers(5, input(view, spec)).gr[2]
    expect(bar).toMatchObject({ kind: 'progress-bar', fraction: 0.25 })
    expect(bar?.style).toMatchObject({ top: '0', height: '14px' })
  })

  it('só os itens que cobrem o instante, e trilha oculta some', () => {
    const late = viewOf([timelineTrack('GR', [timelineItem(0, { id: 'GR-0', kind: 'image', start: 8, end: 9, src: 'a.png', path: 'C:/a.png' })])])
    expect(stageLayers(1, input(late, {})).gr).toEqual([])
    const hidden = viewOf([{ ...view.tracks[0]!, hidden: true }])
    expect(stageLayers(5, input(hidden, spec)).gr).toEqual([])
  })

  it('imagem com arquivo ausente não aparece como imagem quebrada', () => {
    const missing = viewOf([
      timelineTrack('GR', [timelineItem(0, { id: 'GR-0', kind: 'image', start: 0, end: 9, src: 'a.png', path: 'C:/a.png', missing: true })]),
    ])
    expect(stageLayers(1, input(missing, {})).gr).toEqual([])
  })
})

describe('camada PiP', () => {
  it('cada faixa de vídeo acima da V1 mostra o item do instante, no ponto certo do arquivo e no canto pedido', () => {
    const pip = timelineItem(0, {
      id: 'V2-0',
      kind: 'video',
      start: 2,
      end: 8,
      in_point: 1,
      path: 'C:/webcam.mp4',
      extra: { position: 'top-left' },
    })
    const view = viewOf([timelineTrack('V2', [pip]), timelineTrack('V1', [clip(0)])])
    const spec = { overlays: [{ type: 'video', width: 0.3, shape: 'circle', border: 4, border_color: '#fff', opacity: 0.9, margin: 54 }] }
    const [layer] = stageLayers(4, input(view, spec)).pips
    expect(layer).toMatchObject({ id: 'V2-0', path: 'C:/webcam.mp4', fileTime: 3, missing: false })
    expect(layer?.style).toMatchObject({ width: '30%', borderRadius: '50%', border: '4px solid #fff', opacity: '0.9', top: '2.8125%', left: '5%' })
    expect(stageLayers(1, input(view, spec)).pips).toEqual([])
  })

  it('o círculo é 1:1, `aspect` manda no resto e sem ele vale 16:9', () => {
    const pip = timelineItem(0, { id: 'V2-0', kind: 'video', start: 0, end: 8, path: 'C:/w.mp4' })
    const view = viewOf([timelineTrack('V2', [pip])])
    const aspectOf = (overlay: Record<string, unknown>) =>
      stageLayers(1, input(view, { overlays: [overlay] })).pips[0]?.style.aspectRatio
    expect(aspectOf({ shape: 'circle', aspect: '16:9' })).toBe('1 / 1')
    expect(aspectOf({ shape: 'rect', aspect: '4:5' })).toBe('4 / 5')
    expect(aspectOf({})).toBe('16 / 9')
    expect(aspectOf({ aspect: 'quebrado' })).toBe('16 / 9')
  })

  it('x e y da spec mandam na posição, e o PiP de fonte ausente vem marcado', () => {
    const pip = timelineItem(0, { id: 'V2-0', kind: 'video', start: 0, end: 8, path: 'C:/w.mp4', missing: true })
    const view = viewOf([timelineTrack('V2', [pip])])
    const [layer] = stageLayers(1, input(view, { overlays: [{ type: 'video', x: 0.5, y: 0.25 }] })).pips
    expect(layer?.style).toMatchObject({ left: '50%', top: '25%' })
    expect(layer?.missing).toBe(true)
  })

  it('PiP de uma fonte sincronizada desconta o deslocamento dela', () => {
    const pip = timelineItem(0, { id: 'V2-0', kind: 'video', start: 0, end: 8, in_point: 20, source: 'cam2', path: 'C:/cam2.mp4', extra: {} })
    const view = viewOf([timelineTrack('V2', [pip])], { sources: { cam2: { src: 'cam2.mp4', parts: [], offset: 5, in_point: 0, path: 'C:/cam2.mp4' } } })
    expect(stageLayers(3, input(view, { overlays: [{}] })).pips[0]?.fileTime).toBe(18)
    expect(sourceOffsetFor(view)('cam2')).toBe(5)
    expect(sourceOffsetFor(view)('outra')).toBe(0)
  })
})

describe('camada TX', () => {
  const text = (extra: Record<string, unknown> = {}) =>
    timelineItem(0, { id: 'TX-0', kind: 'text', start: 0, end: 5, label: 'Gancho', path: null, extra: { role: 'hook', ...extra } })

  it('o gancho vai para o alto, com o tamanho do papel e as cores do tema', () => {
    const view = viewOf([timelineTrack('TX', [text()], { kind: 'text' })])
    const [layer] = stageLayers(1, input(view, { overlays: [{ type: 'text' }] })).tx
    expect(layer).toMatchObject({ id: 'TX-0', text: 'Gancho', role: 'hook' })
    expect(layer?.style).toMatchObject({ top: '8%', color: '#EEEEEE', fontFamily: 'Poppins' })
    expect(layer?.style.fontSize).toBe(`calc(var(--stage-h, 600px) * ${90 / 1080})`)
  })

  it('posição, tamanho, cor e maiúsculas vêm do estilo da sobreposição', () => {
    const view = viewOf([timelineTrack('TX', [text({ role: 'cta' })], { kind: 'text' })])
    const spec = { overlays: [{ position: 'center', style: { size: 120, color: '#FF0000', uppercase: true } }] }
    const [layer] = stageLayers(1, input(view, spec)).tx
    expect(layer?.style).toMatchObject({ top: '50%', transform: 'translateY(-50%)', color: '#FF0000', textTransform: 'uppercase' })
    expect(layer?.style.fontSize).toBe(`calc(var(--stage-h, 600px) * ${120 / 1080})`)
  })

  it('sem tema, o texto fica branco; trilha oculta some', () => {
    const view = viewOf([timelineTrack('TX', [text({ role: 'subtitle' })], { kind: 'text' })])
    expect(stageLayers(1, input(view, { overlays: [{}] }, { theme: null })).tx[0]?.style).toMatchObject({ bottom: '10%', color: '#FFFFFF' })
    const hidden = viewOf([timelineTrack('TX', [text()], { kind: 'text', hidden: true })])
    expect(stageLayers(1, input(hidden, { overlays: [{}] })).tx).toEqual([])
  })
})

describe('posições', () => {
  it('cantos, bordas e centro; posição desconhecida cai no canto de cima à direita', () => {
    expect(cornerStyle('bottom-left', 3, 4)).toEqual({ bottom: '4%', left: '3%' })
    expect(cornerStyle('top', 3, 4)).toEqual({ top: '4%', left: '50%', transform: 'translateX(-50%)' })
    expect(cornerStyle('center', 3, 4)).toEqual({ top: '50%', left: '50%', transform: 'translate(-50%, -50%)' })
    expect(cornerStyle('qualquer', 3, 4)).toEqual({ top: '4%', right: '3%' })
  })

  it('o texto vai para onde o papel manda quando a spec não diz', () => {
    expect(textPosition('hook', undefined)).toBe('top')
    expect(textPosition('title', 'bottom')).toBe('bottom')
    expect(textPosition('cta', undefined)).toBe('bottom')
    expect(textPosition('custom', 'center')).toBe('center')
  })

  it('o caminho de um item: o que o servidor resolveu, o src ou a fonte nomeada', () => {
    const view = viewOf([], { sources: { cam: { src: 'cam.mp4', parts: [], offset: 0, in_point: 0, path: 'C:/cam.mp4' } } })
    expect(sourcePathOf(timelineItem(0, { path: 'C:/x.mp4' }), view)).toBe('C:/x.mp4')
    expect(sourcePathOf(timelineItem(0, { path: null, src: 'y.mp4' }), view)).toBe('y.mp4')
    expect(sourcePathOf(timelineItem(0, { path: null, src: null, source: 'cam' }), view)).toBe('C:/cam.mp4')
    expect(sourcePathOf(timelineItem(0, { path: null, src: null, source: 'nada' }), view)).toBeNull()
  })
})
