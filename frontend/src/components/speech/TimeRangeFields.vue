<script setup lang="ts">
/* O intervalo opcional de uma mídia, início e fim em segundos: vazio vale o arquivo inteiro. Usado por Isolar voz,
   Corrigir fala (trecho a transcrever) e Trocar voz. Avisa na hora se o fim não vem depois do início. */
import { computed } from 'vue'
import AppNumberInput from '@/components/ui/AppNumberInput.vue'
import { rangeProblem } from '@/lib/speech'

withDefaults(
  defineProps<{
    startLabel?: string
    endLabel?: string
    /** Passo das setas do campo; em vídeos longos, segundos inteiros bastam. */
    step?: number
    disabled?: boolean
  }>(),
  { startLabel: 'Início (s, opcional)', endLabel: 'Fim (s, opcional)', step: 0.1 },
)

const start = defineModel<number | null>('start', { default: null })
const end = defineModel<number | null>('end', { default: null })

const problem = computed(() => rangeProblem(start.value, end.value))
</script>

<template>
  <div class="range">
    <AppNumberInput
      v-model="start"
      :label="startLabel"
      :min="0"
      :step="step"
      placeholder="Começo do arquivo"
      :disabled="disabled"
    />
    <AppNumberInput
      v-model="end"
      :label="endLabel"
      :min="0"
      :step="step"
      placeholder="Fim do arquivo"
      :error="problem"
      :disabled="disabled"
    />
  </div>
</template>

<style scoped>
.range {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 12rem), 1fr));
  gap: var(--space-4);
}
</style>
