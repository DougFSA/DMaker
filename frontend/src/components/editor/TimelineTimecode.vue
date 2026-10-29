<script setup lang="ts">
/* O timecode da linha do tempo (posição do cursor e duração). Componente próprio pelo mesmo motivo do cursor:
   o texto muda a cada quadro e não deve refazer o painel. */
import { computed } from 'vue'
import { formatTimecode } from '@/lib/player'
import { useEditorStore } from '@/stores/editor'

const editor = useEditorStore()

const fps = computed(() => editor.view?.fps || 30)
</script>

<template>
  <p class="timecode" aria-label="Posição na linha do tempo">
    <span class="timecode__now">{{ formatTimecode(editor.playhead, fps) }}</span>
    <span class="timecode__total">/ {{ formatTimecode(editor.total, fps) }}</span>
  </p>
</template>

<style scoped>
.timecode {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  font-variant-numeric: tabular-nums;
  font-size: var(--text-sm);
}

.timecode__now {
  font-family: var(--font-mono);
  font-weight: 600;
  color: var(--color-text);
}

.timecode__total {
  font-family: var(--font-mono);
  color: var(--color-text-muted);
}
</style>
