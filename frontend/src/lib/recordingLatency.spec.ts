import { beforeEach, describe, expect, it } from 'vitest'
import {
  calibrationCorrection,
  compensatedStart,
  findDelay,
  makeClick,
  MIN_CALIBRATION_CONFIDENCE,
  PreviewClock,
  readCalibration,
  totalLatency,
  webAudioLatency,
  writeCalibration,
} from './recordingLatency'

const RATE = 48000

/** O clique tocado na posição `p` da prévia e gravado `delay` segundos depois, dentro de uma gravação com ruído. */
function recordedClick(click: Float32Array, atIndex: number, length: number, noise = 0.002): Float32Array {
  const out = new Float32Array(length)
  let seed = 7
  for (let index = 0; index < length; index += 1) {
    seed = (seed * 1664525 + 1013904223) % 4294967296
    out[index] = (seed / 4294967296 - 0.5) * noise
  }
  click.forEach((value, offset) => {
    out[atIndex + offset] = (out[atIndex + offset] ?? 0) + value * 0.3
  })
  return out
}

describe('a latência da Web Audio', () => {
  it('soma entrada, base e saída; o que o navegador não informa conta zero', () => {
    expect(webAudioLatency({ inputLatency: 0.02, baseLatency: 0.01, outputLatency: 0.04 })).toBeCloseTo(0.07, 6)
    expect(webAudioLatency({ baseLatency: 0.01 })).toBeCloseTo(0.01, 6)
    expect(webAudioLatency({ baseLatency: null, outputLatency: undefined })).toBe(0)
    expect(webAudioLatency({ baseLatency: Number.NaN, outputLatency: -1 })).toBe(0)
  })

  it('a correção da calibração soma à estimativa e a latência nunca fica negativa', () => {
    expect(totalLatency(0.07, 0.03)).toBeCloseTo(0.1, 6)
    expect(totalLatency(0.07, -0.2)).toBe(0)
  })

  it('o início da gravação é o instante da prévia menos a latência (pode ficar negativo no começo do vídeo)', () => {
    expect(compensatedStart(10, 0.12)).toBeCloseTo(9.88, 6)
    expect(compensatedStart(0.05, 0.12)).toBeCloseTo(-0.07, 6)
  })
})

describe('o relógio da prévia', () => {
  it('sem leituras ele diz que ainda não está pronto', () => {
    const clock = new PreviewClock()
    expect(clock.ready).toBe(false)
    expect(() => clock.positionAt(1000)).toThrow()
  })

  it('o cursor que só anda a cada quadro de 16,7 ms erra menos de 1 ms depois de um segundo de leituras', () => {
    // a prévia começou em 4 s e toca a 1x; o cursor só é atualizado nos quadros de animação (a cada 16,667 ms)
    const clock = new PreviewClock()
    const trueAt = (ms: number) => 4 + ms / 1000
    const frame = 1000 / 60
    let worstNaive = 0
    for (let ms = 1000; ms < 2000; ms += 2.7) {
      const lastFrame = Math.floor(ms / frame) * frame
      const reading = trueAt(lastFrame) // o cursor que a página lê: atrasado até um quadro
      clock.add({ nowMs: ms, position: reading })
      worstNaive = Math.max(worstNaive, Math.abs(reading - trueAt(ms)))
    }
    expect(worstNaive).toBeGreaterThan(0.015) // ler o cursor direto erra até um quadro
    expect(Math.abs(clock.positionAt(2000) - trueAt(2000))).toBeLessThan(0.001)
  })
})

describe('achar o atraso do clique por correlação', () => {
  const click = makeClick(RATE)

  it('o clique tem uns 4 ms, começa e termina em zero', () => {
    expect(click.length).toBe(192)
    expect(Math.abs(click[0] ?? 1)).toBeLessThan(0.01)
    expect(Math.abs(click[click.length - 1] ?? 1)).toBeLessThan(0.01)
  })

  it('acha o índice exato do clique numa gravação com ruído', () => {
    const recorded = recordedClick(click, 12345, RATE)
    const found = findDelay(click, recorded, RATE, 0.9)
    expect(found).not.toBeNull()
    expect((found?.seconds ?? 0) * RATE).toBeCloseTo(12345, 0)
    expect(found?.confidence ?? 0).toBeGreaterThan(0.8)
  })

  it('o volume com que o microfone ouviu o clique não muda onde ele está', () => {
    const quiet = new Float32Array(click.length).map((_, index) => (click[index] ?? 0) * 0.05)
    const found = findDelay(click, recordedClick(quiet, 20000, RATE), RATE, 0.9)
    expect(Math.round((found?.seconds ?? 0) * RATE)).toBe(20000)
  })

  it('sem clique na gravação a confiança fica abaixo do mínimo (ruído puro)', () => {
    const noise = recordedClick(new Float32Array(0), 0, RATE, 0.2)
    const found = findDelay(click, noise, RATE, 0.9)
    expect(found === null || found.confidence < MIN_CALIBRATION_CONFIDENCE).toBe(true)
  })

  it('gravação silenciosa ou curta demais devolve nada', () => {
    expect(findDelay(click, new Float32Array(RATE), RATE)).toBeNull()
    expect(findDelay(click, new Float32Array(10), RATE)).toBeNull()
  })
})

describe('um clique gravado sobre um clique da prévia cai no mesmo instante (±10 ms) depois da compensação', () => {
  /**
   * O caminho completo, em números. A prévia toca um clique em `p` = 12,000 s; o alto-falante o solta `saída` depois, o
   * microfone o capta e o navegador entrega o bloco `entrada` depois. A pessoa "grava um clique" ao ouvir o da prévia. A
   * gravação começou (o primeiro quadro chegou à página) quando a prévia marcava `t0`.
   */
  const trueInput = 0.031 // do microfone à página (o navegador não informa tudo)
  const trueOutput = 0.082 // do destino ao ar
  const clickAt = 12.0
  const t0 = 10.0

  /** Onde o clique cai na linha do tempo se o item da gravação começa em `itemStart`. */
  function landing(itemStart: number): number {
    // o clique do ar chega ao arquivo no quadro (p + saída + entrada - t0)·taxa; o item mostra o arquivo a partir de itemStart
    const index = Math.round((clickAt + trueOutput + trueInput - t0) * RATE)
    return itemStart + index / RATE
  }

  it('sem compensar o clique cai atrasado pela latência inteira', () => {
    expect(Math.abs(landing(t0) - clickAt)).toBeCloseTo(trueInput + trueOutput, 2)
  })

  it('só com a estimativa da Web Audio (que não vê tudo) o erro cai mas pode passar de 10 ms', () => {
    const estimate = webAudioLatency({ baseLatency: 0.01, outputLatency: 0.06, inputLatency: 0 })
    const error = Math.abs(landing(compensatedStart(t0, estimate)) - clickAt)
    expect(error).toBeGreaterThan(0.01)
  })

  it('depois da calibração, em sinal sintético, o clique cai a menos de 10 ms', () => {
    const estimate = webAudioLatency({ baseLatency: 0.01, outputLatency: 0.06, inputLatency: 0 })
    // a calibração toca o clique no contexto em 0,400 s e o grava; o clique volta pelo caminho todo
    const playedAt = 0.4
    const arrives = playedAt + trueOutput + trueInput
    const recorded = recordedClick(makeClick(RATE), Math.round(arrives * RATE), Math.round(1.6 * RATE))
    const found = findDelay(makeClick(RATE), recorded, RATE, 1.4)
    expect(found).not.toBeNull()
    const measured = (found?.seconds ?? 0) - playedAt // o primeiro bloco chegou em 0
    const correction = calibrationCorrection(measured, estimate)
    const itemStart = compensatedStart(t0, totalLatency(estimate, correction))
    expect(Math.abs(landing(itemStart) - clickAt)).toBeLessThan(0.01)
    expect(Math.abs(landing(itemStart) - clickAt)).toBeLessThan(0.0005) // na verdade, até a amostra
  })

  it('o erro do relógio da prévia (um quadro) também cabe nos 10 ms quando a calibração e o relógio andam juntos', () => {
    const clock = new PreviewClock()
    const frame = 1000 / 60
    for (let ms = 500; ms < 1500; ms += 2.9) clock.add({ nowMs: ms, position: t0 + (Math.floor(ms / frame) * frame - 500) / 1000 })
    const measured = trueInput + trueOutput
    const itemStart = compensatedStart(clock.positionAt(500), measured)
    expect(Math.abs(landing(itemStart) - clickAt)).toBeLessThan(0.01)
  })
})

describe('a calibração guardada por dispositivo', () => {
  beforeEach(() => window.localStorage.clear())

  it('guarda a correção de cada dispositivo separada e devolve zero para quem nunca calibrou', () => {
    expect(readCalibration('mic-a')).toBe(0)
    writeCalibration('mic-a', 0.0432)
    writeCalibration('mic-b', -0.01)
    expect(readCalibration('mic-a')).toBeCloseTo(0.0432, 6)
    expect(readCalibration('mic-b')).toBeCloseTo(-0.01, 6)
    expect(readCalibration('')).toBe(0)
  })
})
