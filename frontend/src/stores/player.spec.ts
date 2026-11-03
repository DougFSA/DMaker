import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { openEditor } from '@/test/editorMount'
import { usePlayerStore, useScheduler } from './player'

/** Um relógio de quadros de mentira: o teste decide quando cada quadro chega e que horas são. */
class FakeFrames {
  private callbacks = new Map<number, (timestamp: number) => void>()
  private next = 1

  now = () => 0
  request = (callback: (timestamp: number) => void) => {
    const handle = this.next++
    this.callbacks.set(handle, callback)
    return handle
  }
  cancel = (handle: number) => void this.callbacks.delete(handle)

  get pending(): number {
    return this.callbacks.size
  }

  /** Entrega o próximo quadro com o carimbo de tempo dado (ms). */
  frame(timestamp: number): void {
    const [handle, callback] = [...this.callbacks.entries()][0] ?? []
    if (handle === undefined || !callback) throw new Error('nenhum quadro pedido')
    this.callbacks.delete(handle)
    callback(timestamp)
  }
}

let frames: FakeFrames

beforeEach(() => {
  frames = new FakeFrames()
  useScheduler(frames)
  window.localStorage.clear()
})

afterEach(() => {
  useScheduler()
  vi.unstubAllGlobals()
})

async function openPlayer() {
  const opened = await openEditor() // a vista de 6 s, 30 fps
  return { ...opened, player: usePlayerStore() }
}

describe('transporte', () => {
  it('começa parado, no início, com o volume cheio', async () => {
    const { player, store } = await openPlayer()
    expect(player.rate).toBe(0)
    expect(player.playing).toBe(false)
    expect(player.volume).toBe(1)
    expect(player.label).toBe('Pausado')
    expect(store.playhead).toBe(0)
  })

  it('tocar anda o cursor o tempo real que passou, quadro a quadro', async () => {
    const { player, store } = await openPlayer()
    player.play()
    expect(player.playing).toBe(true)
    frames.frame(1000) // o primeiro quadro só marca a hora
    expect(store.playhead).toBe(0)
    frames.frame(1500)
    expect(store.playhead).toBeCloseTo(0.5)
    frames.frame(2250)
    expect(store.playhead).toBeCloseTo(1.25)
    expect(frames.pending).toBe(1) // o relógio segue pedindo quadros enquanto toca
  })

  it('pausar para o relógio e o cursor fica onde estava', async () => {
    const { player, store } = await openPlayer()
    player.play()
    frames.frame(0)
    frames.frame(1000)
    player.pause()
    frames.frame(2000)
    expect(store.playhead).toBeCloseTo(1)
    expect(frames.pending).toBe(0)
    expect(player.label).toBe('Pausado')
  })

  it('no fim do vídeo para sozinho e tocar de novo recomeça do início', async () => {
    const { player, store } = await openPlayer()
    store.setPlayhead(5.5)
    player.play()
    frames.frame(0)
    frames.frame(1000)
    expect(store.playhead).toBe(6)
    expect(player.playing).toBe(false)
    expect(frames.pending).toBe(0)
    player.play()
    expect(store.playhead).toBe(0)
    expect(player.playing).toBe(true)
  })

  it('voltando (o J), chega ao início e para', async () => {
    const { player, store } = await openPlayer()
    store.setPlayhead(0.5)
    player.bump(-1)
    expect(player.rate).toBe(-1)
    frames.frame(0)
    frames.frame(1000)
    expect(store.playhead).toBe(0)
    expect(player.playing).toBe(false)
  })

  it('J e L dobram a velocidade até 8x e K para', async () => {
    const { player } = await openPlayer()
    player.bump(1)
    expect(player.label).toBe('1x')
    player.bump(1)
    player.bump(1)
    player.bump(1)
    player.bump(1)
    expect(player.rate).toBe(8)
    player.bump(-1)
    expect(player.rate).toBe(-1)
    player.pause()
    expect(player.rate).toBe(0)
  })

  it('a velocidade escala o avanço do cursor', async () => {
    const { player, store } = await openPlayer()
    player.bump(1)
    player.bump(1) // 2x
    frames.frame(0)
    frames.frame(1000)
    expect(store.playhead).toBeCloseTo(2)
  })

  it('quadro a quadro para o relógio e anda 1/fps', async () => {
    const { player, store } = await openPlayer()
    player.play()
    player.stepFrame(1)
    expect(player.playing).toBe(false)
    expect(store.playhead).toBeCloseTo(1 / 30)
    player.stepFrame(-1)
    expect(store.playhead).toBeCloseTo(0)
    player.stepFrame(-5)
    expect(store.playhead).toBe(0) // não passa do início
  })

  it('ir ao início e ao fim', async () => {
    const { player, store } = await openPlayer()
    player.goEnd()
    expect(store.playhead).toBe(6)
    player.goStart()
    expect(store.playhead).toBe(0)
    player.seek(99)
    expect(store.playhead).toBe(6)
  })

  it('alternar entre tocar e pausar', async () => {
    const { player } = await openPlayer()
    player.toggle()
    expect(player.playing).toBe(true)
    player.toggle()
    expect(player.playing).toBe(false)
  })

  it('fechar o projeto para o relógio', async () => {
    const { player, store } = await openPlayer()
    player.play()
    store.close()
    await nextTick()
    expect(player.playing).toBe(false)
  })
})

describe('volume', () => {
  it('fica entre 0 e 1 e é lembrado para a próxima vez', async () => {
    const { player } = await openPlayer()
    player.setVolume(0.35)
    expect(player.volume).toBe(0.35)
    player.setVolume(7)
    expect(player.volume).toBe(1)
    player.setVolume(-1)
    expect(player.volume).toBe(0)
    expect(window.localStorage.getItem('dmaker.editor.volume')).toBe('0')
  })

  it('volta ao que foi guardado', async () => {
    window.localStorage.setItem('dmaker.editor.volume', '0.4')
    const { player } = await openPlayer()
    expect(player.volume).toBe(0.4)
  })
})
