<script setup lang="ts">
/* Um item de uma trilha: um bloco posicionado pelo tempo, com o rótulo, as alças de aparar e, quando o item tem som,
   a forma de onda. Não trata o mouse: o painel escuta tudo por delegação e descobre o item pelos `data-*`. */
import { computed } from 'vue'
import type { TimelineItem } from '@/api'
import { displayLabel, hasTrimHandles, isDraggable, itemTitle, kindClass } from '@/lib/timeline'
import { itemPieces } from '@/lib/waveform'
import TimelineWaveform from './TimelineWaveform.vue'

const props = defineProps<{
  item: TimelineItem
  trackId: string
  pxPerSec: number
  selected: boolean
  /** O item tem forma de onda (áudio de clipe, faixa externa, música ou vídeo sobreposto). */
  waveform: boolean
}>()

/** Largura mínima para o bloco de um item muito curto continuar clicável. */
const MIN_WIDTH_PX = 3

const style = computed(() => ({
  left: `${props.item.start * props.pxPerSec}px`,
  width: `${Math.max(MIN_WIDTH_PX, (props.item.end - props.item.start) * props.pxPerSec)}px`,
}))
const draggable = computed(() => isDraggable(props.trackId, props.item))
const handles = computed(() => hasTrimHandles(props.trackId, props.item))
const title = computed(() => itemTitle(props.item))
const label = computed(() => displayLabel(props.item.label) || props.item.kind)
const pieces = computed(() => itemPieces(props.item))
const classes = computed(() => [
  'item',
  `item--${kindClass(props.item.kind)}`,
  {
    'item--selected': props.selected,
    'item--muted': props.item.muted,
    'item--estimated': !!props.item.extra?.estimated,
    'item--missing': !!props.item.missing,
  },
])
</script>

<template>
  <div
    :class="classes"
    :style="style"
    :data-item-id="item.id"
    :data-track-id="trackId"
    :data-draggable="draggable ? '1' : '0'"
    :title="title"
    role="button"
    :aria-pressed="selected"
    :aria-label="title"
  >
    <template v-if="waveform && !item.missing">
      <TimelineWaveform
        v-for="(_piece, index) in pieces"
        :key="`${item.id}:${index}`"
        :item="item"
        :piece-index="index"
        :selected="selected"
      />
      <TimelineWaveform v-if="pieces.length === 0" :item="item" :piece-index="null" :selected="selected" />
    </template>
    <template v-if="handles">
      <span class="item__handle item__handle--in" data-handle="in" />
      <span class="item__handle item__handle--out" data-handle="out" />
    </template>
    <span class="item__label">{{ label }}</span>
  </div>
</template>

<style scoped>
.item {
  position: absolute;
  top: 3px;
  bottom: 3px;
  display: flex;
  align-items: center;
  min-width: 0;
  padding: 0 var(--space-1);
  overflow: hidden;
  border: 1px solid rgb(255 255 255 / 0.18);
  border-radius: 5px;
  background: var(--tl-other);
  color: #fff;
  font-size: var(--text-xs);
  user-select: none;
  cursor: pointer;
}

.item[data-draggable='1'] {
  cursor: grab;
}

.item__label {
  position: relative;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  pointer-events: none;
  text-shadow: 0 1px 2px rgb(0 0 0 / 0.6);
}

.item--selected {
  border-color: #fff;
  box-shadow:
    0 0 0 1px #fff,
    0 0 0 3px var(--color-accent);
  z-index: 1;
}

.item--muted {
  opacity: 0.55;
}

/* a cor de cada tipo de item; as mesmas nos dois temas, porque o texto do bloco é sempre branco */
.item--clip {
  background: var(--tl-clip);
}
.item--image {
  background: var(--tl-image);
}
.item--card {
  background: var(--tl-card);
}
.item--video {
  background: var(--tl-video);
}
.item--text {
  background: var(--tl-text);
}
.item--clip-audio {
  background: var(--tl-clip-audio);
}
.item--track {
  background: var(--tl-track);
}
.item--music {
  background: var(--tl-music);
}
.item--narration {
  background: var(--tl-narration);
}
.item--captions {
  background: var(--tl-captions);
}
.item--progress-bar {
  background: var(--tl-progress);
}

/* a duração da fala ainda é um palpite por texto: borda tracejada até a voz ser sintetizada */
.item--estimated {
  border-style: dashed;
  border-color: rgb(255 255 255 / 0.55);
}

/* o arquivo sumiu do disco: listras vermelhas, e o balão diz "fonte não encontrada" */
.item--missing {
  background-image: repeating-linear-gradient(135deg, rgb(255 122 122 / 0.45) 0 6px, rgb(0 0 0 / 0.35) 6px 12px);
  border-color: var(--color-error);
}

.item__handle {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 6px;
  cursor: ew-resize;
  z-index: 2;
}

.item__handle--in {
  left: 0;
}

.item__handle--out {
  right: 0;
}

.item__handle:hover {
  background: rgb(255 255 255 / 0.28);
}
</style>
