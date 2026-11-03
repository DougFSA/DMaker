<script setup lang="ts">
/* Corrigir fala: troca uma palavra ou frase dita errado pela certa, na voz do próprio falante, sem gravar de novo.
   Três passos: transcrever o trecho (job), clicar na primeira e na última palavra a trocar e escrever o que deve
   ser dito (job). No fim, ouvir o antes e o depois e, se o arquivo é de um projeto, usar a correção nele. */
import { computed, ref } from 'vue'
import MediaPicker from '@/components/media/MediaPicker.vue'
import JobRunStatus from '@/components/speech/JobRunStatus.vue'
import TimeRangeFields from '@/components/speech/TimeRangeFields.vue'
import UseInProject from '@/components/speech/UseInProject.vue'
import WordPicker from '@/components/speech/WordPicker.vue'
import AbCompare from '@/components/ui/AbCompare.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppCheckbox from '@/components/ui/AppCheckbox.vue'
import AppInput from '@/components/ui/AppInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import DownloadButton from '@/components/ui/DownloadButton.vue'
import { useVoiceChoices } from '@/composables/useVoiceChoices'
import { describeFix, downloadUrl } from '@/lib/speech'
import { useFixSpeechStore } from '@/stores/speechFix'

const fix = useFixSpeechStore()
const voices = useVoiceChoices()
// depois de "Usar no projeto" a mídia do projeto mudou: remontar o seletor a lê de novo
const pickerKey = ref(0)

const voiceHint = computed(() => voices.error.value || 'Sem escolher, a correção fala com a voz de quem está falando no arquivo.')
</script>

<template>
  <div class="tool">
    <AppCard
      title="Corrigir fala"
      subtitle="Troca uma palavra ou frase dita errado pela fala certa, na voz do próprio falante, sem gravar de novo. O resto do arquivo e a duração ficam como estão. Na CPU leva alguns minutos."
    >
      <form class="form" @submit.prevent="fix.transcribe()">
        <MediaPicker :key="pickerKey" v-model="fix.media" label="Arquivo" />
        <TimeRangeFields
          v-model:start="fix.from"
          v-model:end="fix.to"
          start-label="Transcrever de (s, opcional)"
          end-label="até (s, opcional)"
          :step="1"
          :disabled="fix.transcription.running"
        />
        <p class="hint">Em vídeos longos, transcreva só o pedaço onde está o erro: é bem mais rápido.</p>
        <div class="actions">
          <AppButton type="submit" variant="primary" :loading="fix.transcription.running" :disabled="!fix.canTranscribe">
            Transcrever
          </AppButton>
        </div>
        <JobRunStatus :job="fix.transcription" title="Transcrever" />
      </form>
    </AppCard>

    <AppCard v-if="fix.transcript" title="Escolha o trecho a trocar" :subtitle="`Transcrição de ${fix.transcript.name}`">
      <p v-if="fix.transcript.words.length === 0" class="empty" role="status">Nenhuma fala encontrada nesse trecho.</p>
      <WordPicker
        v-else
        v-model="fix.selection"
        :words="fix.transcript.words"
        :pause-seconds="fix.transcript.pauseSeconds"
      />
    </AppCard>

    <AppCard v-if="fix.transcript && fix.transcript.words.length > 0" title="Texto novo">
      <form class="form" @submit.prevent="fix.correct()">
        <AppInput v-model="fix.text" label="O que deve ser dito no lugar" placeholder="Ex.: Pedro" />
        <div class="grid">
          <AppSelect
            v-model="fix.voice"
            label="Voz"
            placeholder="Voz do próprio falante (automática)"
            :options="voices.options.value"
            :hint="voiceHint"
          />
          <AppInput v-model="fix.saveVoiceAs" label="Guardar a voz do falante como (opcional)" placeholder="Ex.: Entrevistado" />
        </div>
        <AppCheckbox v-model="fix.expand" label="Falar também as palavras vizinhas (entonação mais natural)" />
        <div class="actions">
          <AppButton type="submit" variant="primary" :loading="fix.correction.running" :disabled="!fix.canCorrect">
            Corrigir fala
          </AppButton>
        </div>
        <JobRunStatus :job="fix.correction" title="Corrigir fala" />
      </form>
    </AppCard>

    <AppCard v-if="fix.outcome" title="Fala corrigida" :subtitle="`De ${fix.outcome.sourceName}. Ouça o antes e o depois.`">
      <div class="result">
        <p class="summary">{{ describeFix(fix.outcome) }}</p>
        <AbCompare
          kind="audio"
          label="Antes e depois da correção"
          :region="fix.outcome.region"
          :first="{ label: 'Trecho original', src: fix.outcome.original_url }"
          :second="{ label: 'Trecho corrigido', src: fix.outcome.audio_url, refreshKey: fix.outcome.stamp }"
        />
        <div class="actions">
          <DownloadButton label="Baixar corrigido" :url="downloadUrl(fix.outcome.audio_url)" />
          <UseInProject
            :project="fix.outcome.project"
            :entry="fix.outcome.entry"
            :new-path="fix.outcome.output"
            what="arquivo corrigido"
            @used="pickerKey += 1"
          />
        </div>
      </div>
    </AppCard>
  </div>
</template>

<style scoped>
.tool {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  max-width: 48rem;
}

.form,
.result {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 14rem), 1fr));
  gap: var(--space-4);
}

.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}

.hint,
.empty {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.summary {
  font-size: var(--text-md);
  overflow-wrap: anywhere;
}
</style>
