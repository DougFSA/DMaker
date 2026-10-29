import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  api,
  errorMessage,
  followJob,
  type CloneVoiceRequest,
  type DesignVoiceRequest,
  type NarrationResult,
  type VoiceDesignOptions,
  type VoiceProfile,
} from '@/api'
import { readStored, writeStored } from '@/lib/storage'
import { LAST_VOICE_KEY } from '@/lib/voice'

/** A amostra de uma voz que acabou de ser gerada, para a biblioteca tocar. */
export interface VoiceSample {
  voiceId: string
  voiceName: string
  url: string
  /** Muda a cada amostra nova, mesmo da mesma voz: o player busca o arquivo de novo e a tela toca outra vez. */
  stamp: number
}

/** Uma amostra em andamento (ou que falhou) de uma voz da biblioteca. */
export interface VoicePreview {
  startedAtMs: number
  /** A etapa que o servidor informou ("fala 1 de 1"). */
  label: string
  /** Vazio enquanto roda; a mensagem quando o job falhou. */
  error: string
}

/**
 * A biblioteca de vozes e a voz escolhida para o roteiro. A Narração (e quem mais precisar de uma voz) lê daqui:
 * `voices` é a lista como a biblioteca a mostra (filtrada pela marca), `selectedVoiceId` é a última voz
 * escolhida em "Usar" ou criada agora, e fica guardada no navegador.
 */
export const useVoiceStore = defineStore('voice', () => {
  const voices = ref<VoiceProfile[]>([])
  const options = ref<VoiceDesignOptions | null>(null)
  const loading = ref(false)
  const failure = ref('')
  /** Marca que filtra a lista; vazio mostra todas as vozes. */
  const brandFilter = ref('')
  const selectedVoiceId = ref(readStored(LAST_VOICE_KEY) ?? '')
  const previews = ref<Record<string, VoicePreview>>({})
  const sample = ref<VoiceSample | null>(null)

  /** A voz escolhida, ou nada se ela foi removida (ou está fora do filtro de marca). */
  const selectedVoice = computed(() => voices.value.find((voice) => voice.id === selectedVoiceId.value) ?? null)

  async function loadOptions(): Promise<void> {
    if (options.value) return
    options.value = await api.voice.designOptions()
  }

  async function loadVoices(): Promise<void> {
    loading.value = true
    failure.value = ''
    try {
      voices.value = await api.voice.list(brandFilter.value || null)
    } catch (error) {
      failure.value = errorMessage(error)
    } finally {
      loading.value = false
    }
  }

  async function setBrandFilter(brand: string): Promise<void> {
    brandFilter.value = brand
    await loadVoices()
  }

  /** Escolhe a voz do roteiro e lembra dela para a próxima vez que a interface abrir. */
  function chooseVoice(voiceId: string): void {
    selectedVoiceId.value = voiceId
    writeStored(LAST_VOICE_KEY, voiceId)
  }

  /** Clona e já escolhe a voz nova; a lista é recarregada porque o filtro de marca pode incluí-la. */
  async function clone(request: CloneVoiceRequest): Promise<VoiceProfile> {
    const profile = await api.voice.clone(request)
    await loadVoices()
    chooseVoice(profile.id)
    return profile
  }

  async function design(request: DesignVoiceRequest): Promise<VoiceProfile> {
    const profile = await api.voice.design(request)
    await loadVoices()
    chooseVoice(profile.id)
    return profile
  }

  async function remove(voiceId: string): Promise<void> {
    await api.voice.remove(voiceId)
    if (selectedVoiceId.value === voiceId) chooseVoice('')
    if (sample.value?.voiceId === voiceId) sample.value = null
    await loadVoices()
  }

  function updatePreview(voiceId: string, change: Partial<VoicePreview>): void {
    const current = previews.value[voiceId]
    if (current) previews.value = { ...previews.value, [voiceId]: { ...current, ...change } }
  }

  /**
   * Gera a amostra curta da voz (um job, que na CPU leva um bom tempo) e a deixa em `sample`. O andamento fica
   * em `previews`, que é também onde a falha aparece; ele vive no store para sobreviver a trocar de tela.
   */
  async function preview(voiceId: string): Promise<void> {
    const running = previews.value[voiceId]
    if (running && !running.error) return
    previews.value = { ...previews.value, [voiceId]: { startedAtMs: Date.now(), label: '', error: '' } }
    try {
      const { job_id } = await api.voice.preview(voiceId)
      const followed = followJob<NarrationResult>(job_id, {
        onProgress: (progress) => updatePreview(voiceId, { label: progress.label ?? '' }),
      })
      const result = await followed.result
      const name = voices.value.find((voice) => voice.id === voiceId)?.name ?? voiceId
      sample.value = { voiceId, voiceName: name, url: result.audio_url, stamp: Date.now() }
      const others = { ...previews.value }
      delete others[voiceId]
      previews.value = others
    } catch (error) {
      updatePreview(voiceId, { error: errorMessage(error) })
    }
  }

  return {
    voices,
    options,
    loading,
    failure,
    brandFilter,
    selectedVoiceId,
    selectedVoice,
    previews,
    sample,
    loadOptions,
    loadVoices,
    setBrandFilter,
    chooseVoice,
    clone,
    design,
    remove,
    preview,
  }
})
