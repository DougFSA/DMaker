import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, errorMessage, followJob, type NarrationResult, type PronunciationEntry } from '@/api'
import {
  canAddPronunciation,
  DEFAULT_PRONUNCIATION_LANGUAGE,
  GLOBAL_SCOPE,
  pronunciationKey,
  pronunciationPreviewText,
  pronunciationRequest,
} from '@/lib/pronunciation'
import { useNarrationStore } from './narration'
import { useToastsStore } from './toasts'

/** A frase com o termo que acabou de ser gerada, para a tela tocar. */
export interface PronunciationSample {
  term: string
  url: string
  /** Muda a cada amostra nova, mesmo do mesmo termo: o player busca o arquivo de novo e a tela toca outra vez. */
  stamp: number
}

/**
 * O dicionário de pronúncia: como a voz fala siglas e nomes, global ou de uma marca. A lista, o que se está
 * escrevendo para adicionar e a amostra de "Ouvir" ficam aqui para sobreviverem a trocar de aba.
 */
export const usePronunciationStore = defineStore('pronunciation', () => {
  const narration = useNarrationStore()
  const toasts = useToastsStore()

  /** O dicionário aberto: vazio é o global, o resto é a chave de uma marca. */
  const brand = ref('')
  const entries = ref<PronunciationEntry[]>([])
  const loading = ref(false)
  const failure = ref('')

  const term = ref('')
  const spoken = ref('')
  const language = ref(DEFAULT_PRONUNCIATION_LANGUAGE)
  const adding = ref(false)

  const listening = ref<Record<string, true>>({})
  const sample = ref<PronunciationSample | null>(null)

  const canAdd = computed(() => canAddPronunciation({ term: term.value, spoken: spoken.value }) && !adding.value)

  async function load(): Promise<void> {
    loading.value = true
    failure.value = ''
    try {
      entries.value = (await api.voice.pronunciation.list(brand.value || null)).entries
    } catch (error) {
      failure.value = errorMessage(error)
    } finally {
      loading.value = false
    }
  }

  async function setBrand(value: string): Promise<void> {
    brand.value = value
    await load()
  }

  async function add(): Promise<boolean> {
    if (!canAdd.value) return false
    const request = pronunciationRequest({ term: term.value, spoken: spoken.value, brand: brand.value, language: language.value })
    adding.value = true
    try {
      entries.value = (await api.voice.pronunciation.add(request)).entries
      term.value = ''
      spoken.value = ''
      toasts.push({ tone: 'success', title: 'Pronúncia salva', description: `"${request.term}" agora se fala "${request.spoken}".` })
      return true
    } catch (error) {
      toasts.push({ tone: 'error', title: 'Não consegui salvar a pronúncia', description: errorMessage(error) })
      return false
    } finally {
      adding.value = false
    }
  }

  /** Tira o termo do dicionário de onde ele vem (o global ou o da marca dona dele). */
  async function remove(entry: PronunciationEntry): Promise<void> {
    try {
      const owner = entry.scope === GLOBAL_SCOPE ? null : entry.scope
      entries.value = (await api.voice.pronunciation.remove(entry.term, owner, entry.language)).entries
    } catch (error) {
      toasts.push({ tone: 'error', title: 'Não consegui remover a pronúncia', description: errorMessage(error) })
    }
  }

  /** Gera uma frase curta com o termo, pela mesma rota da narração, com a voz escolhida na Narração, e a deixa em `sample`. */
  async function listen(entry: PronunciationEntry): Promise<void> {
    const key = pronunciationKey(entry.term, entry.language)
    if (listening.value[key]) return
    listening.value = { ...listening.value, [key]: true }
    try {
      const { job_id } = await api.voice.speak({
        text: pronunciationPreviewText(entry.term, entry.language),
        voice: narration.voiceId || null,
        language: entry.language,
        brand: brand.value || null,
        seed: 1,
      })
      const result = await followJob<NarrationResult>(job_id).result
      sample.value = { term: entry.term, url: result.audio_url, stamp: Date.now() }
    } catch (error) {
      toasts.push({ tone: 'error', title: 'Não consegui gerar a frase', description: errorMessage(error) })
    } finally {
      const others = { ...listening.value }
      delete others[key]
      listening.value = others
    }
  }

  return { brand, entries, loading, failure, term, spoken, language, adding, listening, sample, canAdd, load, setBrand, add, remove, listen }
})
