import { describe, expect, it } from 'vitest'
import { DEFAULT_GATE, gateDecisions, keptRuns, SoundGate, type SoundGateConfig } from './soundGate'

const BLOCK_MS = 50
const PER_SECOND = 1000 / BLOCK_MS
const SPEECH = -20
const SILENCE = -70
const config: SoundGateConfig = { ...DEFAULT_GATE, blockMs: BLOCK_MS }

/** Níveis sintéticos por bloco de 50 ms: `[segundos, nível]` em sequência. */
function levels(...parts: Array<[number, number]>): number[] {
  return parts.flatMap(([seconds, level]) => new Array<number>(Math.round(seconds * PER_SECOND)).fill(level))
}

const seconds = (blocks: number) => blocks / PER_SECOND

describe('a gravação ativada por som', () => {
  it('não grava o silêncio entre as falas: só a fala, o pré-rolo de 300 ms e a cauda de 300 ms de cada uma', () => {
    // 2 s mudo, fala de 3 s, 5 s de silêncio, fala de 2 s, 4 s de silêncio
    const input = levels([2, SILENCE], [3, SPEECH], [5, SILENCE], [2, SPEECH], [4, SILENCE])
    const kept = gateDecisions(input, config)
    const runs = keptRuns(kept)
    expect(runs).toHaveLength(2)
    const first = runs[0] as [number, number]
    const second = runs[1] as [number, number]
    // a primeira fala começa no bloco 40 (2 s); o pré-rolo guarda 6 blocos (300 ms) antes dela
    expect(first[0]).toBe(40 - 6)
    expect(seconds(first[1] - first[0] + 1)).toBeCloseTo(0.3 + 3 + 0.3, 5)
    expect(seconds(second[1] - second[0] + 1)).toBeCloseTo(0.3 + 2 + 0.3, 5)
    const recorded = seconds(kept.filter(Boolean).length)
    const total = seconds(input.length)
    expect(total).toBe(16)
    expect(recorded).toBeCloseTo(6.2, 5)
    // dos 9 s de silêncio (2 + 5 + 4 s), só 1,2 s entram no arquivo: o pré-rolo e a cauda
    expect(recorded - 5).toBeCloseTo(1.2, 5)
  })

  it('uma pausa curta dentro da frase (menor que a espera) é gravada inteira', () => {
    const input = levels([1, SPEECH], [0.8, SILENCE], [1, SPEECH], [3, SILENCE])
    const runs = keptRuns(gateDecisions(input, config))
    expect(runs).toHaveLength(1)
    const [start, end] = runs[0] as [number, number]
    expect(seconds(end - start + 1)).toBeCloseTo(1 + 0.8 + 1 + 0.3, 5) // sem pré-rolo: a fala abre no bloco 0
  })

  it('uma pausa maior que a espera divide em duas gravações e joga fora o miolo', () => {
    const input = levels([1, SPEECH], [2, SILENCE], [1, SPEECH])
    const runs = keptRuns(gateDecisions(input, config))
    expect(runs).toHaveLength(2)
    const kept = gateDecisions(input, config).filter(Boolean).length
    expect(seconds(kept)).toBeCloseTo(1 + 0.3 + 0.3 + 1, 5) // cauda da primeira, pré-rolo da segunda
  })

  it('só silêncio não grava nada', () => {
    expect(gateDecisions(levels([10, SILENCE]), config).some(Boolean)).toBe(false)
  })

  it('a gravação que acaba durante a espera ainda leva a cauda da fala', () => {
    const kept = gateDecisions(levels([1, SPEECH], [0.8, SILENCE]), config)
    expect(seconds(kept.filter(Boolean).length)).toBeCloseTo(1 + 0.3, 5)
  })

  it('o limiar decide: um som abaixo dele é silêncio, acima dele abre', () => {
    const quiet = levels([1, -45], [1, -35], [1, -45])
    const runs = keptRuns(gateDecisions(quiet, { ...config, thresholdDb: -40 }))
    expect(runs).toHaveLength(1)
    const [start] = runs[0] as [number, number]
    expect(seconds(start)).toBeCloseTo(1 - 0.3, 5)
    expect(keptRuns(gateDecisions(quiet, { ...config, thresholdDb: -30 }))).toHaveLength(0)
  })

  it('espera curta pausa mais cedo e não repete blocos no pré-rolo (nenhum bloco sai duas vezes)', () => {
    const short: SoundGateConfig = { ...config, waitMs: 200, prerollMs: 500, tailMs: 300 }
    const gate = new SoundGate(short)
    const emitted: number[] = []
    const input = levels([1, SPEECH], [3, SILENCE], [1, SPEECH], [3, SILENCE])
    for (const level of input) emitted.push(...gate.push(level).emit)
    emitted.push(...gate.finish())
    expect(new Set(emitted).size).toBe(emitted.length)
    expect([...emitted].sort((a, b) => a - b)).toEqual(emitted) // sempre em ordem
  })

  it('a conta ao vivo, bloco a bloco, é a mesma conta pura', () => {
    const input = levels([1.3, SILENCE], [2.1, SPEECH], [0.4, SILENCE], [1.7, SPEECH], [6, SILENCE], [1, SPEECH])
    const gate = new SoundGate(config)
    const live = new Array<boolean>(input.length).fill(false)
    input.forEach((level) => gate.push(level).emit.forEach((block) => (live[block] = true)))
    gate.finish().forEach((block) => (live[block] = true))
    expect(live).toEqual(gateDecisions(input, config))
  })

  it('informa se a gravação está escrevendo (dentro da fala ou da espera dela)', () => {
    const gate = new SoundGate(config)
    expect(gate.push(SILENCE).open).toBe(false)
    expect(gate.push(SPEECH).open).toBe(true)
    expect(gate.push(SILENCE).open).toBe(true) // a espera ainda conta como aberta
    for (let index = 0; index < 40; index += 1) gate.push(SILENCE)
    expect(gate.push(SILENCE).open).toBe(false)
  })
})
