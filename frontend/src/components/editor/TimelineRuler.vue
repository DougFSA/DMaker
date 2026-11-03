<script setup lang="ts">
/* A régua: marcas de tempo com o passo ajustado ao zoom (nunca mais perto que ~70 px). O clique e o arrasto sobre ela
   levam o cursor até lá; quem trata o mouse é o painel, que reconhece a régua pelo atributo `data-ruler`. */
import { computed } from 'vue'
import { formatTimecode } from '@/lib/player'
import { laneWidth, rulerTicks } from '@/lib/timeline'

const props = defineProps<{
  total: number
  fps: number
  pxPerSec: number
  windowStart: number
  windowEnd: number
}>()

// só as marcas da janela visível; uma linha do tempo longa tem centenas
const ticks = computed(() =>
  rulerTicks(props.total, props.pxPerSec).filter((time) => time >= props.windowStart - 5 && time <= props.windowEnd),
)
const width = computed(() => `${laneWidth(props.total, props.pxPerSec)}px`)
</script>

<template>
  <div class="ruler-row">
    <div class="ruler-row__corner" />
    <div class="ruler" :style="{ width }" data-ruler="1">
      <div v-for="time in ticks" :key="time" class="ruler__tick" :style="{ left: `${time * pxPerSec}px` }">
        <span>{{ formatTimecode(time, fps).slice(0, 8) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ruler-row {
  position: sticky;
  top: 0;
  z-index: 6;
  display: flex;
  height: var(--tl-ruler-height);
  border-bottom: 1px solid var(--color-border-strong);
  background: var(--color-surface-raised);
}

.ruler-row__corner {
  position: sticky;
  left: 0;
  z-index: 7;
  flex: none;
  width: var(--tl-header-width);
  border-right: 1px solid var(--color-border-strong);
  background: var(--color-surface-raised);
}

.ruler {
  position: relative;
  flex: none;
  height: 100%;
  cursor: col-resize;
}

.ruler__tick {
  position: absolute;
  top: 0;
  bottom: 0;
  padding-left: 4px;
  border-left: 1px solid var(--color-border-strong);
  font-size: 0.625rem;
  line-height: var(--tl-ruler-height);
  color: var(--color-text-muted);
  white-space: nowrap;
  pointer-events: none;
  font-variant-numeric: tabular-nums;
}
</style>
