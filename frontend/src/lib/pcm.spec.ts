import { describe, expect, it } from 'vitest'
import { blockPeakDb, concat, encodeWav16, interleave, readLevels, toMono } from './pcm'

describe('as contas sobre amostras da gravação', () => {
  it('intercala os canais L R L R, o que o servidor lê', () => {
    const left = Float32Array.from([1, 2, 3])
    const right = Float32Array.from([-1, -2, -3])
    expect([...interleave([left, right])]).toEqual([1, -1, 2, -2, 3, -3])
    expect([...interleave([left])]).toEqual([1, 2, 3])
    expect(interleave([])).toHaveLength(0)
  })

  it('mede o pico e o valor eficaz por canal e acusa clipping', () => {
    const loud = new Float32Array(100).fill(1)
    const half = new Float32Array(100).fill(0.5)
    const [a, b] = readLevels([loud, half])
    expect(a?.clipped).toBe(true)
    expect(a?.peakDb).toBeCloseTo(0, 5)
    expect(b?.clipped).toBe(false)
    expect(b?.peakDb).toBeCloseTo(-6.02, 1)
    expect(b?.rmsDb).toBeCloseTo(-6.02, 1)
  })

  it('o pico do bloco é o maior entre os canais, e o silêncio fica no piso do medidor', () => {
    expect(blockPeakDb([new Float32Array(10).fill(0.1), new Float32Array(10).fill(0.5)])).toBeCloseTo(-6.02, 1)
    expect(blockPeakDb([new Float32Array(10)])).toBe(-60)
  })

  it('une pedaços e faz o mono pela média', () => {
    expect([...concat([Float32Array.from([1, 2]), Float32Array.from([3])])]).toEqual([1, 2, 3])
    expect([...toMono([Float32Array.from([1, 0]), Float32Array.from([0, 1])])]).toEqual([0.5, 0.5])
  })

  it('o WAV de 16 bits tem o cabeçalho certo, limita o que passa de 1 e guarda as amostras', () => {
    const wav = encodeWav16(Float32Array.from([0, 0.5, -0.5, 2, -2]), 24000)
    const view = new DataView(wav)
    const text = (offset: number) => String.fromCharCode(...new Uint8Array(wav, offset, 4))
    expect(text(0)).toBe('RIFF')
    expect(text(8)).toBe('WAVE')
    expect(view.getUint32(24, true)).toBe(24000)
    expect(view.getUint16(22, true)).toBe(1)
    expect(view.getUint16(34, true)).toBe(16)
    expect(view.getUint32(40, true)).toBe(10)
    expect(wav.byteLength).toBe(44 + 10)
    expect([0, 1, 2, 3, 4].map((index) => view.getInt16(44 + index * 2, true))).toEqual([0, 16384, -16383, 32767, -32767])
  })
})
