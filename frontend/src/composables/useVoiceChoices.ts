import { computed, onMounted, ref } from 'vue'
import { api, errorMessage, type VoiceProfile } from '@/api'
import type { SelectOption } from '@/components/ui/AppSelect.vue'
import { voiceLabel } from '@/lib/speech'

/** As vozes da biblioteca em forma de opções de um seletor, lidas ao abrir a tela (a biblioteca muda em outra aba). */
export function useVoiceChoices() {
  const voices = ref<VoiceProfile[]>([])
  const loading = ref(false)
  const error = ref('')

  const options = computed<SelectOption[]>(() => voices.value.map((voice) => ({ value: voice.id, label: voiceLabel(voice) })))

  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      voices.value = await api.voice.list()
    } catch (failure) {
      voices.value = []
      error.value = errorMessage(failure)
    } finally {
      loading.value = false
    }
  }

  onMounted(() => void load())

  return { voices, options, loading, error, reload: load }
}
