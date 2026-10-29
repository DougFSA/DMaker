<script setup lang="ts">
/* O cursor da linha do tempo. Mora em componente próprio porque a posição muda a cada quadro enquanto o vídeo toca:
   assim só esta peça se refaz, e não o painel inteiro com as centenas de itens. */
import { computed } from 'vue'
import { TRACK_HEADER_WIDTH } from '@/lib/timeline'
import { useEditorStore } from '@/stores/editor'
import { useTimelineStore } from '@/stores/timeline'

const editor = useEditorStore()
const timeline = useTimelineStore()

const left = computed(() => `${TRACK_HEADER_WIDTH + editor.playhead * timeline.pxPerSec}px`)
</script>

<template>
  <div class="playhead" :style="{ left }" aria-hidden="true" data-playhead="1" />
</template>

<style scoped>
/* abaixo do cabeçalho colado das trilhas (z-index 4), que cobre o cursor quando ele rola para a esquerda */
.playhead {
  position: absolute;
  top: 0;
  bottom: 0;
  z-index: 3;
  width: 2px;
  margin-left: -1px;
  background: var(--color-error);
  pointer-events: none;
}

.playhead::before {
  content: '';
  position: absolute;
  top: 0;
  left: -4px;
  width: 10px;
  height: 8px;
  background: var(--color-error);
  clip-path: polygon(0 0, 100% 0, 50% 100%);
}
</style>
