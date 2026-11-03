<script setup lang="ts">
/* Trocar voz: troca o timbre de uma gravação (ou de um trecho) por uma voz da biblioteca, mantendo as palavras, o
   ritmo, as pausas e o fundo. Não traduz: isso é a Dublagem. Para testar uma voz, converta antes só um trecho. */
import { computed, ref } from 'vue'
import MediaPicker from '@/components/media/MediaPicker.vue'
import JobRunStatus from '@/components/speech/JobRunStatus.vue'
import TimeRangeFields from '@/components/speech/TimeRangeFields.vue'
import UseInProject from '@/components/speech/UseInProject.vue'
import AbCompare from '@/components/ui/AbCompare.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import DownloadButton from '@/components/ui/DownloadButton.vue'
import { useVoiceChoices } from '@/composables/useVoiceChoices'
import { canUseConversion, describeConversion, downloadUrl, formatSeconds } from '@/lib/speech'
import { useSwapVoiceStore } from '@/stores/speechSwap'

const swap = useSwapVoiceStore()
const voices = useVoiceChoices()
// depois de "Usar no projeto" a mídia do projeto mudou: remontar o seletor a lê de novo
const pickerKey = ref(0)

const voiceHint = computed(() => voices.error.value || (voices.loading.value ? 'Lendo as vozes...' : ''))

/** Só um trecho foi trocado: o áudio novo começa em 0 e o original continua inteiro, então a pessoa precisa saber. */
const excerptNote = computed(() => {
  const outcome = swap.outcome
  if (!outcome?.excerpt) return ''
  const from = outcome.start === null ? 'o começo' : `${formatSeconds(outcome.start)} s`
  const until = outcome.end === null ? 'o fim' : `${formatSeconds(outcome.end)} s`
  return `O áudio com a voz trocada é só do trecho de ${from} até ${until} do original, por isso o original toca o arquivo inteiro.`
})

const blockedReason = computed(() => {
  const outcome = swap.outcome
  if (!outcome || canUseConversion(outcome, true)) return ''
  return 'Só o arquivo inteiro pode entrar no projeto. Troque a voz do arquivo todo para usar nele.'
})
</script>

<template>
  <div class="tool">
    <AppCard
      title="Trocar voz"
      subtitle="Troca a voz de uma gravação inteira pela de uma voz da biblioteca (clonada ou desenhada), mantendo as palavras, o ritmo, as pausas e a entonação, e a música e o ruído de fundo. Diferente de Dublar, não traduz: só o timbre muda. Na CPU leva de 1,5 a 2 s por segundo de fala, mais a separação da voz (que fica guardada)."
    >
      <form class="form" @submit.prevent="swap.run()">
        <MediaPicker :key="pickerKey" v-model="swap.media" label="Arquivo" />
        <AppSelect
          v-model="swap.voice"
          label="Voz que vai falar"
          placeholder="Escolha a voz..."
          :options="voices.options.value"
          :hint="voiceHint"
          :disabled="swap.job.running"
        />
        <TimeRangeFields v-model:start="swap.start" v-model:end="swap.end" :disabled="swap.job.running" />
        <p class="hint">
          Para testar uma voz, converta só um trecho de 20 a 30 s antes de fazer o arquivo inteiro. Funciona melhor com
          gravação limpa: eco forte e ruído na fala pioram a pronúncia da voz trocada.
        </p>
        <div class="actions">
          <AppButton type="submit" variant="primary" :loading="swap.job.running" :disabled="!swap.canRun">
            Trocar voz
          </AppButton>
        </div>
        <JobRunStatus :job="swap.job" title="Trocar voz" />
      </form>
    </AppCard>

    <AppCard v-if="swap.outcome" title="Voz trocada" :subtitle="`De ${swap.outcome.sourceName}. Ouça o original e o resultado.`">
      <div class="result">
        <p class="summary">{{ describeConversion(swap.outcome) }}</p>
        <p v-if="excerptNote" class="hint">{{ excerptNote }}</p>
        <AbCompare
          kind="audio"
          label="Original e voz trocada"
          :first="{ label: 'Original', src: swap.outcome.original_url }"
          :second="{ label: 'Voz trocada', src: swap.outcome.audio_url, refreshKey: swap.outcome.stamp }"
        />
        <div class="actions">
          <DownloadButton label="Baixar com a voz trocada" :url="downloadUrl(swap.outcome.audio_url)" />
          <UseInProject
            :project="swap.outcome.project"
            :entry="swap.outcome.entry"
            :new-path="swap.outcome.output"
            what="voz trocada"
            :blocked-reason="blockedReason"
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

.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}

.hint {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.summary {
  font-size: var(--text-md);
  overflow-wrap: anywhere;
}
</style>
