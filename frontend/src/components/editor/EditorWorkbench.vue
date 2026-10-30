<script setup lang="ts">
/* A bancada do editor: os painéis de mídia, player, filtros e linha do tempo, dispostos pelo layout de tela. A grade
   tem a faixa de cima (inteira) e, embaixo, três colunas; o layout diz que painel mora em cada encaixe, quanto cada
   divisor mede e o que está oculto. Os painéis são sempre os mesmos quatro, na mesma ordem: trocar de lugar só muda a
   posição na grade, e por isso o player não é recriado (nem perde o som) quando alguém o arrasta. Painel oculto sai
   da tela e do DOM, e a coluna dele recolhe. Abaixo de 900 px os painéis empilham e não há divisores. */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import LayoutDivider from '@/components/layout/LayoutDivider.vue'
import AppButton from '@/components/ui/AppButton.vue'
import {
  PANEL_DRAG_MIME,
  isMovablePanel,
  SIZE_RANGES,
  neighborSlot,
  placement,
  workbenchGrid,
  WORKBENCH_SLOTS,
  type MoveDirection,
  type MovablePanel,
  type WorkbenchSlot,
} from '@/lib/editorLayout'
import { useScreenLayoutStore } from '@/stores/screenLayout'
import EditorSlot from './EditorSlot.vue'
import PanelFrame from './PanelFrame.vue'
import { panelsIn, type EditorPanelDef } from './panels'

const layout = useScreenLayoutStore()

// a ordem fixa dos painéis no DOM: o encaixe (e o lugar na grade) é só CSS
type WorkbenchPanel = EditorPanelDef & { id: MovablePanel }
// a ordem do DOM é a do layout padrão, da esquerda para a direita e de cima para baixo: é por ela que o Tab anda
const TAB_ORDER: MovablePanel[] = ['player', 'filters', 'timeline', 'media']
const defs = panelsIn('workbench')
  .filter((def): def is WorkbenchPanel => isMovablePanel(def.id))
  .sort((a, b) => TAB_ORDER.indexOf(a.id) - TAB_ORDER.indexOf(b.id))

const placed = computed(() => placement(layout.layout))
const slotOfPanel = computed(() => {
  const map = new Map<MovablePanel, WorkbenchSlot>()
  for (const slot of WORKBENCH_SLOTS) {
    const panel = placed.value[slot]
    if (panel) map.set(panel, slot)
  }
  return map
})

const shown = computed(() => defs.filter((def) => !layout.isHidden(def.id)))
const visible = computed(() => {
  const result = { 'top-center': false, 'top-left': false, bottom: false, 'top-right': false } as Record<WorkbenchSlot, boolean>
  for (const def of shown.value) {
    const slot = slotOfPanel.value.get(def.id)
    if (slot) result[slot] = true
  }
  return result
})
const grid = computed(() => workbenchGrid(layout.layout, visible.value))

/** Onde cada encaixe cai na grade (faixa de cima inteira; embaixo, esquerda, meio e direita) e na pilha estreita. */
const CELL_POSITION: Record<WorkbenchSlot, { column: string; row: number; order: number }> = {
  'top-center': { column: '1 / -1', row: 1, order: 0 },
  bottom: { column: '3', row: 3, order: 1 },
  'top-left': { column: '1', row: 3, order: 2 },
  'top-right': { column: '5', row: 3, order: 3 },
}

function cellStyle(id: string): Record<string, string> {
  const slot = slotOfPanel.value.get(id as MovablePanel) ?? 'bottom'
  const position = CELL_POSITION[slot]
  return { gridColumn: position.column, gridRow: String(position.row), order: String(position.order) }
}

/* ---------- arrastar o título para trocar de lugar ---------- */

const dragging = ref<MovablePanel | null>(null)
const over = ref<MovablePanel | null>(null)
const announcement = ref('')

function endDrag(): void {
  dragging.value = null
  over.value = null
}

function onDragOver(event: DragEvent, target: MovablePanel): void {
  if (!event.dataTransfer?.types.includes(PANEL_DRAG_MIME)) return
  event.preventDefault()
  event.dataTransfer.dropEffect = 'move'
  over.value = target
}

function onDragLeave(event: DragEvent, target: MovablePanel): void {
  // sair para um filho do mesmo encaixe não é sair
  const next = event.relatedTarget as Node | null
  if (next && (event.currentTarget as Node).contains(next)) return
  if (over.value === target) over.value = null
}

function onDrop(event: DragEvent, target: MovablePanel): void {
  over.value = null
  const source = event.dataTransfer?.getData(PANEL_DRAG_MIME)
  if (!source || source === target) return
  event.preventDefault()
  layout.swap(source as MovablePanel, target)
}

/** Troca com o vizinho pelo teclado e avisa o leitor de tela, que não vê o painel mudar de lugar. */
function moveByKey(panel: MovablePanel, direction: MoveDirection): void {
  const slot = slotOfPanel.value.get(panel)
  const neighbor = slot ? neighborSlot(slot, direction) : null
  const target = neighbor ? placed.value[neighbor] : null
  if (!target) {
    announcement.value = 'Não há painel nessa direção.'
    return
  }
  layout.swap(panel, target)
  const titleOf = (id: MovablePanel) => defs.find((def) => def.id === id)?.title ?? id
  announcement.value = `${titleOf(panel)} trocou de lugar com ${titleOf(target)}.`
}

/* ---------- divisores ---------- */

const gridEl = ref<HTMLElement | null>(null)
const gridHeight = ref(0)
let observer: ResizeObserver | null = null

function measure(): void {
  gridHeight.value = gridEl.value?.getBoundingClientRect().height ?? 0
}

/** Os painéis redesenham pelo que medem; depois de mexer num divisor, um aviso de redimensionamento os acorda. */
function announceResize(): void {
  window.dispatchEvent(new Event('resize'))
}

onMounted(() => {
  measure()
  if (typeof ResizeObserver !== 'undefined' && gridEl.value) {
    observer = new ResizeObserver(measure)
    observer.observe(gridEl.value)
  }
})
onBeforeUnmount(() => observer?.disconnect())

const rowPerPixel = computed(() => 1 / Math.max(gridHeight.value, 1))
</script>

<template>
  <div ref="gridEl" class="workbench" :style="{ gridTemplateColumns: grid.columns, gridTemplateRows: grid.rows }" aria-label="Bancada do editor">
    <div
      v-for="def in shown"
      :key="def.id"
      class="cell"
      :data-cell="def.id"
      :style="cellStyle(def.id)"
      @dragover="onDragOver($event, def.id)"
      @dragleave="onDragLeave($event, def.id)"
      @drop="onDrop($event, def.id)"
    >
      <PanelFrame
        :panel-id="def.id"
        :title="def.title"
        :dragging="dragging === def.id"
        :drop-target="over === def.id && dragging !== def.id"
        @drag-start="dragging = def.id"
        @drag-end="endDrag"
        @hide="layout.setHidden(def.id, true)"
        @move="moveByKey(def.id, $event)"
      >
        <EditorSlot :panel="def" />
      </PanelFrame>
    </div>

    <LayoutDivider
      v-if="grid.showRowDivider"
      class="workbench__divider workbench__divider--row"
      orientation="horizontal"
      label="Altura do player"
      :value="layout.layout.sizes['row-top'] ?? 0.42"
      :min="SIZE_RANGES['row-top'][0]"
      :max="SIZE_RANGES['row-top'][1]"
      :per-pixel="rowPerPixel"
      :step="0.02"
      @resize="layout.setSize('row-top', $event)"
      @commit="announceResize"
    />
    <LayoutDivider
      v-if="grid.showLeftDivider"
      class="workbench__divider workbench__divider--left"
      orientation="vertical"
      label="Largura da coluna da esquerda"
      :value="layout.layout.sizes['col-left'] ?? 240"
      :min="SIZE_RANGES['col-left'][0]"
      :max="SIZE_RANGES['col-left'][1]"
      :per-pixel="1"
      :step="16"
      @resize="layout.setSize('col-left', $event)"
      @commit="announceResize"
    />
    <LayoutDivider
      v-if="grid.showRightDivider"
      class="workbench__divider workbench__divider--right"
      orientation="vertical"
      label="Largura da coluna da direita"
      :value="layout.layout.sizes['col-right'] ?? 240"
      :min="SIZE_RANGES['col-right'][0]"
      :max="SIZE_RANGES['col-right'][1]"
      :per-pixel="1"
      :step="16"
      invert
      @resize="layout.setSize('col-right', $event)"
      @commit="announceResize"
    />

    <div v-if="shown.length === 0" class="workbench__empty">
      <p>Todos os painéis estão ocultos.</p>
      <AppButton variant="primary" @click="layout.restoreDefault()">Restaurar o layout padrão</AppButton>
    </div>

    <p class="visually-hidden" role="status">{{ announcement }}</p>
  </div>
</template>

<style scoped>
.workbench {
  /* a altura da bancada acompanha a janela: o player, a linha do tempo e os painéis laterais dividem este espaço */
  display: grid;
  height: clamp(30rem, calc(100dvh - 18rem), 72rem);
  min-width: 0;
}

.cell {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  /* cada painel mede o próprio encaixe: o palco do player cabe nele, em vez de seguir a altura da janela */
  container-type: size;
  --editor-stage-max-h: max(7rem, calc(100cqh - 13rem));
}

.workbench__divider--row {
  grid-column: 1 / -1;
  grid-row: 2;
}

.workbench__divider--left {
  grid-column: 2;
  grid-row: 3;
}

.workbench__divider--right {
  grid-column: 4;
  grid-row: 3;
}

.workbench__empty {
  display: grid;
  grid-column: 1 / -1;
  grid-row: 1 / -1;
  place-content: center;
  justify-items: center;
  gap: var(--space-3);
  color: var(--color-text-soft);
}

@media (max-width: 900px) {
  /* telas estreitas: os painéis empilham, cada um com a altura do seu conteúdo, e não há divisores */
  .workbench {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    height: auto;
  }

  .cell {
    container-type: normal;
    max-height: 34rem;
    --editor-stage-max-h: min(52vh, 34rem);
  }

  .workbench__divider {
    display: none;
  }
}
</style>
