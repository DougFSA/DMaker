/* O transporte do player: play, pause, velocidade, volume e o relógio que anda o cursor da linha do tempo.
   O relógio é o `requestAnimationFrame`: a cada quadro o cursor avança o tempo real vezes a velocidade. A posição
   mora no store do editor (`playhead`), para a linha do tempo, os filtros e a narração lerem a mesma. */
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { bumpedRate, MAX_SPEED_LEVEL, rateLabel } from '@/lib/player'
import { readStored, writeStored } from '@/lib/storage'
import { useEditorStore } from './editor'

const VOLUME_KEY = 'dmaker.editor.volume'

/** De onde vêm o relógio e os quadros: o navegador, ou um relógio falso nos testes. */
export interface Scheduler {
  now(): number
  request(callback: (timestamp: number) => void): number
  cancel(handle: number): void
}

const browserScheduler: Scheduler = {
  now: () => performance.now(),
  request: (callback) => requestAnimationFrame(callback),
  cancel: (handle) => cancelAnimationFrame(handle),
}

let scheduler: Scheduler = browserScheduler

/** Troca o relógio do player (os testes); sem argumento volta ao do navegador. */
export function useScheduler(next?: Scheduler): void {
  scheduler = next ?? browserScheduler
}

function storedVolume(): number {
  const value = Number(readStored(VOLUME_KEY))
  return readStored(VOLUME_KEY) !== null && Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 1
}

export const usePlayerStore = defineStore('player', () => {
  const editor = useEditorStore()

  /** A velocidade do relógio: 0 parado, 1 normal, negativo voltando (o J). */
  const rate = ref(0)
  /** O volume geral do player, de 0 a 1 (vale para a mixagem e para o som ao vivo). */
  const volume = ref(storedVolume())

  const playing = computed(() => rate.value !== 0)
  const label = computed(() => rateLabel(rate.value))

  let handle: number | null = null
  let lastTimestamp: number | null = null

  function tick(timestamp: number): void {
    const total = editor.total
    if (lastTimestamp !== null && rate.value !== 0) {
      const next = editor.playhead + ((timestamp - lastTimestamp) / 1000) * rate.value
      if (next <= 0) {
        editor.setPlayhead(0)
        rate.value = 0
      } else if (next >= total) {
        editor.setPlayhead(total)
        rate.value = 0
      } else {
        editor.setPlayhead(next)
      }
    }
    lastTimestamp = timestamp
    handle = rate.value !== 0 ? scheduler.request(tick) : null
  }

  function ensureLoop(): void {
    if (handle !== null) return
    lastTimestamp = null
    handle = scheduler.request(tick)
  }

  /** Anda na velocidade dada (0 para). */
  function setRate(next: number): void {
    rate.value = next
    if (next !== 0) ensureLoop()
  }

  /** Toca a 1x. No fim do vídeo, recomeça do início. */
  function play(): void {
    if (editor.total > 0 && editor.playhead >= editor.total) editor.setPlayhead(0)
    setRate(1)
  }

  function pause(): void {
    rate.value = 0
  }

  function toggle(): void {
    if (playing.value) pause()
    else play()
  }

  /** O J e o L: o primeiro toque anda a 1x, repetir na mesma direção dobra até 8x, a outra direção volta a 1x. */
  function bump(direction: -1 | 1): void {
    setRate(bumpedRate(direction, rate.value))
  }

  /** Vai para o instante `seconds` sem parar nem começar a tocar. */
  function seek(seconds: number): void {
    editor.setPlayhead(seconds)
  }

  /** Para e anda alguns quadros (negativo volta). */
  function stepFrame(frames: number): void {
    pause()
    const fps = editor.view?.fps || 30
    editor.setPlayhead(editor.playhead + frames / fps)
  }

  function goStart(): void {
    seek(0)
  }

  function goEnd(): void {
    pause()
    seek(editor.total)
  }

  function setVolume(next: number): void {
    volume.value = Math.min(1, Math.max(0, next))
    writeStored(VOLUME_KEY, String(volume.value))
  }

  // trocar de projeto (ou fechar o editor) para o relógio: o cursor do projeto novo começa parado
  watch(
    () => editor.name,
    () => pause(),
  )

  return {
    rate,
    volume,
    playing,
    label,
    maxLevel: MAX_SPEED_LEVEL,
    setRate,
    play,
    pause,
    toggle,
    bump,
    seek,
    stepFrame,
    goStart,
    goEnd,
    setVolume,
  }
})
