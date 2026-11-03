<script setup lang="ts">
/* Um marcador da trilha MK: o instante é uma linha com a etiqueta ao lado, a região é uma faixa com as duas bordas
   para puxar. Não trata o mouse (o painel escuta tudo por delegação e acha o marcador pelos `data-*`); só a caixa de
   texto, aberta com o duplo clique ou logo depois de criar, tem teclado próprio: Enter confirma, Esc desiste. */
import { computed, nextTick, ref, watch } from 'vue'
import type { TimelineItem } from '@/api'
import { markerColor, markerTitle, renameOperation } from '@/lib/markers'
import { isInstantMarker } from '@/lib/timeline'
import { useEditorStore } from '@/stores/editor'
import { useTimelineStore } from '@/stores/timeline'

const props = defineProps<{
  item: TimelineItem
  trackId: string
  pxPerSec: number
  selected: boolean
}>()

const editor = useEditorStore()
const timeline = useTimelineStore()

/** A faixa de uma região nunca fica mais fina que isto, para a borda continuar ao alcance do mouse. */
const MIN_REGION_PX = 12

const instant = computed(() => isInstantMarker(props.item))
const editing = computed(() => timeline.editingMarkerId === props.item.id)
const title = computed(() => markerTitle(props.item))
const color = computed(() => markerColor(props.item))
const style = computed(() => {
  const left = `${props.item.start * props.pxPerSec}px`
  const base = color.value ? { '--marker-color': color.value } : {}
  if (instant.value) return { ...base, left }
  return { ...base, left, width: `${Math.max(MIN_REGION_PX, (props.item.end - props.item.start) * props.pxPerSec)}px` }
})

const draft = ref(props.item.label)
const input = ref<HTMLInputElement | null>(null)
let finished = false

watch(
  editing,
  async (isEditing) => {
    if (!isEditing) return
    draft.value = props.item.label
    finished = false
    await nextTick()
    input.value?.focus()
    input.value?.select()
  },
  { immediate: true },
)

async function commit(): Promise<void> {
  // Enter e o blur que vem logo depois dele chamam isto duas vezes: só a primeira vale
  if (finished) return
  finished = true
  timeline.stopEditingMarker()
  const op = renameOperation(props.item, draft.value)
  if (op) await editor.applyOp(op)
}

function cancel(): void {
  finished = true
  timeline.stopEditingMarker()
}
</script>

<template>
  <div
    :class="['marker', instant ? 'marker--instant' : 'marker--region', { 'marker--selected': selected }]"
    :style="style"
    :data-item-id="item.id"
    :data-track-id="trackId"
    data-draggable="1"
    data-marker="1"
    :title="title"
    role="button"
    :aria-pressed="selected"
    :aria-label="title"
  >
    <template v-if="!instant">
      <span class="marker__handle marker__handle--in" data-handle="in" />
      <span class="marker__handle marker__handle--out" data-handle="out" />
    </template>
    <span v-if="instant" class="marker__line" />
    <input
      v-if="editing"
      ref="input"
      v-model="draft"
      class="marker__input"
      type="text"
      aria-label="Texto do marcador"
      placeholder="Texto do marcador"
      @mousedown.stop
      @dblclick.stop
      @keydown.enter.prevent="commit"
      @keydown.esc.prevent="cancel"
      @blur="commit"
    />
    <span v-else-if="item.label" class="marker__label">{{ item.label }}</span>
  </div>
</template>

<style scoped>
.marker {
  --marker-color: var(--tl-marker);
  position: absolute;
  top: 3px;
  bottom: 3px;
  display: flex;
  align-items: center;
  min-width: 0;
  color: #fff;
  font-size: var(--text-xs);
  user-select: none;
  cursor: grab;
}

/* o instante: uma linha da cor do marcador e a etiqueta colada nela; sem texto ainda sobra uma área para clicar */
.marker--instant {
  min-width: 14px;
  padding-left: 7px;
}

.marker__line {
  position: absolute;
  top: -3px;
  bottom: -3px;
  left: 0;
  width: 2px;
  background: var(--marker-color);
}

.marker--instant::before {
  content: '';
  position: absolute;
  top: 0;
  left: -4px;
  border: 5px solid transparent;
  border-top-color: var(--marker-color);
}

.marker--instant .marker__label {
  padding: 0 var(--space-1);
  border-radius: 4px;
  background: rgb(0 0 0 / 0.55);
}

/* a região: uma faixa translúcida com borda, como o rótulo de região do Audacity */
.marker--region {
  padding: 0 var(--space-2);
  border: 1px solid var(--marker-color);
  border-radius: 5px;
  background: color-mix(in srgb, var(--marker-color) 38%, transparent);
}

.marker__label {
  overflow: hidden;
  max-width: 14rem;
  text-overflow: ellipsis;
  white-space: nowrap;
  pointer-events: none;
  text-shadow: 0 1px 2px rgb(0 0 0 / 0.6);
}

.marker--region .marker__label {
  max-width: none;
}

.marker__input {
  z-index: 3;
  width: 10rem;
  height: 22px;
  padding: 0 var(--space-1);
  border: 1px solid var(--color-accent);
  border-radius: 4px;
  background: var(--color-surface);
  color: var(--color-text);
  font: inherit;
  user-select: text;
}

.marker--selected {
  z-index: 1;
}

.marker--selected.marker--instant .marker__label,
.marker--selected.marker--region {
  box-shadow:
    0 0 0 1px #fff,
    0 0 0 3px var(--color-accent);
}

.marker__handle {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 6px;
  cursor: ew-resize;
  z-index: 2;
}

.marker__handle--in {
  left: 0;
}

.marker__handle--out {
  right: 0;
}

.marker__handle:hover {
  background: rgb(255 255 255 / 0.35);
}
</style>
