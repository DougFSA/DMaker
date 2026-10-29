import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, type ConversionResult } from '@/api'
import type { PickedMedia } from '@/components/media/MediaPicker.vue'
import type { MediaEntry } from '@/lib/media'
import { rangeProblem } from '@/lib/speech'
import { createJobRun } from './jobRun'
import { useWorkspaceStore } from './workspace'

/** O resultado da troca de voz e do arquivo de que ele saiu. */
export interface SwapOutcome extends ConversionResult {
  sourceName: string
  entry: MediaEntry | null
  project: string | null
  /** O trecho pedido (segundos); vazio quando foi o arquivo inteiro. */
  start: number | null
  end: number | null
  stamp: number
}

/** Trocar voz: o formulário, o trabalho e o resultado ficam aqui para sobreviver a trocar de aba da Voz. */
export const useSwapVoiceStore = defineStore('speechSwap', () => {
  const workspace = useWorkspaceStore()

  const media = ref<PickedMedia | null>(null)
  const voice = ref('')
  const start = ref<number | null>(null)
  const end = ref<number | null>(null)
  const job = createJobRun<ConversionResult>()
  const outcome = ref<SwapOutcome | null>(null)

  const problem = computed(() => rangeProblem(start.value, end.value))
  const canRun = computed(() => !!media.value && !!voice.value && !problem.value && !job.running)

  async function run(): Promise<void> {
    const source = media.value
    const chosenVoice = voice.value
    if (!source || !chosenVoice || problem.value || job.running) return
    const range = { start: start.value, end: end.value }
    outcome.value = null
    const result = await job.run(() => api.speech.convert({ path: source.path, voice: chosenVoice, ...range }))
    if (result) {
      outcome.value = {
        ...result,
        sourceName: source.name,
        entry: source.entry,
        project: source.origin === 'project' ? workspace.currentProject : null,
        ...range,
        stamp: Date.now(),
      }
    }
  }

  return { media, voice, start, end, job, outcome, problem, canRun, run }
})
