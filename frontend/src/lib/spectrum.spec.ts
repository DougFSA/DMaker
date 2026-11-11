import { describe, expect, it } from 'vitest'
import type { SpectrumCurve } from '@/api'
import {
  analysisTargetOf,
  curvePath,
  formatDb,
  formatHz,
  formatNote,
  frequencyAtX,
  frequencyTicks,
  levelAt,
  levelTicks,
  noteOf,
  spectrumRange,
  xOfFrequency,
  yOfLevel,
  type PlotBox,
} from './spectrum'

const box: PlotBox = { left: 50, right: 650, top: 10, bottom: 210 }

/** Uma curva de 5 pontos: um pico de -6 dB em 1 kHz sobre um piso de -90 dB. */
function curve(): SpectrumCurve {
  return {
    frequencies: [0, 500, 1000, 1500, 24000],
    levels_db: [-90, -70, -6, -70, -90],
    points_total: 5,
  }
}

describe('o recorte do gráfico', () => {
  it('o topo é o pico arredondado para a dezena e o eixo mostra 100 dB', () => {
    const range = spectrumRange(curve(), 'log')
    expect(range).toEqual({ lowHz: 20, highHz: 24000, lowDb: -100, highDb: 0 })
    expect(spectrumRange(curve(), 'linear').lowHz).toBe(0)
  })

  it('um sinal estourado não empurra o topo além de +20 dB', () => {
    const loud = { frequencies: [100, 200], levels_db: [55, 40], points_total: 2 }
    expect(spectrumRange(loud, 'log').highDb).toBe(20)
  })
})

describe('frequência e posição', () => {
  it('no eixo logarítmico cada oitava ocupa a mesma largura', () => {
    const range = spectrumRange(curve(), 'log')
    const at100 = xOfFrequency(100, 'log', range, box)
    const at200 = xOfFrequency(200, 'log', range, box)
    const at400 = xOfFrequency(400, 'log', range, box)
    expect(at200 - at100).toBeCloseTo(at400 - at200, 6)
    expect(xOfFrequency(20, 'log', range, box)).toBe(box.left)
    expect(xOfFrequency(24000, 'log', range, box)).toBeCloseTo(box.right, 6)
  })

  it('no linear a posição cresce com a frequência', () => {
    const range = spectrumRange(curve(), 'linear')
    expect(xOfFrequency(0, 'linear', range, box)).toBe(box.left)
    expect(xOfFrequency(12000, 'linear', range, box)).toBeCloseTo((box.left + box.right) / 2, 6)
  })

  it('a posição devolve a frequência que a produziu, nos dois eixos', () => {
    for (const axis of ['log', 'linear'] as const) {
      const range = spectrumRange(curve(), axis)
      for (const frequency of [30, 440, 1000, 9000]) {
        const x = xOfFrequency(frequency, axis, range, box)
        expect(frequencyAtX(x, axis, range, box)).toBeCloseTo(frequency, 3)
      }
    }
  })

  it('fora da área do gráfico a frequência fica nas pontas', () => {
    const range = spectrumRange(curve(), 'log')
    expect(frequencyAtX(-500, 'log', range, box)).toBeCloseTo(20, 6)
    expect(frequencyAtX(9999, 'log', range, box)).toBeCloseTo(24000, 3)
  })

  it('o nível mais alto fica no topo e o mais baixo, embaixo', () => {
    const range = spectrumRange(curve(), 'log')
    expect(yOfLevel(range.highDb, range, box)).toBe(box.top)
    expect(yOfLevel(range.lowDb, range, box)).toBe(box.bottom)
    expect(yOfLevel(500, range, box)).toBe(box.top)
  })
})

describe('a curva', () => {
  it('o traçado começa em M, junta com L e deixa de fora o que o eixo logarítmico não mostra', () => {
    const range = spectrumRange(curve(), 'log')
    const path = curvePath(curve(), 'log', range, box)
    expect(path.startsWith('M')).toBe(true)
    expect(path.match(/L/g)).toHaveLength(3) // 500, 1000, 1500 e 24000 entram; o 0 Hz (o DC) fica de fora
    expect(curvePath(curve(), 'linear', spectrumRange(curve(), 'linear'), box).match(/L/g)).toHaveLength(4)
  })

  it('o nível numa frequência é interpolado entre as divisões vizinhas', () => {
    expect(levelAt(curve(), 1000)).toBe(-6)
    expect(levelAt(curve(), 750)).toBeCloseTo(-38, 6)
    expect(levelAt(curve(), -5)).toBe(-90)
    expect(levelAt(curve(), 99999)).toBe(-90)
    expect(levelAt({ frequencies: [], levels_db: [], points_total: 0 }, 100)).toBe(-Infinity)
  })
})

describe('as notas', () => {
  it('lá 4 é 440 Hz e o dó central vem do número MIDI', () => {
    expect(noteOf(440)?.name).toBe('Lá4')
    expect(noteOf(440)?.cents).toBeCloseTo(0, 6)
    expect(noteOf(261.63)?.name).toBe('Dó4')
    expect(noteOf(466.16)?.name).toBe('Lá#4')
    expect(noteOf(1000)?.name).toBe('Si5')
  })

  it('diz quantos cents a frequência dista da nota', () => {
    const flat = noteOf(430)
    expect(flat?.name).toBe('Lá4')
    expect(flat!.cents).toBeLessThan(-30)
    expect(formatNote(noteOf(1000)!)).toBe('Si5 +21 cents')
    expect(formatNote({ name: 'Lá4', cents: -12.4 })).toBe('Lá4 -12 cents')
  })

  it('outra afinação muda a nota mais próxima, e o DC não tem nota', () => {
    expect(noteOf(432, 432)?.cents).toBeCloseTo(0, 6)
    expect(noteOf(0)).toBeNull()
    expect(noteOf(-10)).toBeNull()
    expect(noteOf(Number.NaN)).toBeNull()
  })
})

describe('rótulos e grade', () => {
  it('escreve as frequências e os níveis em português', () => {
    expect(formatHz(440)).toBe('440 Hz')
    expect(formatHz(1500)).toBe('1,5 kHz')
    expect(formatHz(12.34)).toBe('12,3 Hz')
    expect(formatDb(-6)).toBe('-6,0 dB')
  })

  it('a grade logarítmica segue a sequência 1-2-5 dentro do eixo', () => {
    const range = spectrumRange(curve(), 'log')
    expect(frequencyTicks('log', range)).toEqual([20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000])
    expect(frequencyTicks('log', { ...range, highHz: 3000 })).toEqual([20, 50, 100, 200, 500, 1000, 2000])
  })

  it('a grade linear usa números redondos e começa em zero', () => {
    const ticks = frequencyTicks('linear', spectrumRange(curve(), 'linear'))
    expect(ticks[0]).toBe(0)
    expect(ticks.length).toBeGreaterThanOrEqual(4)
    expect(ticks.length).toBeLessThanOrEqual(9)
    expect(new Set(ticks.slice(1).map((tick, index) => tick - ticks[index]!)).size).toBe(1)
  })

  it('a grade de nível anda de dez em dez dB', () => {
    expect(levelTicks({ lowHz: 20, highHz: 24000, lowDb: -100, highDb: 0 })).toEqual([
      -100, -90, -80, -70, -60, -50, -40, -30, -20, -10, 0,
    ])
  })
})

describe('de qual item a análise fala', () => {
  it('tira o `.effects` da lista que o painel de filtros edita', () => {
    expect(analysisTargetOf('timeline.2.effects')).toBe('timeline.2')
    expect(analysisTargetOf('audio.voiceover.0.effects')).toBe('audio.voiceover.0')
    expect(analysisTargetOf('audio.music.effects')).toBe('audio.music')
    expect(analysisTargetOf('overlays.1.effects')).toBe('overlays.1')
  })

  it('o master é a saída final já renderizada', () => {
    expect(analysisTargetOf('audio.master_effects')).toBe('output')
  })
})
