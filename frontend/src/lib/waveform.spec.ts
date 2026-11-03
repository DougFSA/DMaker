import { describe, expect, it, vi } from 'vitest'
import type { Waveform } from '@/api'
import { timelineItem, timelineView } from '@/test/editorFixtures'
import {
  itemAudioOffset,
  itemAudioRate,
  itemLoops,
  itemPieces,
  itemSourcePath,
  peakIndexAt,
  WaveformCache,
  waveformColumns,
  waveformEligible,
  waveformWindow,
} from './waveform'

describe('quais itens têm forma de onda', () => {
  it('o áudio de clipe, a faixa externa, a música e o vídeo sobreposto', () => {
    expect(waveformEligible({ id: 'A1', kind: 'audio' }, { kind: 'clip-audio' })).toBe(true)
    expect(waveformEligible({ id: 'A2', kind: 'audio' }, { kind: 'track' })).toBe(true)
    expect(waveformEligible({ id: 'MUS', kind: 'audio' }, { kind: 'music' })).toBe(true)
    expect(waveformEligible({ id: 'V2', kind: 'video' }, { kind: 'video' })).toBe(true)
  })

  it('a V1, o texto, os gráficos, a narração e as legendas não', () => {
    expect(waveformEligible({ id: 'V1', kind: 'video' }, { kind: 'clip' })).toBe(false)
    expect(waveformEligible({ id: 'TX', kind: 'text' }, { kind: 'text' })).toBe(false)
    expect(waveformEligible({ id: 'GR', kind: 'graphics' }, { kind: 'image' })).toBe(false)
    expect(waveformEligible({ id: 'NAR', kind: 'audio' }, { kind: 'narration' })).toBe(false)
    expect(waveformEligible({ id: 'CC', kind: 'captions' }, { kind: 'captions' })).toBe(false)
    expect(waveformEligible({ id: 'A1', kind: 'audio' }, { kind: 'track' })).toBe(false)
  })
})

describe('peakIndexAt', () => {
  it('um pico por intervalo, dentro do arquivo', () => {
    expect(peakIndexAt(100, 10, 10, 0, false)).toBe(0)
    expect(peakIndexAt(100, 10, 10, 2.55, false)).toBe(25)
    expect(peakIndexAt(100, 10, 10, 9.99, false)).toBe(99)
  })

  it('fora do trecho gravado, sem loop, não há pico', () => {
    expect(peakIndexAt(100, 10, 10, -0.1, false)).toBe(-1)
    expect(peakIndexAt(100, 10, 10, 10, false)).toBe(-1)
    expect(peakIndexAt(100, 10, 10, 25, false)).toBe(-1)
  })

  it('com loop o arquivo se repete, também para trás', () => {
    expect(peakIndexAt(100, 10, 10, 12.5, true)).toBe(25)
    expect(peakIndexAt(100, 10, 10, -0.5, true)).toBe(95)
  })

  it('o índice nunca passa da lista de picos', () => {
    expect(peakIndexAt(5, 10, 10, 9, false)).toBe(-1)
  })
})

describe('waveformColumns', () => {
  const wave: Waveform = { duration: 4, peaks_per_second: 1, peaks: [0.25, 0.5, 1, 2] }

  it('uma altura por coluna, de 0 a 1, cobrindo o trecho pedido', () => {
    expect([...waveformColumns(4, wave, 0, 4, false)]).toEqual([0.25, 0.5, 1, 1])
  })

  it('colunas fora do arquivo ficam em zero; com loop elas repetem o arquivo', () => {
    expect([...waveformColumns(4, wave, 2, 6, false)]).toEqual([1, 1, 0, 0])
    expect([...waveformColumns(4, wave, 2, 6, true)]).toEqual([1, 1, 0.25, 0.5])
  })

  it('sem picos ou sem largura, nada para desenhar', () => {
    expect(waveformColumns(3, { duration: 0, peaks_per_second: 1, peaks: [] }, 0, 3, false)).toEqual(new Float32Array(3))
    expect(waveformColumns(0, wave, 0, 4, false)).toHaveLength(0)
  })
})

describe('a janela de um item', () => {
  const view = timelineView()

  it('o item inteiro: ponto de entrada mais o avanço, na velocidade do item', () => {
    const item = timelineItem(0, { start: 4, end: 8, in_point: 10, path: 'C:/a.wav', extra: { speed: 2 } })
    const window = waveformWindow(view, item, null)
    expect(window.path).toBe('C:/a.wav')
    expect([window.start, window.end]).toEqual([4, 8])
    expect(window.fileTimeAt(4)).toBe(10)
    expect(window.fileTimeAt(5)).toBe(12)
  })

  it('desconta o deslocamento da fonte sincronizada', () => {
    const synced = { ...view, sources: { mesa: { src: 'mesa.wav', parts: [], offset: 2.5, in_point: 0, path: 'C:/mesa.wav' } } }
    const item = timelineItem(0, { start: 0, end: 5, in_point: 0, source: 'mesa', path: null, src: null })
    const window = waveformWindow(synced, item, null)
    expect(window.path).toBe('C:/mesa.wav')
    expect(window.fileTimeAt(3)).toBe(0.5)
  })

  it('a faixa fatiada traz o próprio deslocamento, que vale em vez do da fonte', () => {
    const synced = { ...view, sources: { mesa: { src: 'mesa.wav', parts: [], offset: 2.5, in_point: 0, path: 'C:/mesa.wav' } } }
    const item = timelineItem(0, { start: 6, end: 9, in_point: 7, source: 'mesa', path: 'C:/mesa.wav', extra: { offset: 0 } })
    expect(waveformWindow(synced, item, null).fileTimeAt(7)).toBe(8)
  })

  it('um pedaço de uma fonte em várias partes desenha o arquivo e o intervalo dele', () => {
    const pieces = [
      { start: 2, end: 5, in_point: 0, path: 'C:/p1.mp4' },
      { start: 5, end: 8, in_point: 1, path: 'C:/p2.mp4' },
    ]
    const item = timelineItem(0, { start: 2, end: 8, extra: { pieces, speed: 1 } })
    const second = waveformWindow(view, item, 1)
    expect(second.path).toBe('C:/p2.mp4')
    expect([second.start, second.end]).toEqual([5, 8])
    expect(second.fileTimeAt(6)).toBe(2)
    expect(itemPieces(item)).toHaveLength(2)
  })

  it('velocidade, deslocamento, loop e caminho têm valores padrão', () => {
    const plain = timelineItem(0, { extra: {}, path: null, src: 'x.wav' })
    expect(itemAudioRate(plain)).toBe(1)
    expect(itemAudioRate(timelineItem(0, { extra: { speed: 0 } }))).toBe(1)
    expect(itemAudioOffset(view, plain)).toBe(0)
    expect(itemLoops(plain)).toBe(false)
    expect(itemLoops(timelineItem(0, { extra: { loop: true } }))).toBe(true)
    expect(itemSourcePath(view, plain)).toBe('x.wav')
    expect(itemSourcePath(view, timelineItem(0, { path: null, src: null, source: 'nenhuma' }))).toBeNull()
  })
})

describe('WaveformCache', () => {
  it('pede cada arquivo uma vez só, mesmo com vários itens esperando ao mesmo tempo', async () => {
    const fetchPeaks = vi.fn().mockResolvedValue({ duration: 1, peaks_per_second: 1, peaks: [0.5] })
    const cache = new WaveformCache(fetchPeaks)
    const [a, b] = await Promise.all([cache.peaks('C:/a.wav'), cache.peaks('C:/a.wav')])
    await cache.peaks('C:/a.wav')
    expect(fetchPeaks).toHaveBeenCalledTimes(1)
    expect(a).toBe(b)
    await cache.peaks('C:/a.wav', 1)
    expect(fetchPeaks).toHaveBeenCalledTimes(2)
  })

  it('erro do servidor vira "sem picos" e não se tenta de novo; sem caminho, nem pede', async () => {
    const fetchPeaks = vi.fn().mockRejectedValue(new Error('sem áudio'))
    const cache = new WaveformCache(fetchPeaks)
    expect(await cache.peaks('C:/mudo.mp4')).toBeNull()
    expect(await cache.peaks('C:/mudo.mp4')).toBeNull()
    expect(await cache.peaks(null)).toBeNull()
    expect(fetchPeaks).toHaveBeenCalledTimes(1)
  })

  it('clear esquece o que já pediu', async () => {
    const fetchPeaks = vi.fn().mockResolvedValue({ duration: 1, peaks_per_second: 1, peaks: [] })
    const cache = new WaveformCache(fetchPeaks)
    await cache.peaks('C:/a.wav')
    cache.clear()
    await cache.peaks('C:/a.wav')
    expect(fetchPeaks).toHaveBeenCalledTimes(2)
  })
})
