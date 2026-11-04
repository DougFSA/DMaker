/* O desenho da onda e da régua do painel Áudio num canvas 2D. Recebe o contexto e os números já calculados
   (`audioWave.ts`); não lê o documento nem o store, então cabe num teste com um contexto falso. As cores vêm de fora,
   lidas das variáveis de tema pelo componente, para a onda acompanhar o tema claro e o escuro. */
import type { AudioWave } from '@/api'
import { columnExtent, timeToX, type AxisView, type Tick } from './audioWave'

export interface WaveColors {
  wave: string
  /** O meio da onda (a linha do zero) e a grade. */
  line: string
  /** O que ainda não foi calculado (a construção em andamento) e o que fica antes de o item começar a soar. */
  pending: string
  text: string
  /** As amostras no zoom máximo. */
  sample: string
}

export interface ChannelsInput {
  data: AudioWave | null
  view: AxisView
  width: number
  height: number
  channels: number
  colors: WaveColors
}

/** A altura de cada canal, com 2 px de respiro entre eles. */
export function channelBand(index: number, channels: number, height: number): { top: number; height: number } {
  const gap = 2
  const band = (height - gap * (channels - 1)) / channels
  return { top: index * (band + gap), height: band }
}

function clear(ctx: CanvasRenderingContext2D, width: number, height: number): void {
  ctx.clearRect(0, 0, width, height)
}

/** Desenha os canais: uma barra de mínimo a máximo por coluna e, no zoom máximo, as amostras ligadas por uma linha. */
export function drawChannels(ctx: CanvasRenderingContext2D, input: ChannelsInput): void {
  const { data, view, width, height, channels, colors } = input
  clear(ctx, width, height)
  for (let channel = 0; channel < channels; channel += 1) {
    const band = channelBand(channel, channels, height)
    ctx.fillStyle = colors.line
    ctx.fillRect(0, Math.round(band.top + band.height / 2), width, 1)
    if (!data) continue
    const mins = data.mins[channel]
    const maxs = data.maxs[channel]
    if (!mins || !maxs) continue
    if (data.mode === 'samples' && data.samples?.[channel]) {
      drawSamples(ctx, data, data.samples[channel] as number[], channel, view, width, band, colors)
    } else {
      drawColumns(ctx, data, mins, maxs, view, width, band, colors)
    }
  }
  if (data && data.state !== 'ready') {
    // a parte que a construção ainda não leu fica de fora: a tela mostra o que há e o resto tracejado
    const from = Math.max(timeToX(data.ready_until, view, width), 0)
    if (from < width) {
      ctx.fillStyle = colors.pending
      ctx.fillRect(from, 0, width - from, height)
    }
  }
}

function drawColumns(
  ctx: CanvasRenderingContext2D,
  data: AudioWave,
  mins: number[],
  maxs: number[],
  view: AxisView,
  width: number,
  band: { top: number; height: number },
  colors: WaveColors,
): void {
  const columns = data.columns
  if (columns <= 0) return
  const step = (data.end - data.start) / columns
  ctx.fillStyle = colors.wave
  for (let index = 0; index < columns; index += 1) {
    const x0 = timeToX(data.start + index * step, view, width)
    const x1 = timeToX(data.start + (index + 1) * step, view, width)
    if (x1 < 0 || x0 > width) continue
    const extent = columnExtent(mins[index] ?? 0, maxs[index] ?? 0, band.height)
    const left = Math.floor(x0)
    ctx.fillRect(left, band.top + extent.top, Math.max(1, Math.ceil(x1) - left), extent.bottom - extent.top)
  }
}

/** Quando as amostras ficam espaçadas o bastante, cada uma ganha um ponto e uma haste até o zero (como no Audacity). */
export const SAMPLE_DOT_MIN_PIXELS = 6

function drawSamples(
  ctx: CanvasRenderingContext2D,
  data: AudioWave,
  samples: number[],
  channel: number,
  view: AxisView,
  width: number,
  band: { top: number; height: number },
  colors: WaveColors,
): void {
  const first = Math.round(data.start * data.rate) / data.rate
  const half = band.height / 2
  const middle = band.top + half
  const spacing = timeToX(first + 1 / data.rate, view, width) - timeToX(first, view, width)
  ctx.strokeStyle = colors.wave
  ctx.fillStyle = colors.sample
  ctx.lineWidth = 1.25
  ctx.beginPath()
  samples.forEach((value, index) => {
    const x = timeToX(first + index / data.rate, view, width)
    const y = middle - Math.max(-1, Math.min(1, value)) * half
    if (index === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  })
  ctx.stroke()
  if (spacing < SAMPLE_DOT_MIN_PIXELS) return
  samples.forEach((value, index) => {
    const x = timeToX(first + index / data.rate, view, width)
    if (x < -4 || x > width + 4) return
    const y = middle - Math.max(-1, Math.min(1, value)) * half
    ctx.fillRect(x - 0.5, Math.min(y, middle), 1, Math.abs(y - middle))
    ctx.beginPath()
    ctx.arc(x, y, 2.5, 0, Math.PI * 2)
    ctx.fill()
  })
  void channel
}

/** A régua: o tempo em cima e, quando a janela é pequena, as amostras embaixo. */
export function drawRuler(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  time: readonly Tick[],
  samples: readonly Tick[],
  colors: WaveColors,
): void {
  clear(ctx, width, height)
  ctx.font = '11px system-ui, sans-serif'
  ctx.textBaseline = 'top'
  ctx.fillStyle = colors.line
  ctx.fillRect(0, height - 1, width, 1)
  ctx.fillStyle = colors.text
  const rows = samples.length > 0 ? 2 : 1
  const rowHeight = (height - 1) / rows
  for (const tick of time) {
    ctx.fillRect(Math.round(tick.x), 0, 1, rowHeight * 0.45)
    ctx.fillText(tick.label, Math.round(tick.x) + 3, 1)
  }
  for (const tick of samples) {
    ctx.fillRect(Math.round(tick.x), rowHeight, 1, rowHeight * 0.45)
    ctx.fillText(tick.label, Math.round(tick.x) + 3, rowHeight + 1)
  }
}
