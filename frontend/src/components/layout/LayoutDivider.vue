<script setup lang="ts">
/* O divisor que se arrasta para mudar o tamanho de um painel (a altura da faixa de cima, a largura das colunas ou da
   barra lateral). Também funciona pelo teclado: as setas movem de `step` em `step`. Quem usa guarda o valor novo; o
   divisor só calcula, a partir do ponto onde o arrasto começou, e por isso não acumula erro de arredondamento. */
import { onBeforeUnmount, ref } from 'vue'

const props = defineProps<{
  /** `horizontal` é a barra deitada (muda a altura); `vertical` é a barra em pé (muda a largura). */
  orientation: 'horizontal' | 'vertical'
  label: string
  value: number
  min: number
  max: number
  /** O quanto o valor muda por pixel arrastado (1 para pixels; 1 dividido pela altura para uma fração). */
  perPixel: number
  /** O quanto cada toque de seta muda. */
  step: number
  /** Arrastar para a esquerda ou para cima aumenta o valor (o divisor da coluna da direita). */
  invert?: boolean
}>()

const emit = defineEmits<{ resize: [value: number]; commit: []; drag: [active: boolean] }>()

const dragging = ref(false)
let origin: { x: number; y: number; value: number } | null = null

function clamp(value: number): number {
  return Math.min(props.max, Math.max(props.min, value))
}

function onMouseMove(event: MouseEvent): void {
  if (!origin) return
  const distance = props.orientation === 'vertical' ? event.clientX - origin.x : event.clientY - origin.y
  emit('resize', clamp(origin.value + distance * props.perPixel * (props.invert ? -1 : 1)))
}

function stopDragging(): void {
  window.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('mouseup', stopDragging)
  if (!origin) return
  origin = null
  dragging.value = false
  emit('drag', false)
  emit('commit')
}

function onMouseDown(event: MouseEvent): void {
  if (event.button !== 0) return
  event.preventDefault()
  origin = { x: event.clientX, y: event.clientY, value: props.value }
  dragging.value = true
  emit('drag', true)
  window.addEventListener('mousemove', onMouseMove)
  window.addEventListener('mouseup', stopDragging)
}

function onKeyDown(event: KeyboardEvent): void {
  const keys = props.orientation === 'vertical' ? ['ArrowLeft', 'ArrowRight'] : ['ArrowUp', 'ArrowDown']
  const index = keys.indexOf(event.key)
  if (index < 0) return
  event.preventDefault()
  // seta para a direita ou para baixo empurra o divisor nesse sentido
  const direction = (index === 0 ? -1 : 1) * (props.invert ? -1 : 1)
  emit('resize', clamp(props.value + direction * props.step))
  emit('commit')
}

onBeforeUnmount(stopDragging)
</script>

<template>
  <div
    :class="['divider', `divider--${orientation}`, { 'is-dragging': dragging }]"
    role="separator"
    tabindex="0"
    :aria-orientation="orientation === 'vertical' ? 'vertical' : 'horizontal'"
    :aria-label="label"
    :aria-valuenow="Math.round(value * 100) / 100"
    :aria-valuemin="min"
    :aria-valuemax="max"
    title="Arraste para redimensionar"
    @mousedown="onMouseDown"
    @keydown="onKeyDown"
  />
</template>

<style scoped>
.divider {
  background: transparent;
  border-radius: var(--radius-pill);
  touch-action: none;
  transition: background var(--transition);
}

.divider--vertical {
  cursor: col-resize;
}

.divider--horizontal {
  cursor: row-resize;
}

.divider:hover,
.divider.is-dragging {
  background: var(--color-accent-soft);
}

.divider:focus-visible {
  outline: 2px solid var(--color-focus);
  outline-offset: -2px;
  background: var(--color-accent-soft);
}
</style>
