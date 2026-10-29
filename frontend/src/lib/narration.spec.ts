import { describe, expect, it } from 'vitest'
import type { TimelineView } from '@/api'
import {
  buildNarrationItem,
  EMPTY_SCRIPT_HINT,
  estimateSeconds,
  excerpt,
  lastNarrationEnd,
  scriptStats,
  seedProblem,
  SEED_PROBLEM,
  speedLabel,
  spokenForm,
  withNarration,
} from './narration'

describe('estimateSeconds', () => {
  it('conta 14 caracteres por segundo, ajustados pela velocidade', () => {
    expect(estimateSeconds('a'.repeat(140), 1)).toBe(10)
    expect(estimateSeconds('a'.repeat(140), 2)).toBe(5)
    expect(estimateSeconds('a'.repeat(140), 0.5)).toBe(20)
  })

  it('soma as pausas fixas dos marcadores sem contá-los como fala', () => {
    expect(estimateSeconds(`${'a'.repeat(14)} [pausa 1,5] `, 1)).toBe(2.5)
    expect(estimateSeconds(`${'a'.repeat(14)} [pausa 1.2]`, 1)).toBeCloseTo(2.2, 6)
    expect(estimateSeconds('[PAUSA 2]', 1)).toBe(2)
  })

  it('a pausa não muda com a velocidade', () => {
    expect(estimateSeconds(`${'a'.repeat(14)} [pausa 1]`, 2)).toBe(1.5)
  })

  it('texto vazio dura zero, e velocidade inválida vale 1', () => {
    expect(estimateSeconds('', 1)).toBe(0)
    expect(estimateSeconds('a'.repeat(14), 0)).toBe(1)
  })

  it('conta a pronúncia de [[termo|pronúncia]], não o termo', () => {
    expect(estimateSeconds(`[[${'a'.repeat(140)}|${'b'.repeat(14)}]]`, 1)).toBe(1)
  })
})

describe('spokenForm', () => {
  it('troca [[termo|pronúncia]] e [[pronúncia]] pela pronúncia', () => {
    expect(spokenForm('Fale [[DMaker|Di Meiker]] e [[Samanta]].')).toBe('Fale Di Meiker e Samanta.')
  })

  it('texto sem marcação passa como está', () => {
    expect(spokenForm('sem marcacao')).toBe('sem marcacao')
  })
})

describe('scriptStats', () => {
  it('sem roteiro, pede para escrever', () => {
    expect(scriptStats('   ', 1)).toBe(EMPTY_SCRIPT_HINT)
  })

  it('com roteiro, diz os caracteres e a duração estimada', () => {
    expect(scriptStats('a'.repeat(140), 1)).toBe(
      '140 caracteres · duração estimada 10 s (cerca de 14 caracteres por segundo)',
    )
    expect(scriptStats('a'.repeat(1400), 1)).toContain('duração estimada 1 min 40 s')
  })
})

describe('speedLabel', () => {
  it('escreve a velocidade com vírgula e duas casas', () => {
    expect(speedLabel(1)).toBe('1,00x')
    expect(speedLabel(1.25)).toBe('1,25x')
    expect(speedLabel(0.5)).toBe('0,50x')
  })
})

describe('seedProblem', () => {
  it('a semente é opcional, inteira e não negativa', () => {
    expect(seedProblem(null)).toBe('')
    expect(seedProblem(0)).toBe('')
    expect(seedProblem(42)).toBe('')
    expect(seedProblem(1.5)).toBe(SEED_PROBLEM)
    expect(seedProblem(-1)).toBe(SEED_PROBLEM)
  })
})

describe('excerpt', () => {
  it('corta o roteiro longo com reticências e deixa o curto inteiro', () => {
    expect(excerpt('curto')).toBe('curto')
    expect(excerpt('a'.repeat(80))).toBe(`${'a'.repeat(70)}...`)
  })
})

describe('buildNarrationItem', () => {
  it('leva voz, idioma e semente só quando a pessoa escolheu', () => {
    expect(buildNarrationItem({ text: 'Oi', voiceId: 'ana', speed: 1.1, language: null, seed: 0 }, 3.456)).toEqual({
      text: 'Oi',
      start: 3.46,
      speed: 1.1,
      voice: 'ana',
      seed: 0,
    })
    expect(buildNarrationItem({ text: 'Oi', voiceId: null, speed: 1, language: 'en', seed: null }, -1)).toEqual({
      text: 'Oi',
      start: 0,
      speed: 1,
      language: 'en',
    })
  })
})

function viewWithNarrations(ends: number[]): Pick<TimelineView, 'tracks'> {
  return {
    tracks: [
      { id: 'V1', kind: 'video', label: 'V1', muted: false, hidden: false, locked: false, items: [] },
      {
        id: 'NAR',
        kind: 'audio',
        label: 'NAR',
        muted: false,
        hidden: false,
        locked: false,
        items: ends.map((end, index) => ({
          id: `NAR-${index}`,
          kind: 'narration',
          index,
          label: 'fala',
          start: 0,
          end,
          in_point: 0,
          out_point: null,
          src: null,
          source: null,
          transition: null,
          muted: false,
          extra: {},
          path: null,
        })),
      },
    ],
  }
}

describe('lastNarrationEnd', () => {
  it('é o fim da última narração do projeto', () => {
    expect(lastNarrationEnd(viewWithNarrations([4.2, 11.337, 9]))).toBe(11.34)
  })

  it('sem narração no projeto, ou sem vista, começa em 0', () => {
    expect(lastNarrationEnd(viewWithNarrations([]))).toBe(0)
    expect(lastNarrationEnd({ tracks: [] })).toBe(0)
    expect(lastNarrationEnd(null)).toBe(0)
  })
})

describe('withNarration', () => {
  const item = { text: 'Oi', start: 1, speed: 1 }

  it('cria audio.narration quando o projeto ainda não tem', () => {
    expect(withNarration({ name: 'demo' }, item)).toEqual({ name: 'demo', audio: { narration: [item] } })
  })

  it('acrescenta ao fim das que já existem, sem tocar no resto de audio', () => {
    const spec = { name: 'demo', audio: { normalize: 'two-pass', narration: [{ text: 'Antes', start: 0 }] } }
    const next = withNarration(spec, item)
    expect(next).toEqual({
      name: 'demo',
      audio: { normalize: 'two-pass', narration: [{ text: 'Antes', start: 0 }, item] },
    })
    expect(spec.audio.narration).toHaveLength(1)
  })
})
