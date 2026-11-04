<script setup lang="ts">
/* A régua: marcas de tempo com o passo ajustado ao zoom (nunca mais perto que ~70 px), em segundos ou, com o andamento do
   projeto e a escolha da pessoa, em compassos (`9` no início do compasso 9 e `9.3` no terceiro tempo dele). O clique e o
   arrasto sobre ela levam o cursor até lá; quem trata o mouse é o painel, que reconhece a régua pelo atributo `data-ruler`. */
import { computed } from 'vue'
import type { TimelineTempo } from '@/api'
import { formatTimecode } from '@/lib/player'
import { laneWidth, rulerTicks } from '@/lib/timeline'
import { barRulerTicks } from '@/lib/tempoGrid'

const props = defineProps<{
  total: number
  fps: number
  pxPerSec: number
  windowStart: number
  windowEnd: number
  /** O andamento a desenhar em compassos; nulo é a régua de segundos. */
  tempo?: TimelineTempo | null
}>()

// só as marcas da janela visível; uma linha do tempo longa tem centenas
const ticks = computed(() => {
  if (props.tempo) {
    return barRulerTicks(props.tempo, Math.max(0, props.windowStart - 5), Math.min(props.total, props.windowEnd), props.pxPerSec).map(
      (tick) => ({ time: tick.time, label: tick.label, strong: tick.strong }),
    )
  }
  return rulerTicks(props.total, props.pxPerSec)
    .filter((time) => time >= props.windowStart - 5 && time <= props.windowEnd)
    .map((time) => ({ time, label: formatTimecode(time, props.fps).slice(0, 8), strong: true }))
})
const width = computed(() => `${laneWidth(props.total, props.pxPerSec)}px`)
</script>

<template>
  <div class="ruler-row">
    <div class="ruler-row__corner" />
    <div class="ruler" :style="{ width }" data-ruler="1">
      <div
        v-for="tick in ticks"
        :key="tick.time"
        class="ruler__tick"
        :class="{ 'ruler__tick--weak': !tick.strong }"
        :style="{ left: `${tick.time * pxPerSec}px` }"
      >
        <span>{{ tick.label }}</span>
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

/* o tempo dentro do compasso: a marca é menor e mais apagada que a do início do compasso */
.ruler__tick--weak {
  top: 40%;
  border-left-color: var(--color-border);
  line-height: calc(var(--tl-ruler-height) * 0.6);
}
</style>
