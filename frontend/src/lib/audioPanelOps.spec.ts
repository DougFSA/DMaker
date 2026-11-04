import { describe, expect, it } from 'vitest'
import {
  envelopeGainAt,
  planCut,
  planEffect,
  planEnvelope,
  planLabel,
  planSilence,
  planSplitAt,
  tidyEnvelope,
  toProjectTime,
  trackSetOp,
} from './audioPanelOps'

// o item começa em 2 s da linha do tempo e toca a 2x: 1 s do eixo dura 0,5 s no vídeo
const clock = { start: 2, speed: 2, origin: 0 }
const slow = { start: 10, speed: 1, origin: 0 }

describe('o relógio do item', () => {
  it('leva o instante do eixo para a linha do tempo do projeto', () => {
    expect(toProjectTime(clock, 4)).toBe(4)
    expect(toProjectTime(slow, 1.5)).toBe(11.5)
    expect(toProjectTime({ start: 5, speed: 1, origin: 30 }, 32)).toBe(7) // a música que começa no meio do arquivo
    expect(toProjectTime(null, 1)).toBeNull()
  })
})

describe('silenciar, cortar e dividir', () => {
  it('silenciam a seleção em tempo do projeto', () => {
    expect(planSilence('audio.voiceover.0', slow, { start: 1, end: 3 })).toEqual({
      ok: true,
      ops: [{ type: 'audio_silence', target: 'audio.voiceover.0', start: 11, end: 13 }],
    })
    expect(planCut('audio.voiceover.0', slow, { start: 1, end: 3 })).toEqual({
      ok: true,
      ops: [{ type: 'audio_cut', target: 'audio.voiceover.0', start: 11, end: 13 }],
    })
  })

  it('pedem uma seleção e dizem quando o som não tem lugar na linha do tempo', () => {
    expect(planSilence('timeline.0', slow, null)).toEqual({ ok: false, message: 'Selecione um trecho na onda (arraste sobre ela).' })
    const noClock = planSilence('audio.tracks.0', null, { start: 1, end: 2 })
    expect(noClock.ok).toBe(false)
    expect(planCut('audio.tracks.0', slow, { start: 1, end: 2 })).toMatchObject({ ok: false })
  })

  it('só dividem a voz gravada, no instante do cursor', () => {
    expect(planSplitAt('audio.voiceover.1', slow, 2)).toEqual({
      ok: true,
      ops: [{ type: 'audio_split', target: 'audio.voiceover.1', at: 12 }],
    })
    expect(planSplitAt('timeline.0', slow, 2)).toMatchObject({ ok: false })
  })
})

describe('o marcador na seleção', () => {
  it('vira uma região com seleção e um instante sem ela', () => {
    expect(planLabel(slow, { start: 1, end: 3 }, 2)).toEqual({ ok: true, ops: [{ type: 'marker_add', start: 11, end: 13, text: '' }] })
    expect(planLabel(slow, null, 2)).toEqual({ ok: true, ops: [{ type: 'marker_add', at: 12, text: '' }] })
    expect(planLabel(null, null, 2)).toMatchObject({ ok: false })
  })
})

describe('aplicar um efeito', () => {
  it('grava o intervalo da seleção em tempo do eixo, sem converter', () => {
    expect(planEffect('timeline.0', 'normalize', { peak_db: -1 }, { start: 1.23456, end: 4 })).toEqual({
      ok: true,
      ops: [
        {
          type: 'audio_effect',
          action: 'add',
          target: 'timeline.0',
          effect: { type: 'normalize', peak_db: -1, start: 1.235, end: 4 },
        },
      ],
    })
  })

  it('sem seleção vale para o item inteiro', () => {
    const plan = planEffect('audio.music', 'amplify', { gain_db: 3 }, null)
    expect(plan).toEqual({
      ok: true,
      ops: [{ type: 'audio_effect', action: 'add', target: 'audio.music', effect: { type: 'amplify', gain_db: 3 } }],
    })
  })
})

describe('o envelope', () => {
  it('arruma a curva: em ordem, sem pontos no mesmo instante e com o ganho na faixa', () => {
    expect(
      tidyEnvelope([
        { at: 5, db: -3 },
        { at: 1, db: 40 },
        { at: 5.0004, db: -80 },
      ]),
    ).toEqual([
      { at: 1, db: 12 },
      { at: 5, db: -60 },
    ])
  })

  it('calcula o ganho em reta entre os pontos e segura a ponta fora deles', () => {
    const points = [
      { at: 10, db: 0 },
      { at: 12, db: -12 },
    ]
    expect(envelopeGainAt(points, 5)).toBe(0)
    expect(envelopeGainAt(points, 11)).toBeCloseTo(-6)
    expect(envelopeGainAt(points, 20)).toBe(-12)
    expect(envelopeGainAt([], 3)).toBe(0)
  })

  it('cria o efeito pela operação de envelope na primeira vez, em tempo do projeto', () => {
    const plan = planEnvelope('audio.voiceover.0', slow, [{ at: 1, db: 0 }, { at: 3, db: -12 }], null)
    expect(plan).toEqual({
      ok: true,
      ops: [{ type: 'audio_envelope', target: 'audio.voiceover.0', points: [{ at: 11, db: 0 }, { at: 13, db: -12 }] }],
    })
  })

  it('troca os pontos do efeito que já está na cadeia, sem empilhar outro', () => {
    const plan = planEnvelope('audio.voiceover.0', slow, [{ at: 1, db: 0 }, { at: 3, db: -6.04 }], 2)
    expect(plan).toEqual({
      ok: true,
      ops: [
        {
          type: 'audio_effect',
          action: 'set',
          target: 'audio.voiceover.0',
          index: 2,
          params: { points: [{ at: 1, db: 0 }, { at: 3, db: -6 }] },
        },
      ],
    })
  })
})

describe('a trilha', () => {
  it('monta a operação de estado da trilha', () => {
    expect(trackSetOp('A1', { solo: true })).toEqual({ type: 'track_set', track: 'A1', solo: true })
    expect(trackSetOp('MUS', { gain_db: -6, pan: 0.5 })).toEqual({ type: 'track_set', track: 'MUS', gain_db: -6, pan: 0.5 })
  })
})
