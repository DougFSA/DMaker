import { describe, expect, it } from 'vitest'
import type { AudioGeneratorInfo } from '@/api'
import { timelineItem, timelineTrack } from '@/test/editorFixtures'
import {
  FAMILY_NAMES,
  GENERATED_PATH,
  addGeneratedIn,
  censorBeepOperation,
  generatedList,
  generatedMoveOperation,
  groupByFamily,
  isGeneratedItem,
  newSound,
  removeGeneratedIn,
  soundParamValue,
} from './generatedSounds'
import { effectContextFor } from './audioEffects'
import { hasTrimHandles, isDraggable } from './timeline'
import { dragOperation, dragPreview, type DragStart, type SnapContext } from './timelineDrag'
import { isDuckTrack } from './autoDuck'
import { planCensorBeep } from './audioPanelOps'

const tone = { type: 'tone', default_duration: 1 }
const info = (type: string, family: string): AudioGeneratorInfo => ({
  type,
  label: type,
  audacity_name: type,
  summary: '',
  family,
  default_duration: 1,
  has_natural_duration: false,
  parameters: [],
})

describe('a lista de sons gerados da spec', () => {
  it('vem vazia num projeto sem o campo e traz a lista quando ele existe', () => {
    expect(generatedList({ audio: {} })).toEqual([])
    expect(generatedList(undefined)).toEqual([])
    const sound = { generator: 'tone', params: {}, start: 1, duration: 2 }
    expect(generatedList({ audio: { generated: [sound] } })).toEqual([sound])
  })

  it('acrescenta o som e some com a chave ao tirar o último, como o projeto de antes', () => {
    const spec: Record<string, unknown> = { audio: {} }
    expect(addGeneratedIn(spec, newSound(tone, 4))).toBe(0)
    expect(addGeneratedIn(spec, newSound({ type: 'noise', default_duration: 2 }, 0))).toBe(1)
    expect(generatedList(spec).map((sound) => sound.generator)).toEqual(['tone', 'noise'])
    expect(removeGeneratedIn(spec, 0)).toBe(true)
    expect(removeGeneratedIn(spec, 5)).toBe(false)
    expect(removeGeneratedIn(spec, 0)).toBe(true)
    expect(Object.keys(spec.audio as object)).toEqual([])
  })

  it('o som novo leva o gerador, os padrões do servidor (parâmetros vazios) e a duração que ele pede', () => {
    expect(newSound({ type: 'rhythm_track', default_duration: 8 }, 3.25)).toEqual({
      generator: 'rhythm_track',
      params: {},
      start: 3.25,
      duration: 8,
    })
    expect(newSound(tone, -2).start).toBe(0)
  })

  it('mostra o valor da spec e, sem ele, o padrão do catálogo', () => {
    const param = { name: 'frequency_hz', default: 440 }
    expect(soundParamValue({ params: { frequency_hz: 1000 } }, param)).toBe(1000)
    expect(soundParamValue({ params: {} }, param)).toBe(440)
  })
})

describe('o menu por família', () => {
  it('agrupa na ordem do catálogo e dá o nome em português de cada família', () => {
    const groups = groupByFamily([info('tone', 'tons'), info('noise', 'ruído'), info('chirp', 'tons'), info('x', 'nova')])
    expect(groups.map((group) => [group.label, group.items.map((item) => item.type)])).toEqual([
      [FAMILY_NAMES.tons, ['tone', 'chirp']],
      [FAMILY_NAMES['ruído'], ['noise']],
      ['nova', ['x']],
    ])
  })
})

describe('a trilha SFX', () => {
  it('o som gerado se arrasta, tem alças de aparar e a cadeia de efeitos dele mora em audio.generated.N', () => {
    const item = { kind: 'generated' }
    expect(isGeneratedItem('SFX')).toBe(true)
    expect(isDraggable('SFX', item)).toBe(true)
    expect(hasTrimHandles('SFX', item)).toBe(true)
    const context = effectContextFor({ trackId: 'SFX', item: timelineItem(2, { id: 'SFX-2', kind: 'generated', label: 'Tom 1000 Hz' }) }, null)
    expect(context).toMatchObject({ kind: 'chain', chain: { targetKey: 'audio.generated.N', listPath: 'audio.generated.2.effects' } })
  })

  it('a SFX pode ser o fundo de uma regra de Auto Duck', () => {
    expect(isDuckTrack('SFX')).toBe(true)
  })

  const NO_SNAP: SnapContext = { points: [], tolerance: 0, total: 30 }
  const track = timelineTrack('SFX', [timelineItem(1, { id: 'SFX-1', kind: 'generated', start: 4, end: 5 })], { kind: 'audio' })

  function start(mode: DragStart['mode'], side: DragStart['side'] = null): DragStart {
    const item = track.items[0]!
    return { mode, trackId: 'SFX', item, side, original: { start: item.start, end: item.end } }
  }

  it('arrastar o corpo muda o início e mantém a duração: grava um generated_set', () => {
    const drag = start('shift')
    expect(dragOperation(drag, track, dragPreview(drag, track, 2, NO_SNAP))).toEqual({
      type: 'generated_set',
      index: 1,
      start: 6,
      duration: 1,
    })
  })

  it('aparar a borda de saída muda só a duração', () => {
    const drag = start('trim', 'out')
    expect(dragOperation(drag, track, dragPreview(drag, track, 0.5, NO_SNAP))).toEqual({
      type: 'generated_set',
      index: 1,
      start: 4,
      duration: 1.5,
    })
  })

  it('sem movimento não há operação', () => {
    const drag = start('shift')
    expect(dragOperation(drag, track, dragPreview(drag, track, 0, NO_SNAP))).toBeNull()
  })

  it('a operação de mover nunca guarda duração menor que o mínimo', () => {
    expect(generatedMoveOperation(0, 1, 0)).toEqual({ type: 'generated_set', index: 0, start: 1, duration: 0.01 })
    expect(generatedMoveOperation(0, 1)).toEqual({ type: 'generated_set', index: 0, start: 1 })
  })
})

describe('o bipe de censura', () => {
  it('a operação leva o alvo e o intervalo', () => {
    expect(censorBeepOperation('audio.voiceover.0', 4, 4.5)).toEqual({ type: 'censor_beep', target: 'audio.voiceover.0', start: 4, end: 4.5 })
  })

  it('do painel Áudio: converte a seleção do eixo do item para a linha do tempo pelo relógio', () => {
    const clock = { start: 10, speed: 2, origin: 0 }
    expect(planCensorBeep('audio.voiceover.0', clock, { start: 1, end: 3 })).toEqual({
      ok: true,
      ops: [{ type: 'censor_beep', target: 'audio.voiceover.0', start: 10.5, end: 11.5 }],
    })
  })

  it('sem seleção, ou num item sem lugar na linha do tempo, devolve o aviso', () => {
    expect(planCensorBeep('timeline.0', { start: 0, speed: 1, origin: 0 }, null)).toEqual({
      ok: false,
      message: 'Selecione um trecho na onda (arraste sobre ela).',
    })
    expect(planCensorBeep('audio.tracks.0', null, { start: 1, end: 2 })).toMatchObject({ ok: false })
  })

  it('o caminho dos sons gerados é audio.generated', () => {
    expect(GENERATED_PATH).toBe('audio.generated')
  })
})
