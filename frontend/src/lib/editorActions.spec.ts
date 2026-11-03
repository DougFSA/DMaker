import { describe, expect, it } from 'vitest'
import type { TimelineItem, TimelineView } from '@/api'
import { timelineItem, timelineTrack, timelineView } from '@/test/editorFixtures'
import { planDuplicate, planRemove, planSplit, planTrackToggle, planTrim, shortcutTrack, v1ItemIds, type SelectedEntry } from './editorActions'

/** V1 com três trechos (0-3, 3-6, 6-9), um texto (1-4), um PiP (2-5), a música e a A1. */
function view(extra: { v1Locked?: boolean; txLocked?: boolean } = {}): TimelineView {
  const base = timelineView([timelineItem(0), timelineItem(1), timelineItem(2)])
  return {
    ...base,
    tracks: [
      timelineTrack('V2', [timelineItem(0, { id: 'V2:0', kind: 'video', start: 2, end: 5 })]),
      timelineTrack('TX', [timelineItem(3, { id: 'TX:3', kind: 'text', index: 3, start: 1, end: 4 })], { kind: 'text', locked: !!extra.txLocked }),
      timelineTrack('V1', base.tracks[0]?.items ?? [], { locked: !!extra.v1Locked }),
      timelineTrack('A1', [timelineItem(0, { id: 'A1:0', kind: 'clip-audio' })], { kind: 'audio' }),
      timelineTrack('MUS', [timelineItem(0, { id: 'MUS:0', kind: 'music' })], { kind: 'audio' }),
    ],
  }
}

const entry = (trackId: string, item: TimelineItem): SelectedEntry => ({ trackId, item })
const v1Item = (index: number) => view().tracks.find((track) => track.id === 'V1')?.items[index] as TimelineItem

describe('cortar', () => {
  it('corta o trecho da V1 sob o cursor, a distância dele desde o início do trecho', () => {
    expect(planSplit(view(), [], 4.5)).toEqual({ ok: true, ops: [{ type: 'split', index: 1, at: 1.5 }] })
  })

  it('o trecho selecionado vale mais que o que está sob o cursor', () => {
    const plan = planSplit(view(), [entry('V1', v1Item(0))], 1)
    expect(plan).toEqual({ ok: true, ops: [{ type: 'split', index: 0, at: 1 }] })
  })

  it('sem trecho sob o cursor, ou com o cursor colado na borda, avisa em vez de cortar', () => {
    expect(planSplit(view(), [], 9.5)).toEqual({ ok: false, message: 'Não há trecho da V1 sob o cursor.' })
    expect(planSplit(view(), [], 3.01)).toEqual({ ok: false, message: 'Posicione o cursor dentro do trecho para cortar.' })
    expect(planSplit(view(), [], 0)).toEqual({ ok: false, message: 'Posicione o cursor dentro do trecho para cortar.' })
  })

  it('com a V1 bloqueada, avisa do cadeado', () => {
    expect(planSplit(view({ v1Locked: true }), [], 4)).toEqual({ ok: false, message: 'A trilha V1 está bloqueada (cadeado no cabeçalho).' })
  })
})

describe('remover, lift e duplicar', () => {
  it('trecho da V1 vira remover; sobreposição vira remover sobreposição', () => {
    const selected = [entry('V1', v1Item(1)), entry('TX', timelineItem(3, { id: 'TX:3', kind: 'text', index: 3 }))]
    const plan = planRemove(view(), selected)
    expect(plan).toEqual({
      ok: true,
      ops: [
        { type: 'overlay_remove', index: 3 },
        { type: 'remove', index: 1 },
      ],
    })
  })

  it('vários itens da mesma lista saem do maior índice para o menor, para um não deslocar o outro', () => {
    const plan = planRemove(view(), [entry('V1', v1Item(0)), entry('V1', v1Item(2)), entry('V1', v1Item(1))])
    expect(plan).toEqual({
      ok: true,
      ops: [
        { type: 'remove', index: 2 },
        { type: 'remove', index: 1 },
        { type: 'remove', index: 0 },
      ],
    })
  })

  it('duplicar também vai do maior índice para o menor', () => {
    const plan = planDuplicate(view(), [entry('V1', v1Item(0)), entry('V1', v1Item(2))])
    expect(plan).toEqual({
      ok: true,
      ops: [
        { type: 'duplicate', index: 2 },
        { type: 'duplicate', index: 0 },
      ],
    })
  })

  it('áudio, música e legendas não se removem nem se duplicam: o aviso pede um trecho ou sobreposição', () => {
    const audio = entry('A1', timelineItem(0, { kind: 'clip-audio' }))
    expect(planRemove(view(), [audio])).toEqual({ ok: false, message: 'Selecione um trecho ou sobreposição para remover.' })
    expect(planRemove(view(), [], 'o lift')).toEqual({ ok: false, message: 'Selecione um trecho ou sobreposição para o lift.' })
    expect(planDuplicate(view(), [])).toEqual({ ok: false, message: 'Selecione um trecho ou sobreposição para duplicar.' })
  })

  it('itens de trilha bloqueada ficam de fora; se só havia esses, o aviso é do cadeado', () => {
    const text = entry('TX', timelineItem(3, { id: 'TX:3', kind: 'text', index: 3 }))
    expect(planRemove(view({ txLocked: true }), [text])).toEqual({ ok: false, message: 'A trilha TX está bloqueada (cadeado no cabeçalho).' })
    const mixed = planRemove(view({ txLocked: true }), [text, entry('V1', v1Item(0))])
    expect(mixed).toEqual({ ok: true, ops: [{ type: 'remove', index: 0 }] })
  })
})

describe('aparar até o cursor', () => {
  it('na V1, a entrada anda do início do trecho ao cursor e a saída, do fim ao cursor', () => {
    expect(planTrim(view(), [entry('V1', v1Item(1))], 'in', 4)).toEqual({ ok: true, ops: [{ type: 'trim', index: 1, side: 'in', delta: 1 }] })
    expect(planTrim(view(), [entry('V1', v1Item(1))], 'out', 5)).toEqual({ ok: true, ops: [{ type: 'trim', index: 1, side: 'out', delta: -1 }] })
  })

  it('sem seleção, apara o trecho da V1 sob o cursor', () => {
    expect(planTrim(view(), [], 'out', 7)).toEqual({ ok: true, ops: [{ type: 'trim', index: 2, side: 'out', delta: -2 }] })
  })

  it('numa sobreposição, o cursor vira o novo começo ou fim', () => {
    const text = entry('TX', timelineItem(3, { id: 'TX:3', kind: 'text', index: 3, start: 1, end: 4 }))
    expect(planTrim(view(), [text], 'in', 2)).toEqual({ ok: true, ops: [{ type: 'overlay_span', index: 3, start: 2, end: 4 }] })
    expect(planTrim(view(), [text], 'out', 3)).toEqual({ ok: true, ops: [{ type: 'overlay_span', index: 3, start: 1, end: 3 }] })
  })

  it('cursor fora do intervalo da sobreposição deixaria menos que o mínimo: avisa', () => {
    const text = entry('TX', timelineItem(3, { id: 'TX:3', kind: 'text', index: 3, start: 1, end: 4 }))
    expect(planTrim(view(), [text], 'in', 4)).toEqual({ ok: false, message: 'O cursor precisa ficar dentro do intervalo da sobreposição.' })
  })

  it('sem nada para aparar, avisa', () => {
    expect(planTrim(view(), [], 'in', 20)).toEqual({ ok: false, message: 'Selecione um trecho ou sobreposição para aparar.' })
  })
})

describe('mudo, ocultar e bloquear', () => {
  it('liga o que estava desligado e desliga o que estava ligado', () => {
    expect(planTrackToggle(view(), 'A1', 'muted')).toEqual({ ok: true, ops: [{ type: 'set_field', path: 'tracks.A1.muted', value: true }] })
    expect(planTrackToggle(view({ v1Locked: true }), 'V1', 'locked')).toEqual({
      ok: true,
      ops: [{ type: 'set_field', path: 'tracks.V1.locked', value: false }],
    })
  })

  it('só aceita o controle que o cabeçalho da trilha tem', () => {
    expect(planTrackToggle(view(), 'V1', 'hidden')).toEqual({ ok: false, message: 'A trilha V1 não tem esse controle.' })
    expect(planTrackToggle(view(), 'V2', 'muted')).toEqual({ ok: false, message: 'A trilha V2 não tem esse controle.' })
  })

  it('sem trilha (nada selecionado, mouse fora das trilhas), avisa', () => {
    expect(planTrackToggle(view(), null, 'locked')).toEqual({ ok: false, message: 'Selecione um item ou passe o mouse sobre uma trilha.' })
    expect(planTrackToggle(view(), 'ZZ', 'locked').ok).toBe(false)
  })

  it('o atalho usa a trilha do primeiro item selecionado ou, sem seleção, a que está sob o mouse', () => {
    expect(shortcutTrack([entry('A1', timelineItem(0))], 'V1')).toBe('A1')
    expect(shortcutTrack([], 'MUS')).toBe('MUS')
    expect(shortcutTrack([], null)).toBeNull()
  })
})

describe('selecionar tudo', () => {
  it('são todos os trechos da V1', () => {
    expect(v1ItemIds(view())).toEqual(['V1:0', 'V1:1', 'V1:2'])
    expect(v1ItemIds({ ...view(), tracks: [] })).toEqual([])
  })
})
