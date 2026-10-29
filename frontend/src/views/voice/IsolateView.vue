<script setup lang="ts">
/* Isolar voz: separa a fala da música e do ruído de fundo de um vídeo ou áudio e entrega as duas partes, cada uma
   com player e botão de baixar. Na CPU o trabalho leva de 3 a 6 vezes a duração do trecho, por isso é um job. */
import MediaPicker from '@/components/media/MediaPicker.vue'
import JobRunStatus from '@/components/speech/JobRunStatus.vue'
import TimeRangeFields from '@/components/speech/TimeRangeFields.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppSelect, { type SelectOption } from '@/components/ui/AppSelect.vue'
import DownloadButton from '@/components/ui/DownloadButton.vue'
import MediaPlayer from '@/components/ui/MediaPlayer.vue'
import { downloadUrl } from '@/lib/speech'
import { useIsolateStore } from '@/stores/speechIsolate'

const FORMATS: SelectOption[] = [
  { value: 'wav', label: 'wav (sem perdas)' },
  { value: 'mp3', label: 'mp3' },
]

const isolate = useIsolateStore()
</script>

<template>
  <div class="tool">
    <AppCard
      title="Isolar voz"
      subtitle="Separa a fala da música e do ruído de fundo de um vídeo ou áudio. Na CPU leva de 3 a 6 vezes a duração do trecho; o resultado fica guardado."
    >
      <form class="form" @submit.prevent="isolate.run()">
        <MediaPicker v-model="isolate.media" label="Arquivo" />
        <TimeRangeFields v-model:start="isolate.start" v-model:end="isolate.end" :disabled="isolate.job.running" />
        <AppSelect v-model="isolate.format" label="Formato" :options="FORMATS" :disabled="isolate.job.running" />
        <div class="actions">
          <AppButton type="submit" variant="primary" :loading="isolate.job.running" :disabled="!isolate.canRun">
            Isolar voz
          </AppButton>
        </div>
        <JobRunStatus :job="isolate.job" title="Isolar voz" />
      </form>
    </AppCard>

    <AppCard v-if="isolate.outcome" title="Voz e fundo prontos" :subtitle="`De ${isolate.outcome.sourceName}`">
      <div class="outputs">
        <MediaPlayer
          kind="audio"
          title="Voz"
          :src="isolate.outcome.voice_url"
          :refresh-key="isolate.outcome.stamp"
        >
          <template #actions>
            <DownloadButton size="sm" label="Baixar voz" :url="downloadUrl(isolate.outcome.voice_url)" />
          </template>
        </MediaPlayer>
        <MediaPlayer
          kind="audio"
          title="Fundo (música e ambiente)"
          :src="isolate.outcome.background_url"
          :refresh-key="isolate.outcome.stamp"
        >
          <template #actions>
            <DownloadButton size="sm" label="Baixar fundo" :url="downloadUrl(isolate.outcome.background_url)" />
          </template>
        </MediaPlayer>
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

.form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.actions {
  display: flex;
  gap: var(--space-3);
}

.outputs {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}
</style>
