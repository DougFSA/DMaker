import { describe, expect, it } from 'vitest'
import { timelineItem, timelineTrack, timelineView } from '@/test/editorFixtures'
import {
  clampZoom,
  displayLabel,
  edgeTimes,
  fitZoom,
  hasTrimHandles,
  headerButtons,
  isDraggable,
  isOverlayTrack,
  itemCovering,
  itemTitle,
  kindClass,
  laneWidth,
  MAX_PX_PER_SEC,
  MIN_PX_PER_SEC,
  narrationMoveOp,
  nextEdge,
  roundSeconds,
  rulerTicks,
  snapBlock,
  snapPoints,
  snapTime,
  tickStep,
  timeAtX,
  trackLabel,
  trackTitle,
  transitionSpans,
  TRACK_HEADER_WIDTH,
  v1InsertIndexAt,
} from './timeline'

describe('tickStep', () => {
  it('escolhe o menor passo que deixa as marcas a pelo menos 70 px', () => {
    expect(tickStep(400)).toBe(0.2)
    expect(tickStep(60)).toBe(2)
    expect(tickStep(35)).toBe(2)
    expect(tickStep(34)).toBe(5)
    expect(tickStep(14)).toBe(5)
    expect(tickStep(7)).toBe(10)
  })

  it('no zoom mais aberto usa o maior passo', () => {
    expect(tickStep(0.01)).toBe(1800)
  })
})

describe('rulerTicks', () => {
  it('vai de zero até depois do fim, de passo em passo, sem erro de ponto flutuante', () => {
    expect(rulerTicks(5, 60)).toEqual([0, 2, 4, 6])
    const fine = rulerTicks(1, 400)
    expect(fine.slice(0, 4)).toEqual([0, 0.2, 0.4, 0.6])
  })
})

describe('zoom', () => {
  it('fica entre o mínimo e o máximo', () => {
    expect(clampZoom(1)).toBe(MIN_PX_PER_SEC)
    expect(clampZoom(9999)).toBe(MAX_PX_PER_SEC)
    expect(clampZoom(60)).toBe(60)
  })

  it('"Ajustar" faz o vídeo caber na largura visível, com a folga do fim', () => {
    expect(fitZoom(10, 540)).toBe(50)
    expect(fitZoom(0, 540)).toBe(MAX_PX_PER_SEC)
    expect(fitZoom(10_000, 540)).toBe(MIN_PX_PER_SEC)
  })

  it('a faixa tem a largura da duração mais uma folga, e nunca menos de 200 px', () => {
    expect(laneWidth(10, 60)).toBe(640)
    expect(laneWidth(0, 60)).toBe(200)
  })
})

describe('timeAtX', () => {
  it('traduz a posição do mouse em tempo, descontando o cabeçalho e somando a rolagem', () => {
    // área rolável começa em x=100; o cabeçalho tem 92 px; 60 px por segundo
    expect(timeAtX(100 + TRACK_HEADER_WIDTH + 120, 100, 0, 60, 30)).toBe(2)
    expect(timeAtX(100 + TRACK_HEADER_WIDTH + 120, 100, 60, 60, 30)).toBe(3)
  })

  it('não sai de 0 até o fim do vídeo', () => {
    expect(timeAtX(0, 100, 0, 60, 30)).toBe(0)
    expect(timeAtX(99999, 100, 0, 60, 30)).toBe(30)
  })
})

describe('encaixe', () => {
  const sorted = [0, 3, 6, 10]

  it('atrai para o ponto mais perto dentro da tolerância', () => {
    expect(snapTime(3.08, sorted, 0.1)).toBe(3)
    expect(snapTime(2.95, sorted, 0.1)).toBe(3)
  })

  it('longe de qualquer ponto, o tempo fica como está', () => {
    expect(snapTime(4.5, sorted, 0.1)).toBe(4.5)
  })

  it('tolerância zero é o encaixe desligado', () => {
    expect(snapTime(3.0001, sorted, 0)).toBe(3.0001)
  })

  it('escolhe o vizinho mais perto quando há dois ao alcance', () => {
    expect(snapTime(4.4, [4, 4.5], 1)).toBe(4.5)
    expect(snapTime(4.2, [4, 4.5], 1)).toBe(4)
  })

  it('funciona nas pontas da lista e com a lista vazia', () => {
    expect(snapTime(-0.05, sorted, 0.1)).toBe(0)
    expect(snapTime(10.05, sorted, 0.1)).toBe(10)
    expect(snapTime(5, [], 1)).toBe(5)
  })

  it('snapBlock desliza o bloco pelo começo, e se o começo não encaixou, pelo fim, sem mudar a duração', () => {
    const byStart = snapBlock(2.95, 4.95, sorted, 0.1)
    expect(byStart.start).toBe(3)
    expect(byStart.end).toBeCloseTo(5, 9)
    const byEnd = snapBlock(4.05, 5.95, sorted, 0.1)
    expect(byEnd.end).toBe(6)
    expect(byEnd.start).toBeCloseTo(4.1, 9)
    const none = snapBlock(4.2, 5, sorted, 0.1)
    expect(none.start).toBeCloseTo(4.2, 9)
    expect(none.end).toBeCloseTo(5, 9)
  })

  it('os pontos de encaixe são o começo, o fim, o cursor e as bordas de todos os itens, menos o do arrasto', () => {
    const view = timelineView()
    const withOverlay = { ...view, tracks: [...view.tracks, timelineTrack('TX', [timelineItem(0, { id: 'TX:0', start: 1, end: 2 })])] }
    expect(snapPoints(withOverlay, 4.5, null)).toEqual([0, 1, 2, 3, 4.5, 6])
    expect(snapPoints(withOverlay, 4.5, 'TX:0')).toEqual([0, 3, 4.5, 6])
    expect(snapPoints(withOverlay, null, 'TX:0')).toEqual([0, 3, 6])
  })
})

describe('o que cada item permite', () => {
  it('a V1, as sobreposições e a narração se arrastam; música, legendas e áudios não', () => {
    expect(isDraggable('V1', { kind: 'clip' })).toBe(true)
    expect(isDraggable('V2', { kind: 'video' })).toBe(true)
    expect(isDraggable('V12', { kind: 'video' })).toBe(true)
    expect(isDraggable('TX', { kind: 'text' })).toBe(true)
    expect(isDraggable('GR', { kind: 'image' })).toBe(true)
    expect(isDraggable('GR', { kind: 'progress-bar' })).toBe(false)
    expect(isDraggable('NAR', { kind: 'narration' })).toBe(true)
    for (const id of ['A1', 'A2', 'MUS', 'CC']) expect(isDraggable(id, { kind: 'x' }), id).toBe(false)
  })

  it('a narração não tem alças de aparar: a duração dela é da voz', () => {
    expect(hasTrimHandles('NAR', { kind: 'narration' })).toBe(false)
    expect(hasTrimHandles('V1', { kind: 'clip' })).toBe(true)
    expect(hasTrimHandles('TX', { kind: 'text' })).toBe(true)
    expect(hasTrimHandles('MUS', { kind: 'music' })).toBe(false)
  })

  it('sobreposição é o que vive em overlays: texto, imagem do GR e as trilhas V2 em diante', () => {
    expect(isOverlayTrack('TX', { kind: 'text' })).toBe(true)
    expect(isOverlayTrack('V3', { kind: 'video' })).toBe(true)
    expect(isOverlayTrack('V1', { kind: 'clip' })).toBe(false)
    expect(isOverlayTrack('GR', { kind: 'progress-bar' })).toBe(false)
    expect(isOverlayTrack('A2', { kind: 'track' })).toBe(false)
  })
})

describe('cabeçalho da trilha', () => {
  it('M nas de áudio, H nas de vídeo além da V1, texto, gráficos e legendas, e o cadeado em todas', () => {
    expect(headerButtons({ id: 'A1', kind: 'audio' })).toEqual(['muted', 'locked'])
    expect(headerButtons({ id: 'MUS', kind: 'audio' })).toEqual(['muted', 'locked'])
    expect(headerButtons({ id: 'V1', kind: 'video' })).toEqual(['locked'])
    expect(headerButtons({ id: 'V2', kind: 'video' })).toEqual(['hidden', 'locked'])
    expect(headerButtons({ id: 'TX', kind: 'text' })).toEqual(['hidden', 'locked'])
    expect(headerButtons({ id: 'GR', kind: 'graphics' })).toEqual(['hidden', 'locked'])
    expect(headerButtons({ id: 'CC', kind: 'captions' })).toEqual(['hidden', 'locked'])
  })

  it('o rótulo ganha uma nota musical nas de áudio, e o balão diz o nome por extenso', () => {
    expect(trackLabel({ label: 'A2', kind: 'audio' })).toBe('A2 ♪')
    expect(trackLabel({ label: 'V1', kind: 'video' })).toBe('V1')
    expect(trackTitle({ id: 'V1', label: 'V1' })).toBe('Vídeo principal (V1)')
    expect(trackTitle({ id: 'V3', label: 'V3' })).toBe('Vídeo sobreposto (V3)')
    expect(trackTitle({ id: 'A4', label: 'A4' })).toBe('Faixa de áudio externa (A4)')
    expect(trackTitle({ id: 'NAR', label: 'NAR' })).toBe('Narração (NAR)')
    expect(trackTitle({ id: 'ZZ', label: 'ZZ' })).toBe('ZZ')
  })
})

describe('nomes dos itens', () => {
  it('rótulo vindo de caminho mostra só o nome do arquivo; texto fica como veio', () => {
    expect(displayLabel('C:\\videos\\cena.mp4')).toBe('cena.mp4')
    expect(displayLabel('cards/abertura.png')).toBe('abertura.png')
    expect(displayLabel('Olá, mundo')).toBe('Olá, mundo')
    expect(displayLabel('')).toBe('')
    expect(displayLabel(null)).toBe('')
  })

  it('o balão da narração diz se a duração é real ou estimada', () => {
    const real = { kind: 'narration', label: 'Olá', start: 0, end: 2.34, extra: {} }
    const guess = { kind: 'narration', label: 'Olá', start: 1, end: 6, extra: { estimated: true } }
    expect(itemTitle(real)).toBe('Olá (duração real: 2,3 s)')
    expect(itemTitle(guess)).toBe('Olá (duração estimada: 5,0 s)')
    expect(itemTitle({ kind: 'clip', label: 'a.mp4', start: 0, end: 1, extra: {} })).toBe('a.mp4')
  })

  it('o balão de um item sem arquivo diz "fonte não encontrada"', () => {
    expect(itemTitle({ kind: 'clip', label: 'a.mp4', start: 0, end: 1, extra: {}, missing: true })).toBe('a.mp4 (fonte não encontrada)')
  })

  it('o nome de classe do tipo nunca tem caracteres de fora do padrão', () => {
    expect(kindClass('clip-audio')).toBe('clip-audio')
    expect(kindClass('a b/c')).toBe('a-b-c')
    expect(kindClass(null)).toBe('other')
  })
})

describe('operações do arrasto', () => {
  it('mover uma fala da narração muda só o início, arredondado e nunca antes de zero', () => {
    expect(narrationMoveOp({ index: 2 }, 3.14159)).toEqual({ type: 'set_field', path: 'audio.narration.2.start', value: 3.142 })
    expect(narrationMoveOp({ index: 0 }, -0.4).value).toBe(0)
  })

  it('roundSeconds guarda milissegundos', () => {
    expect(roundSeconds(0.30000000000000004)).toBe(0.3)
  })
})

describe('a V1 e as emendas', () => {
  const view = timelineView([timelineItem(0), timelineItem(1), timelineItem(2)])

  it('a mídia entra antes do primeiro trecho que começa depois do instante, ou no fim', () => {
    expect(v1InsertIndexAt(view, 0)).toBe(1)
    expect(v1InsertIndexAt(view, 3)).toBe(2)
    expect(v1InsertIndexAt(view, 4.5)).toBe(2)
    expect(v1InsertIndexAt(view, 9)).toBe(3)
    expect(v1InsertIndexAt({ ...view, tracks: [] }, 5)).toBe(0)
  })

  it('as emendas são o começo, o fim e as bordas dos trechos, sem repetição', () => {
    expect(edgeTimes(view)).toEqual([0, 3, 6, 9])
  })

  it('a próxima emenda anda para a frente ou para trás a partir do cursor', () => {
    const edges = [0, 3, 6, 9]
    expect(nextEdge(edges, 0, 1)).toBe(3)
    expect(nextEdge(edges, 3, 1)).toBe(6)
    expect(nextEdge(edges, 3, -1)).toBe(0)
    expect(nextEdge(edges, 4, -1)).toBe(3)
    expect(nextEdge(edges, 9, 1)).toBeNull()
    expect(nextEdge(edges, 0, -1)).toBeNull()
  })

  it('o item que cobre um instante inclui o início e exclui o fim', () => {
    const v1 = view.tracks[0]
    expect(itemCovering(v1, 0)?.id).toBe('V1:0')
    expect(itemCovering(v1, 3)?.id).toBe('V1:1')
    expect(itemCovering(v1, 9)).toBeNull()
    expect(itemCovering(undefined, 1)).toBeNull()
  })

  it('a hachura da transição vai do começo do trecho de entrada até o fim do anterior', () => {
    const items = [
      timelineItem(0),
      timelineItem(1, { start: 2.5, end: 6, transition: { type: 'fade', duration: 0.5 } }),
      timelineItem(2, { start: 6, end: 9, transition: { type: 'cut' } }),
    ]
    expect(transitionSpans(items)).toEqual([{ id: 'V1:1', start: 2.5, end: 3, type: 'fade' }])
  })
})
