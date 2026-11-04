<script setup lang="ts">
/* O aviso do painel Áudio quando o projeto tem uma gravação que a aba deixou aberta (fechou no meio): o que chegou ao
   servidor está salvo, e dá para recuperar com a duração certa ou descartar. */
import { onMounted, watch } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useEditorStore } from '@/stores/editor'
import { useRecordingStore } from '@/stores/recording'

const recording = useRecordingStore()
const editor = useEditorStore()

onMounted(() => void recording.loadUnfinished())
watch(
  () => editor.name,
  () => void recording.loadUnfinished(),
)

const seconds = (value: number) => value.toFixed(1).replace('.', ',')
</script>

<template>
  <section v-if="recording.unfinished.length > 0 && recording.phase === 'idle'" class="recovery" role="status" data-recording-recovery>
    <strong>Uma gravação ficou aberta</strong>
    <span v-for="item in recording.unfinished" :key="item.id" class="recovery__item">
      {{ seconds(item.duration) }} s salvos
      <AppButton size="sm" variant="primary" data-recovery-recover @click="recording.recover(item.id)">Recuperar</AppButton>
      <AppButton size="sm" data-recovery-discard @click="recording.discardUnfinished(item.id)">Descartar</AppButton>
    </span>
  </section>
</template>

<style scoped>
.recovery {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--color-warning);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
}

.recovery__item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}
</style>
