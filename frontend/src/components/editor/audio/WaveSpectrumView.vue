<script setup lang="ts">
/* A multivista "Onda e espectro": a onda em cima e o espectrograma embaixo, no mesmo eixo de tempo (as duas leem a janela,
   a seleção, o cursor e a reprodução do mesmo store, então rolar, aproximar ou selecionar numa move a outra). A régua de
   tempo é a da onda; o tamanho que o painel usa para pedir a onda é o dela. */
import { ref } from 'vue'
import type { AudioWave } from '@/api'
import AudioWaveView from './AudioWaveView.vue'
import SpectrogramView from './SpectrogramView.vue'

defineProps<{ data: AudioWave | null }>()
const emit = defineEmits<{ size: [width: number]; scrub: [time: number]; 'scrub-end': [] }>()

const wave = ref<{ focus?: () => void } | null>(null)

defineExpose({ focus: () => wave.value?.focus?.() })
</script>

<template>
  <div class="both" data-audio-both>
    <AudioWaveView ref="wave" :data="data" @size="emit('size', $event)" @scrub="emit('scrub', $event)" @scrub-end="emit('scrub-end')" />
    <SpectrogramView :data="data" :ruler="false" />
  </div>
</template>

<style scoped>
.both {
  display: flex;
  flex-direction: column;
  flex: 1 1 auto;
  gap: var(--space-1);
  min-height: 0;
}

.both > * {
  flex: 1 1 0;
}
</style>
