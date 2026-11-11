/* O atalho de clonagem: grava 15 s do microfone com o texto da folha de gravação na tela e manda o WAV direto para a
   clonagem (`POST /api/voices/clone`, o mesmo `clone_voice` da aba Voz), sem passar por arquivo no disco. O texto da
   folha vai como a transcrição da referência, então o Whisper não precisa ouvir de novo. O som fica em memória só até virar
   o WAV desta chamada; nada é gravado no projeto. */
import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'
import { errorMessage } from '@/api'
import type { MeterReading } from '@/lib/audioPlayback'
import { concat, encodeWav16, readLevels, toMono } from '@/lib/pcm'
import { CaptureError, captureEngine, type CaptureSession } from '@/lib/recordingCapture'
import { CLONE_SECONDS, recordingScript } from '@/lib/recordingScript'
import { useToastsStore } from './toasts'
import { useVoiceStore } from './voice'

/** Gravação curta demais não dá referência: o modelo precisa de pelo menos alguns segundos de fala. */
export const MIN_CLONE_SECONDS = 3

export type CloneRecordPhase = 'idle' | 'recording' | 'cloning'

export const useRecordCloneStore = defineStore('recordClone', () => {
  const voices = useVoiceStore()
  const toasts = useToastsStore()

  const phase = ref<CloneRecordPhase>('idle')
  const elapsed = ref(0)
  const levels = shallowRef<MeterReading[]>([])
  const error = ref('')
  const name = ref('')
  const language = ref('pt')
  const brand = ref('')
  const consent = ref(false)
  const deviceId = ref('')

  const script = computed(() => recordingScript(language.value))
  const canStart = computed(() => phase.value === 'idle' && name.value.trim() !== '' && consent.value)

  let session: CaptureSession | null = null
  let samples: Float32Array[] = []

  async function release(): Promise<void> {
    const current = session
    session = null
    levels.value = []
    if (current) {
      current.onBlock = null
      current.onEnded = null
      await current.close()
    }
  }

  /** Grava até `CLONE_SECONDS` (ou até a pessoa parar, se já passou do mínimo) e clona. */
  async function record(): Promise<void> {
    if (!canStart.value) return
    error.value = ''
    elapsed.value = 0
    samples = []
    try {
      session = await captureEngine().open({ deviceId: deviceId.value || undefined, channels: 1, sampleRate: 48000 })
    } catch (failure) {
      error.value = failure instanceof CaptureError ? failure.message : errorMessage(failure)
      return
    }
    const opened = session
    phase.value = 'recording'
    opened.onEnded = (reason) => {
      error.value = reason
      void cancel()
    }
    opened.onBlock = (block) => {
      levels.value = readLevels(block.channels)
      samples.push(block.channels[0] ?? new Float32Array(0))
      const frames = samples.reduce((total, part) => total + part.length, 0)
      elapsed.value = frames / opened.rate
      if (elapsed.value >= CLONE_SECONDS) void finish()
    }
  }

  /** Para antes do tempo; vale se já passou do mínimo. */
  async function stop(): Promise<void> {
    if (phase.value !== 'recording') return
    if (elapsed.value < MIN_CLONE_SECONDS) {
      error.value = `Grave pelo menos ${MIN_CLONE_SECONDS} segundos lendo o texto.`
      return
    }
    await finish()
  }

  async function finish(): Promise<void> {
    const opened = session
    if (phase.value !== 'recording' || !opened) return
    phase.value = 'cloning'
    opened.onBlock = null
    const rate = opened.rate
    const wave = toMono([concat(samples)])
    samples = []
    await release()
    const reference = new Blob([encodeWav16(wave, rate)], { type: 'audio/wav' })
    try {
      const profile = await voices.clone({
        name: name.value.trim(),
        audio: reference,
        filename: 'gravacao.wav',
        reference_text: script.value, // a pessoa leu a folha: o texto é conhecido
        brand: brand.value || null,
        language: language.value,
      })
      toasts.push({
        tone: 'success',
        title: `Voz "${profile.name}" clonada`,
        description: 'Já está na biblioteca de vozes e escolhida para a narração.',
      })
      name.value = ''
      consent.value = false
    } catch (failure) {
      error.value = `Não consegui clonar a voz: ${errorMessage(failure)}`
    } finally {
      phase.value = 'idle'
    }
  }

  async function cancel(): Promise<void> {
    samples = []
    await release()
    phase.value = 'idle'
    elapsed.value = 0
  }

  return { phase, elapsed, levels, error, name, language, brand, consent, deviceId, script, canStart, record, stop, cancel }
})
