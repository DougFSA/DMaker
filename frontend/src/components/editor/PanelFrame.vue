<script setup lang="ts">
/* A moldura de um painel da bancada: a barra do título, que se arrasta para trocar o painel de lugar com outro, e o
   botão que o oculta. Quem não usa o mouse foca o ícone de arrastar e troca com as setas. O painel em si (o
   conteúdo) entra pelo slot e não sabe que está numa moldura. */
import AppIcon from '@/components/ui/AppIcon.vue'
import { MOVE_KEYS, PANEL_DRAG_MIME } from '@/lib/editorLayout'
import type { MoveDirection } from '@/lib/editorLayout'

const props = defineProps<{
  panelId: string
  title: string
  dragging?: boolean
  dropTarget?: boolean
}>()

const emit = defineEmits<{
  dragStart: []
  dragEnd: []
  hide: []
  move: [direction: MoveDirection]
}>()

function onDragStart(event: DragEvent): void {
  if (event.dataTransfer) {
    event.dataTransfer.setData(PANEL_DRAG_MIME, props.panelId)
    event.dataTransfer.effectAllowed = 'move'
  }
  emit('dragStart')
}

function onGripKey(event: KeyboardEvent): void {
  const direction = MOVE_KEYS[event.key]
  if (!direction) return
  event.preventDefault()
  emit('move', direction)
}
</script>

<template>
  <div :class="['frame', { 'is-dragging': dragging, 'is-drop-target': dropTarget }]" :data-frame="panelId">
    <header class="frame__bar" draggable="true" @dragstart="onDragStart" @dragend="emit('dragEnd')">
      <button
        type="button"
        class="frame__grip"
        :aria-label="`Mover o painel ${title}: use as setas para trocar de lugar com o vizinho`"
        title="Arraste o título para trocar de lugar"
        @keydown="onGripKey"
      >
        <AppIcon name="grip" :size="16" />
      </button>
      <h3 class="frame__title">{{ title }}</h3>
      <button type="button" class="frame__hide" :aria-label="`Ocultar o painel ${title}`" title="Ocultar painel" @click="emit('hide')">
        <AppIcon name="x" :size="16" />
      </button>
    </header>
    <div class="frame__body"><slot /></div>
  </div>
</template>

<style scoped>
.frame {
  display: flex;
  flex-direction: column;
  min-width: 0;
  height: 100%;
  overflow: hidden;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.frame.is-dragging {
  opacity: 0.45;
}

.frame.is-drop-target {
  outline: 2px dashed var(--color-accent);
  outline-offset: -3px;
}

.frame__bar {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-2);
  min-height: 2rem;
  background: var(--color-bg-soft);
  border-bottom: 1px solid var(--color-border);
  cursor: grab;
  user-select: none;
}

.frame__bar:active {
  cursor: grabbing;
}

.frame__title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-overflow: ellipsis;
  text-transform: uppercase;
  white-space: nowrap;
  color: var(--color-text-muted);
}

.frame__grip,
.frame__hide {
  display: grid;
  place-items: center;
  width: 1.5rem;
  height: 1.5rem;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-muted);
  cursor: inherit;
}

.frame__hide {
  cursor: pointer;
}

.frame__grip:hover,
.frame__hide:hover {
  background: var(--color-surface-hover);
  color: var(--color-text);
}

.frame__grip:focus-visible,
.frame__hide:focus-visible {
  outline: 2px solid var(--color-focus);
  outline-offset: 1px;
}

.frame__body {
  flex: 1;
  min-height: 0;
  /* o conteúdo mede o que precisa e a moldura rola; no layout de tela cada painel tem a altura do seu encaixe */
  overflow: auto;
  overscroll-behavior: contain;
  /* o painel de dentro dá a própria borda: aqui a moldura já a tem */
  --editor-side-panel-height: none;
  --editor-timeline-height: none;
}

.frame__body :deep(.card) {
  border: 0;
  border-radius: 0;
  box-shadow: none;
  background: transparent;
}

.frame__body :deep(.card .card__header) {
  padding: var(--space-2) var(--space-3);
}
</style>
