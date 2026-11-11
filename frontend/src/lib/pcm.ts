/* Contas sobre amostras que a gravação faz no navegador: intercalar canais, o nível de um bloco e o WAV de 16 bits do atalho
   de clonagem. Puras (só Float32Array), para testar sem Web Audio. */
import { levelDb, measureBlock, type MeterReading } from './audioPlayback'

/** Canais separados (um `Float32Array` por canal) em uma sequência intercalada L R L R, o que o servidor recebe. */
export function interleave(channels: readonly Float32Array[]): Float32Array {
  const first = channels[0]
  if (!first) return new Float32Array(0)
  if (channels.length === 1) return first.slice()
  const out = new Float32Array(first.length * channels.length)
  channels.forEach((channel, offset) => {
    for (let index = 0; index < first.length; index += 1) out[index * channels.length + offset] = channel[index] ?? 0
  })
  return out
}

/** O pico e o valor eficaz de cada canal de um bloco, na forma que o medidor lê. O clipping é pico em 0 dBFS ou acima. */
export function readLevels(channels: readonly Float32Array[]): MeterReading[] {
  return channels.map((samples) => {
    const { peak, rms } = measureBlock(samples)
    return { peakDb: levelDb(peak), rmsDb: levelDb(rms), clipped: peak >= 0.999 }
  })
}

/** O pico mais alto entre os canais de um bloco, em dBFS: o que o gatilho por som compara com o limiar. */
export function blockPeakDb(channels: readonly Float32Array[]): number {
  let peak = 0
  for (const samples of channels) peak = Math.max(peak, measureBlock(samples).peak)
  return levelDb(peak)
}

/** Une pedaços de um canal só. */
export function concat(parts: readonly Float32Array[]): Float32Array {
  const out = new Float32Array(parts.reduce((total, part) => total + part.length, 0))
  let at = 0
  for (const part of parts) {
    out.set(part, at)
    at += part.length
  }
  return out
}

/** O mono de vários canais (média), para a referência de clonagem. */
export function toMono(channels: readonly Float32Array[]): Float32Array {
  const first = channels[0]
  if (!first) return new Float32Array(0)
  if (channels.length === 1) return first.slice()
  const out = new Float32Array(first.length)
  for (let index = 0; index < first.length; index += 1) {
    let sum = 0
    for (const channel of channels) sum += channel[index] ?? 0
    out[index] = sum / channels.length
  }
  return out
}

/** Um WAV PCM de 16 bits mono, little-endian, com o cabeçalho de 44 bytes; o que passa de ±1 é limitado. */
export function encodeWav16(samples: Float32Array, rate: number): ArrayBuffer {
  const bytes = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(bytes)
  const text = (offset: number, value: string) => {
    for (let index = 0; index < value.length; index += 1) view.setUint8(offset + index, value.charCodeAt(index))
  }
  text(0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  text(8, 'WAVE')
  text(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, 1, true) // mono
  view.setUint32(24, rate, true)
  view.setUint32(28, rate * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  text(36, 'data')
  view.setUint32(40, samples.length * 2, true)
  samples.forEach((value, index) => {
    const clipped = Math.max(-1, Math.min(1, value))
    view.setInt16(44 + index * 2, Math.round(clipped * 32767), true)
  })
  return bytes
}
