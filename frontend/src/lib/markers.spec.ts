import { describe, expect, it } from 'vitest'
import type { TimelineItem, TimelineView } from '@/api'
import { timelineItem, timelineTrack, timelineView } from '@/test/editorFixtures'
import { planAddMarker, planDuplicate, planRemove, planTrim, type SelectedEntry } from './editorActions'
import {
  markerColor,
  markerGroup,
  markerItems,
  markerMoveOperation,
  markerTitle,
  markerTrackOf,
  nextMarker,
  renameOperation,
} from './markers'
import { dragOperation, dragPreview, type DragStart, type SnapContext } from './timelineDrag'
import { hasTrimHandles, headerButtons, isDraggable, isInstantMarker, isMarkerTrack, trackTitle } from './timeline'

const NO_SNAP: SnapContext = { points: [], tolerance: 0, total: 30 }

/** Um marcador da vista: `instant` quando o início e o fim são o mesmo ponto. */
function marker(index: number, start: number, end: number, extra: Record<string, unknown> = {}, label = `marca ${index}`): TimelineItem {
  return timelineItem(index, {
    id: `MK-${index}`,
    kind: 'marker',
    label,
    start,
    end,
    in_point: 0,
    out_point: null,
    src: null,
    extra: { color: null, group: '', instant: start === end, ...extra },
  })
}

function viewWith(...markers: TimelineItem[]): TimelineView {
  const base = timelineView([timelineItem(0), timelineItem(1), timelineItem(2)])
  const groups = [...new Set(markers.map((item) => String(item.extra.group ?? '')))]
  return {
    ...base,
    tracks: [
      ...base.tracks,
      ...groups.map((group) =>
        timelineTrack(group ? `MK:${group}` : 'MK', markers.filter((item) => item.extra.group === group), {
          kind: 'markers',
          label: group ? `MK ${group}` : 'MK',
        }),
      ),
    ],
  }
}

const entry = (trackId: string, item: TimelineItem): SelectedEntry => ({ trackId, item })

describe('a trilha MK', () => {
  it('reconhece a trilha padrão e as dos grupos', () => {
    expect(isMarkerTrack('MK')).toBe(true)
    expect(isMarkerTrack('MK:análise')).toBe(true)
    expect(['V1', 'MUS', 'MKT', 'XMK'].some(isMarkerTrack)).toBe(false)
  })

  it('o instante e a região se distinguem pelo extra da vista', () => {
    expect(isInstantMarker(marker(0, 3, 3))).toBe(true)
    expect(isInstantMarker(marker(1, 3, 6))).toBe(false)
  })

  it('o marcador se arrasta; só a região tem alças de aparar', () => {
    expect(isDraggable('MK', marker(0, 3, 3))).toBe(true)
    expect(hasTrimHandles('MK', marker(0, 3, 3))).toBe(false)
    expect(hasTrimHandles('MK:meus', marker(1, 3, 6))).toBe(true)
  })

  it('o cabeçalho só tem o cadeado, e o balão diz de quem é a trilha', () => {
    expect(headerButtons({ id: 'MK', kind: 'markers' })).toEqual(['locked'])
    expect(trackTitle({ id: 'MK', label: 'MK' })).toBe('Marcadores (MK)')
    expect(trackTitle({ id: 'MK:análise', label: 'MK análise' })).toBe('Marcadores do grupo análise (MK:análise)')
  })

  it('a cor só vale se for #RRGGBB, e o grupo vazio é a trilha padrão', () => {
    expect(markerColor(marker(0, 1, 1, { color: '#E0A020' }))).toBe('#E0A020')
    expect(markerColor(marker(0, 1, 1, { color: 'vermelho' }))).toBeNull()
    expect(markerColor(marker(0, 1, 1))).toBeNull()
    expect(markerGroup(marker(0, 1, 1, { group: 'meus' }))).toBe('meus')
    expect(markerGroup(marker(0, 1, 1))).toBe('')
  })

  it('o balão traz o texto e o tempo, com vírgula', () => {
    expect(markerTitle(marker(0, 12.5, 12.5, {}, 'refrão'))).toBe('refrão (12,5 s)')
    expect(markerTitle(marker(1, 2, 4.25, {}, ''))).toBe('Marcador sem texto (2 a 4,25 s)')
  })
})

describe('pular entre marcadores', () => {
  const view = viewWith(marker(0, 10, 10), marker(1, 2, 5), marker(2, 20, 20, { group: 'meus' }))

  it('lista os marcadores de todas as trilhas por ordem de início', () => {
    expect(markerItems(view).map((item) => item.id)).toEqual(['MK-1', 'MK-0', 'MK-2'])
  })

  it('o seguinte é o primeiro que começa depois do cursor, o anterior é o último que começou antes', () => {
    expect(nextMarker(view, 0, 1)?.id).toBe('MK-1')
    expect(nextMarker(view, 2, 1)?.id).toBe('MK-0')
    expect(nextMarker(view, 10, 1)?.id).toBe('MK-2')
    expect(nextMarker(view, 10, -1)?.id).toBe('MK-1')
    expect(nextMarker(view, 2, -1)).toBeNull()
    expect(nextMarker(view, 20, 1)).toBeNull()
  })

  it('o cursor que acabou de pousar no marcador não o repete', () => {
    expect(nextMarker(view, 10.002, -1)?.id).toBe('MK-1')
    expect(nextMarker(view, 9.998, 1)?.id).toBe('MK-2')
  })

  it('sem marcador não há para onde pular', () => {
    expect(nextMarker(timelineView(), 1, 1)).toBeNull()
  })
})

describe('arrastar um marcador', () => {
  function startOf(item: TimelineItem, mode: DragStart['mode'], side: DragStart['side'] = null): DragStart {
    return { mode, trackId: 'MK', item, side, original: { start: item.start, end: item.end } }
  }

  it('o instante vira marker_set com o novo instante', () => {
    const item = marker(3, 10, 10)
    const track = timelineTrack('MK', [item], { kind: 'markers' })
    const drag = startOf(item, 'shift')
    expect(dragOperation(drag, track, dragPreview(drag, track, 2.5, NO_SNAP))).toEqual({ type: 'marker_set', index: 3, at: 12.5 })
  })

  it('a região inteira anda junto, e a borda puxada muda só aquela ponta', () => {
    const item = marker(1, 4, 8)
    const track = timelineTrack('MK', [item], { kind: 'markers' })
    const body = startOf(item, 'shift')
    expect(dragOperation(body, track, dragPreview(body, track, 1, NO_SNAP))).toEqual({ type: 'marker_set', index: 1, start: 5, end: 9 })
    const edge = startOf(item, 'trim', 'out')
    expect(dragOperation(edge, track, dragPreview(edge, track, 2, NO_SNAP))).toEqual({ type: 'marker_set', index: 1, start: 4, end: 10 })
    const head = startOf(item, 'trim', 'in')
    expect(dragOperation(head, track, dragPreview(head, track, -1, NO_SNAP))).toEqual({ type: 'marker_set', index: 1, start: 3, end: 8 })
  })

  it('o marcador encaixa nos pontos vizinhos e não sai do vídeo', () => {
    const item = marker(0, 10, 10)
    const track = timelineTrack('MK', [item], { kind: 'markers' })
    const drag = startOf(item, 'shift')
    const snapped = dragPreview(drag, track, 1.95, { points: [12], tolerance: 0.1, total: 30 })
    expect(snapped.start).toBe(12)
    expect(dragPreview(drag, track, 99, NO_SNAP).start).toBe(30)
    expect(dragPreview(drag, track, -99, NO_SNAP).start).toBe(0)
  })

  it('soltar sem mover não grava nada', () => {
    const item = marker(0, 10, 10)
    const track = timelineTrack('MK', [item], { kind: 'markers' })
    const drag = startOf(item, 'shift')
    expect(dragOperation(drag, track, dragPreview(drag, track, 0, NO_SNAP))).toBeNull()
  })

  it('markerMoveOperation separa o instante da região', () => {
    expect(markerMoveOperation(marker(2, 1, 1), { start: 1.2346, end: 1.2346 })).toEqual({ type: 'marker_set', index: 2, at: 1.235 })
    expect(markerMoveOperation(marker(2, 1, 3), { start: 1, end: 3.5 })).toEqual({ type: 'marker_set', index: 2, start: 1, end: 3.5 })
  })
})

describe('renomear', () => {
  it('só há operação se o texto mudou, e sem espaço nas pontas', () => {
    expect(renameOperation({ index: 4, label: 'refrão' }, '  coda ')).toEqual({ type: 'marker_set', index: 4, text: 'coda' })
    expect(renameOperation({ index: 4, label: 'refrão' }, 'refrão ')).toBeNull()
  })

  it('apagar todo o texto também é uma mudança', () => {
    expect(renameOperation({ index: 0, label: 'x' }, '')).toEqual({ type: 'marker_set', index: 0, text: '' })
  })
})

describe('criar e remover', () => {
  it('cria no cursor, na trilha padrão, com o tempo arredondado ao milissegundo', () => {
    expect(planAddMarker(viewWith(), [], 12.3456)).toEqual({ ok: true, ops: [{ type: 'marker_add', at: 12.346, text: '' }] })
  })

  it('com um marcador selecionado, o novo vai para o grupo dele', () => {
    const selected = marker(0, 3, 3, { group: 'meus' })
    const view = viewWith(selected)
    expect(planAddMarker(view, [entry('MK:meus', selected)], 5)).toEqual({
      ok: true,
      ops: [{ type: 'marker_add', at: 5, text: '', group: 'meus' }],
    })
    expect(markerTrackOf(view, 'meus')?.id).toBe('MK:meus')
    expect(markerTrackOf(view, '')).toBeUndefined()
  })

  it('numa trilha de marcadores bloqueada, avisa do cadeado', () => {
    const selected = marker(0, 3, 3)
    const view = viewWith(selected)
    view.tracks = view.tracks.map((track) => (track.id === 'MK' ? { ...track, locked: true } : track))
    expect(planAddMarker(view, [entry('MK', selected)], 5)).toEqual({
      ok: false,
      message: 'A trilha MK está bloqueada (cadeado no cabeçalho).',
    })
  })

  it('remover marcadores sai do maior índice para o menor, e antes dos trechos (apagar um trecho pode levar marcadores)', () => {
    const view = viewWith(marker(0, 1, 1), marker(5, 4, 4))
    const plan = planRemove(view, [
      entry('V1', timelineItem(2)),
      entry('MK', marker(0, 1, 1)),
      entry('MK', marker(5, 4, 4)),
    ])
    expect(plan).toEqual({
      ok: true,
      ops: [
        { type: 'marker_remove', index: 5 },
        { type: 'marker_remove', index: 0 },
        { type: 'remove', index: 2 },
      ],
    })
  })

  it('duplicar e aparar ignoram o marcador selecionado: o aviso pede um trecho ou sobreposição', () => {
    const view = viewWith(marker(0, 1, 1))
    expect(planDuplicate(view, [entry('MK', marker(0, 1, 1))])).toEqual({
      ok: false,
      message: 'Selecione um trecho ou sobreposição para duplicar.',
    })
    expect(planTrim(view, [entry('MK', marker(0, 1, 1))], 'in', 40)).toEqual({
      ok: false,
      message: 'Selecione um trecho ou sobreposição para aparar.',
    })
  })
})
