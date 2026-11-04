<script setup lang="ts">
/* As alças de fade nas duas pontas de um item de áudio: um botão em cada canto de cima e, quando há fade, a curva
   desenhada sobre a forma de onda (a região escura é o som que o fade tira). Não trata o mouse: o painel escuta por
   delegação e descobre a alça pelo `data-fade`; durante o arrasto a duração vem do store (`fadePreview`). */
import { computed } from 'vue'
import type { TimelineItem } from '@/api'
import { fadeShadePoints, fadeTarget, itemFades, itemSpeed, type FadeSide } from '@/lib/audioFades'

const props = defineProps<{
  item: TimelineItem
  trackId: string
  pxPerSec: number
  /** O fade que a alça arrastada mostra enquanto o gesto não termina (o painel o guarda no store da linha do tempo). */
  preview?: { itemId: string; side: FadeSide; duration: number } | null
}>()

const target = computed(() => fadeTarget(props.trackId, props.item))
const fades = computed(() => itemFades(props.item))
const speed = computed(() => itemSpeed(props.item))
const itemWidthPx = computed(() => (props.item.end - props.item.start) * props.pxPerSec)

interface Shown {
  side: FadeSide
  /** Largura do fade na tela, em pixels. */
  widthPx: number
  shade: string
  title: string
}

function shownFade(side: FadeSide): Shown {
  const preview = props.preview
  const live = preview && preview.itemId === props.item.id && preview.side === side ? preview.duration : null
  const edge = fades.value[side]
  const duration = live ?? edge?.duration ?? 0
  const curve = edge?.curve ?? 'linear'
  const widthPx = Math.min((duration / speed.value) * props.pxPerSec, itemWidthPx.value)
  const name = side === 'in' ? 'Fade In' : 'Fade Out'
  return {
    side,
    widthPx,
    shade: widthPx > 0 ? fadeShadePoints(side, curve, 100, 100) : '',
    title: duration > 0 ? `${name}: ${duration.toFixed(2)} s. Arraste para mudar; solte na borda para tirar.` : `${name}: arraste para criar`,
  }
}

const sides = computed<Shown[]>(() => [shownFade('in'), shownFade('out')])
</script>

<template>
  <template v-if="target">
    <template v-for="fade in sides" :key="fade.side">
      <svg
        v-if="fade.widthPx > 0"
        :class="['fade', `fade--${fade.side}`]"
        :style="{ width: `${fade.widthPx}px` }"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <polygon :points="fade.shade" />
      </svg>
      <span
        :class="['fade-handle', `fade-handle--${fade.side}`, { 'fade-handle--set': fade.widthPx > 0 }]"
        :style="fade.side === 'in' ? { left: `${fade.widthPx}px` } : { right: `${fade.widthPx}px` }"
        :data-fade="fade.side"
        :title="fade.title"
      />
    </template>
  </template>
</template>

<style scoped>
.fade {
  position: absolute;
  top: 0;
  bottom: 0;
  z-index: 1;
  pointer-events: none;
}

.fade polygon {
  fill: rgb(0 0 0 / 0.5);
  stroke: rgb(255 255 255 / 0.8);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}

.fade--in {
  left: 0;
}

.fade--out {
  right: 0;
}

/* a alça é um quadradinho no canto de cima; fica mais visível com o ponteiro sobre o item ou com o fade posto */
.fade-handle {
  position: absolute;
  top: 0;
  z-index: 3;
  width: 9px;
  height: 9px;
  border: 1px solid rgb(255 255 255 / 0.9);
  border-radius: 2px;
  background: rgb(0 0 0 / 0.55);
  opacity: 0;
  cursor: ew-resize;
}

:global(.item:hover) .fade-handle,
.fade-handle--set {
  opacity: 1;
}

.fade-handle:hover {
  background: var(--color-accent);
}
</style>
