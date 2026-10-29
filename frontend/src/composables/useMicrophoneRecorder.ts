import { computed, inject, onScopeDispose, ref, shallowRef, type InjectionKey } from 'vue'
import {
  createMicrophone,
  MicrophoneError,
  type Microphone,
  type Recording,
  type RecordingHandle,
} from '@/lib/microphone'

export type RecorderPhase = 'idle' | 'recording' | 'recorded'

/** Quem monta a tela entrega outro microfone por aqui (os testes entregam um falso); sem isso vale o do navegador. */
export const microphoneKey: InjectionKey<Microphone> = Symbol('microphone')

/**
 * Estado reativo de uma gravação pelo microfone: o botão vira "Gravar", "Parar" ou "Gravar de novo" conforme a
 * fase, o relógio anda sozinho e a gravação pronta ganha um endereço para tocar. Ao sair da tela, o microfone
 * é solto e a gravação em andamento é descartada.
 */
export function useMicrophoneRecorder(microphone: Microphone = inject(microphoneKey, null) ?? createMicrophone()) {
  const phase = ref<RecorderPhase>('idle')
  const elapsedMs = ref(0)
  const recording = shallowRef<Recording | null>(null)
  const playbackUrl = ref('')
  const error = ref('')
  /** O navegador está pedindo a permissão do microfone: o botão espera a resposta em vez de pedir de novo. */
  const starting = ref(false)
  const supported = microphone.isSupported()
  const recordingNow = computed(() => phase.value === 'recording')

  let handle: RecordingHandle | null = null

  function releasePlayback(): void {
    if (playbackUrl.value) URL.revokeObjectURL(playbackUrl.value)
    playbackUrl.value = ''
  }

  /** Volta ao começo: sem gravação, sem erro, relógio zerado. */
  function discard(): void {
    handle?.cancel()
    handle = null
    releasePlayback()
    recording.value = null
    elapsedMs.value = 0
    error.value = ''
    phase.value = 'idle'
  }

  async function start(): Promise<void> {
    if (phase.value === 'recording' || starting.value) return
    discard()
    let current: RecordingHandle
    starting.value = true
    try {
      current = await microphone.start({ onTick: (elapsed) => (elapsedMs.value = elapsed) })
    } catch (failure) {
      error.value = failure instanceof MicrophoneError ? failure.message : 'A gravação falhou. Tente de novo.'
      return
    } finally {
      starting.value = false
    }
    handle = current
    phase.value = 'recording'
    void settle(current)
  }

  /** Espera a gravação acabar (a pessoa parou, bateu na tampa ou falhou) e guarda o resultado. */
  async function settle(current: RecordingHandle): Promise<void> {
    try {
      const finished = await current.finished
      // outra gravação (ou um descarte) pode ter trocado o handle enquanto esta terminava
      if (handle !== current) return
      recording.value = finished
      elapsedMs.value = finished.durationMs
      playbackUrl.value = URL.createObjectURL(finished.blob)
      phase.value = 'recorded'
    } catch (failure) {
      if (handle !== current) return
      handle = null
      phase.value = 'idle'
      // descartar não é erro: a pessoa pediu, não há o que mostrar
      if (failure instanceof MicrophoneError && failure.reason === 'cancelled') return
      error.value = failure instanceof MicrophoneError ? failure.message : 'A gravação falhou. Tente de novo.'
    }
  }

  /** Pede para parar; a fase muda para "gravada" quando o arquivo chega. */
  function stop(): void {
    handle?.stop()
  }

  onScopeDispose(() => {
    handle?.cancel()
    releasePlayback()
  })

  return { phase, recordingNow, elapsedMs, recording, playbackUrl, error, starting, supported, start, stop, discard }
}
