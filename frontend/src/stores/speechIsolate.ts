import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, type IsolationResult } from '@/api'
import type { PickedMedia } from '@/components/media/MediaPicker.vue'
import { rangeProblem } from '@/lib/speech'
import { createJobRun } from './jobRun'

/** O que Isolar voz mostra depois do trabalho: as duas saídas e de qual arquivo elas vieram. */
export interface IsolateOutcome extends IsolationResult {
  sourceName: string
  /** Muda a cada resultado, para o navegador buscar de novo um arquivo regravado no mesmo endereço. */
  stamp: number
}

/** Isolar voz: o formulário, o trabalho e as duas saídas ficam aqui para sobreviver a trocar de aba da Voz. */
export const useIsolateStore = defineStore('speechIsolate', () => {
  const media = ref<PickedMedia | null>(null)
  const start = ref<number | null>(null)
  const end = ref<number | null>(null)
  // o seletor trabalha com texto; só 'mp3' muda o formato, qualquer outra coisa fica no padrão
  const format = ref('wav')
  const job = createJobRun<IsolationResult>()
  const outcome = ref<IsolateOutcome | null>(null)

  const problem = computed(() => rangeProblem(start.value, end.value))
  const canRun = computed(() => !!media.value && !problem.value && !job.running)

  async function run(): Promise<void> {
    const source = media.value
    if (!source || problem.value || job.running) return
    outcome.value = null
    const result = await job.run(() =>
      api.speech.isolate({ path: source.path, start: start.value, end: end.value, format: format.value === 'mp3' ? 'mp3' : 'wav' }),
    )
    if (result) outcome.value = { ...result, sourceName: source.name, stamp: Date.now() }
  }

  return { media, start, end, format, job, outcome, problem, canRun, run }
})
