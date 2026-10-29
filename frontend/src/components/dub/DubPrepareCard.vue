<script setup lang="ts">
/* Preparar a dublagem: escolher o arquivo, os idiomas e as opções, e deixar o programa transcrever e traduzir (job).
   Quem já preparou antes abre a dublagem salva em vez de repetir os minutos de trabalho. */
import { computed, onMounted } from 'vue'
import MediaPicker from '@/components/media/MediaPicker.vue'
import JobRunStatus from '@/components/speech/JobRunStatus.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppInput from '@/components/ui/AppInput.vue'
import AppNumberInput from '@/components/ui/AppNumberInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import { useVoiceChoices } from '@/composables/useVoiceChoices'
import { FIT_MODE_OPTIONS, SPEAKER_MODE_OPTIONS } from '@/lib/dub'
import { useDubbingStore } from '@/stores/dubbing'

defineProps<{
  /** Muda depois de "Usar no projeto": a mídia do projeto mudou e o seletor precisa ler de novo. */
  mediaKey?: number
}>()

const dub = useDubbingStore()
const voices = useVoiceChoices()

const languageOptions = computed(() => dub.languages.map((language) => ({ value: language.value, label: language.label })))
const savedOptions = computed(() => dub.savedProjects.map((saved) => ({ value: saved.path, label: saved.name })))
const perSpeaker = computed(() => dub.speakerMode === 'per_speaker')
const languageError = computed(() => (dub.sameLanguages ? 'O idioma de destino precisa ser diferente do de origem.' : ''))
const voiceHint = computed(() => voices.error.value || 'Sem escolher, o programa clona a voz de quem fala no arquivo.')
const modeOptions = SPEAKER_MODE_OPTIONS.map((option) => ({ ...option }))
const fitOptions = FIT_MODE_OPTIONS.map((option) => ({ ...option }))

onMounted(() => {
  void dub.loadLanguages()
  void dub.loadSaved()
})
</script>

<template>
  <AppCard
    title="Preparar a dublagem"
    subtitle="Traduz a fala de um vídeo ou áudio e a refaz no outro idioma com a voz clonada de quem fala, mantendo a música e o ruído de fundo. Primeiro prepare (transcreve e traduz com o Ollama local), depois revise as traduções e gere. Na CPU leva vários minutos; cada fala sintetizada fica em cache, então corrigir uma tradução refaz só aquela fala."
  >
    <form class="form" @submit.prevent="dub.prepare()">
      <MediaPicker :key="mediaKey" v-model="dub.media" label="Arquivo" />
      <div class="grid">
        <AppSelect
          v-model="dub.sourceLanguage"
          label="Idioma da fala"
          :options="languageOptions"
          :disabled="dub.busy"
        />
        <AppSelect
          v-model="dub.targetLanguage"
          label="Dublar para"
          :options="languageOptions"
          :error="languageError"
          :disabled="dub.busy"
        />
        <AppSelect v-model="dub.speakerMode" label="Modo de voz" :options="modeOptions" :disabled="dub.busy" />
        <AppNumberInput
          v-if="perSpeaker"
          v-model="dub.speakerCount"
          label="Quantas pessoas falam (opcional)"
          placeholder="Vazio: o áudio decide"
          :min="1"
          :max="12"
          :step="1"
          :disabled="dub.busy"
        />
        <AppSelect
          v-model="dub.voice"
          label="Voz da biblioteca (opcional)"
          placeholder="Clonar a voz de quem fala (automático)"
          :options="voices.options.value"
          :hint="voiceHint"
          :disabled="dub.busy"
        />
        <AppNumberInput
          v-model="dub.keepDb"
          label="Voz original por baixo (dB, opcional)"
          placeholder="Ex.: -18"
          hint="Vazio: só a voz dublada. Quanto mais negativo, mais baixa a voz original; o sinal se ajusta sozinho (18 vale -18)."
          unit="dB"
          :step="1"
          :disabled="dub.busy"
        />
        <AppSelect v-model="dub.fitMode" label="Quando a fala não cabe" :options="fitOptions" :disabled="dub.busy" />
        <AppInput
          v-model="dub.glossary"
          label="Termos que não se traduzem (opcional)"
          placeholder="Ex.: DMaker, MedlyCare"
          hint="Separe por vírgula."
          :disabled="dub.busy"
        />
      </div>
      <p v-if="dub.loadError" class="problem" role="alert">{{ dub.loadError }}</p>
      <div class="actions">
        <AppButton type="submit" variant="primary" :loading="dub.preparation.running" :disabled="!dub.canPrepare">
          Preparar (transcrever e traduzir)
        </AppButton>
      </div>
      <JobRunStatus :job="dub.preparation" title="Preparar a dublagem" cancellable @cancel="dub.preparation.cancel()" />
    </form>

    <form class="open" @submit.prevent="dub.openSaved()">
      <AppSelect
        v-model="dub.savedChoice"
        label="Abrir uma dublagem já preparada"
        placeholder="Dublagens salvas..."
        :options="savedOptions"
        :disabled="dub.busy"
      />
      <AppButton type="submit" :disabled="!dub.canOpenSaved">Abrir projeto</AppButton>
    </form>
  </AppCard>
</template>

<style scoped>
.form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 15rem), 1fr));
  gap: var(--space-4);
}

.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}

.open {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--space-3);
  margin-top: var(--space-5);
  padding-top: var(--space-5);
  border-top: 1px solid var(--color-border);
}

.open > :first-child {
  flex: 1 1 18rem;
  min-width: 0;
}

.problem {
  font-size: var(--text-sm);
  color: var(--color-error);
}
</style>
