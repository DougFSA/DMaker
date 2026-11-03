<script setup lang="ts">
/* Gravar a referência da voz pelo microfone: grava e para, mostra o relógio e o conselho de 5 a 8 s, para sozinho
   aos 30 s e deixa ouvir o que foi gravado antes de clonar. O v-model é a gravação pronta (ou nada). */
import { computed, watch } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import MediaPlayer from '@/components/ui/MediaPlayer.vue'
import { useMicrophoneRecorder } from '@/composables/useMicrophoneRecorder'
import { formatClock } from '@/lib/format'
import { MAX_RECORDING_MS, type Recording } from '@/lib/microphone'
import { INITIAL_ADVICE, recordingAdvice } from '@/lib/voice'

const model = defineModel<Recording | null>({ default: null })

const { phase, recordingNow, elapsedMs, recording, playbackUrl, error, starting, supported, start, stop, discard } =
  useMicrophoneRecorder()

const advice = computed(() => (phase.value === 'idle' ? INITIAL_ADVICE : recordingAdvice(elapsedMs.value / 1000)))
const clock = computed(() => formatClock(Math.floor(elapsedMs.value / 1000)))
const buttonLabel = computed(() => {
  if (phase.value === 'recording') return 'Parar gravação'
  return phase.value === 'recorded' ? 'Gravar de novo' : 'Gravar'
})
const limitSeconds = MAX_RECORDING_MS / 1000

defineExpose({
  /** Para a gravação em andamento (e guarda o que saiu); sem gravação, não faz nada. */
  stop,
})

function toggle(): void {
  if (phase.value === 'recording') stop()
  else void start()
}

// a gravação pronta sobe para o formulário; ao começar outra, ela some de lá até a nova ficar pronta
watch(recording, (value) => (model.value = value))
// o formulário limpou o campo (clonou com sucesso): o gravador volta ao começo
watch(model, (value) => {
  if (value === null && recording.value !== null) discard()
})
</script>

<template>
  <div class="recorder">
    <div class="recorder__row">
      <AppButton :variant="recordingNow ? 'danger' : 'secondary'" :disabled="!supported || starting" @click="toggle">
        {{ buttonLabel }}
      </AppButton>
      <span :class="['recorder__clock', { 'is-live': recordingNow }]">
        <span class="visually-hidden">Tempo gravado: </span>{{ clock }}
      </span>
      <span class="recorder__limit">Para sozinho aos {{ limitSeconds }} s.</span>
    </div>

    <p v-if="!supported" class="recorder__error" role="alert">
      Este navegador não grava pelo microfone. Envie um arquivo de áudio.
    </p>
    <template v-else>
      <p class="recorder__advice" :data-level="advice.level" role="status">{{ advice.text }}</p>
      <p v-if="error" class="recorder__error" role="alert">{{ error }}</p>
    </template>

    <MediaPlayer
      v-if="phase === 'recorded' && playbackUrl"
      kind="audio"
      title="Sua gravação"
      :src="playbackUrl"
      :meta="[clock]"
    />
  </div>
</template>

<style scoped>
.recorder {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-soft);
}

.recorder__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-4);
}

.recorder__clock {
  font-size: var(--text-xl);
  font-variant-numeric: tabular-nums;
  color: var(--color-text-soft);
}

.recorder__clock.is-live {
  color: var(--color-error);
}

.recorder__limit {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.recorder__advice {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.recorder__advice[data-level='good'] {
  color: var(--color-success);
}

.recorder__advice[data-level='bad'] {
  color: var(--color-warning);
}

.recorder__error {
  font-size: var(--text-sm);
  color: var(--color-error);
}
</style>
