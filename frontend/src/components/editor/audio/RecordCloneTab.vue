<script setup lang="ts">
/* O atalho de clonagem da janela Gravar: o texto da folha de gravação na tela, 15 s de microfone e a voz clonada na biblioteca,
   sem arquivo no meio. A voz só é clonada com a permissão do dono marcada (aqui, a própria pessoa lendo). */
import { computed, onMounted } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCheckbox from '@/components/ui/AppCheckbox.vue'
import AppInput from '@/components/ui/AppInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import ProgressBar from '@/components/ui/ProgressBar.vue'
import { CLONE_SECONDS } from '@/lib/recordingScript'
import { clockText } from '@/lib/recordingSchedule'
import { useRecordCloneStore, MIN_CLONE_SECONDS } from '@/stores/recordClone'
import { useRecordingStore } from '@/stores/recording'
import { useVoiceStore } from '@/stores/voice'
import AudioMeter from './AudioMeter.vue'

const clone = useRecordCloneStore()
const recording = useRecordingStore()
const voices = useVoiceStore()

const languages = [
  { value: 'pt', label: 'Português' },
  { value: 'en', label: 'Inglês' },
  { value: 'es', label: 'Espanhol' },
  { value: 'fr', label: 'Francês' },
  { value: 'de', label: 'Alemão' },
  { value: 'it', label: 'Italiano' },
]
const percent = computed(() => Math.min(100, (clone.elapsed / CLONE_SECONDS) * 100))
const recordingNow = computed(() => clone.phase === 'recording')
const cloning = computed(() => clone.phase === 'cloning')

onMounted(() => {
  clone.deviceId = recording.settings.deviceId
  void voices.loadVoices()
})
</script>

<template>
  <div class="clone" data-record-clone>
    <p class="clone__hint">
      Grave {{ CLONE_SECONDS }} segundos lendo o texto abaixo em voz alta, com calma, num lugar silencioso. A voz vai direto para a
      biblioteca de vozes. Clone apenas a sua voz ou a de quem deu permissão.
    </p>
    <AppInput v-model="clone.name" label="Nome da voz" placeholder="Ex.: Minha voz" :disabled="clone.phase !== 'idle'" data-clone-name />
    <AppSelect v-model="clone.language" label="Idioma do texto" :options="languages" :disabled="clone.phase !== 'idle'" />
    <blockquote class="clone__script" data-clone-script>{{ clone.script }}</blockquote>
    <AppCheckbox v-model="clone.consent" label="Esta é a minha voz, ou tenho a permissão do dono dela para clonar" :disabled="clone.phase !== 'idle'" data-clone-consent />
    <div class="clone__row">
      <AudioMeter :levels="clone.levels" />
      <span class="clone__clock" role="status">{{ clockText(clone.elapsed) }} / {{ clockText(CLONE_SECONDS) }}</span>
    </div>
    <ProgressBar v-if="recordingNow" :value="percent" label="Tempo gravado" />
    <p v-if="cloning" class="clone__hint" role="status">Clonando a voz...</p>
    <p v-if="clone.error" class="clone__error" role="alert" data-clone-error>{{ clone.error }}</p>
    <div class="clone__row">
      <AppButton v-if="!recordingNow" variant="primary" :disabled="!clone.canStart || cloning" data-clone-record @click="clone.record()">
        Gravar e clonar
      </AppButton>
      <template v-else>
        <AppButton variant="primary" :disabled="clone.elapsed < MIN_CLONE_SECONDS" data-clone-stop @click="clone.stop()">Parar e clonar</AppButton>
        <AppButton data-clone-cancel @click="clone.cancel()">Descartar</AppButton>
      </template>
    </div>
  </div>
</template>

<style scoped>
.clone {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.clone__script {
  margin: 0;
  padding: var(--space-3) var(--space-4);
  border-left: 3px solid var(--color-accent);
  border-radius: var(--radius-sm);
  background: var(--color-bg-soft);
  font-size: var(--text-lg);
  line-height: 1.5;
}

.clone__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
}

.clone__clock {
  font-variant-numeric: tabular-nums;
}

.clone__hint {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.clone__error {
  font-size: var(--text-sm);
  color: var(--color-error);
}
</style>
