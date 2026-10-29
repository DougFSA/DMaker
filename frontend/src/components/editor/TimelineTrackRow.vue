<script setup lang="ts">
/* Uma trilha: o cabeçalho colado à esquerda (rótulo e os botões M, H e cadeado) e a faixa com os itens. Só os itens
   que caem na janela visível são desenhados, para uma linha do tempo de centenas de trechos continuar leve. */
import { computed } from 'vue'
import type { TimelineTrack } from '@/api'
import {
  headerButtons,
  laneWidth,
  TOGGLE_LABEL,
  trackLabel,
  trackTitle,
  transitionSpans,
  type TrackToggle,
} from '@/lib/timeline'
import { waveformEligible } from '@/lib/waveform'
import TimelineItemBlock from './TimelineItemBlock.vue'

const props = defineProps<{
  track: TimelineTrack
  total: number
  pxPerSec: number
  /** A janela de itens desenhados, em segundos. */
  windowStart: number
  windowEnd: number
  selected: ReadonlySet<string>
}>()

const emit = defineEmits<{ toggle: [trackId: string, field: TrackToggle] }>()

const visibleItems = computed(() => props.track.items.filter((item) => item.end >= props.windowStart && item.start <= props.windowEnd))
const hatches = computed(() =>
  props.track.id === 'V1'
    ? transitionSpans(props.track.items).filter((span) => span.end >= props.windowStart && span.start <= props.windowEnd)
    : [],
)
const buttons = computed(() => headerButtons(props.track))
const width = computed(() => `${laneWidth(props.total, props.pxPerSec)}px`)

function pressed(field: TrackToggle): boolean {
  return props.track[field]
}

function buttonTitle(field: TrackToggle): string {
  const { title, verb } = TOGGLE_LABEL[field]
  return pressed(field) ? `${title}: ligado. Clique para desligar.` : `${verb} a trilha ${props.track.id}`
}
</script>

<template>
  <div
    :class="['row', { 'row--muted': track.muted, 'row--hidden': track.hidden, 'row--locked': track.locked }]"
    :data-track-id="track.id"
  >
    <div class="row__header" :title="trackTitle(track)">
      <span class="row__title">{{ trackLabel(track) }}</span>
      <span class="row__buttons">
        <button
          v-for="field in buttons"
          :key="field"
          type="button"
          :class="['row__button', { 'row__button--on': pressed(field) }]"
          :data-track-action="field"
          :aria-pressed="pressed(field)"
          :aria-label="`${TOGGLE_LABEL[field].title} (${track.id})`"
          :title="buttonTitle(field)"
          @click.stop="emit('toggle', track.id, field)"
        >
          {{ TOGGLE_LABEL[field].letter }}
        </button>
      </span>
    </div>
    <div class="lane" :data-track-id="track.id" :style="{ width }">
      <div
        v-for="span in hatches"
        :key="`transition:${span.id}`"
        class="transition"
        :style="{ left: `${span.start * pxPerSec}px`, width: `${Math.max(2, (span.end - span.start) * pxPerSec)}px` }"
        :title="`Transição: ${span.type}`"
      />
      <TimelineItemBlock
        v-for="item in visibleItems"
        :key="item.id"
        :item="item"
        :track-id="track.id"
        :px-per-sec="pxPerSec"
        :selected="selected.has(item.id)"
        :waveform="waveformEligible(track, item)"
      />
    </div>
  </div>
</template>

<style scoped>
.row {
  display: flex;
  height: var(--tl-row-height);
  border-bottom: 1px solid var(--color-border);
}

.row__header {
  position: sticky;
  left: 0;
  z-index: 4;
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-1);
  width: var(--tl-header-width);
  padding: 0 var(--space-1) 0 var(--space-2);
  border-right: 1px solid var(--color-border-strong);
  background: var(--color-surface-raised);
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--color-text-soft);
}

.row__title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row__buttons {
  display: inline-flex;
  gap: 2px;
}

.row__button {
  display: inline-grid;
  place-items: center;
  width: 17px;
  height: 17px;
  padding: 0;
  border: 1px solid var(--color-border);
  border-radius: 4px;
  background: transparent;
  color: var(--color-text-muted);
  font: inherit;
  font-size: 0.625rem;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
}

.row__button:hover {
  color: var(--color-text);
  border-color: var(--color-border-strong);
}

.row__button--on {
  border-color: var(--color-accent);
  background: var(--color-accent-bg);
  color: var(--color-accent-text);
}

.lane {
  position: relative;
  flex: none;
  height: 100%;
}

/* trilha muda ou oculta fica esmaecida; bloqueada fica com o cabeçalho riscado */
.row--muted .lane,
.row--hidden .lane {
  opacity: 0.45;
}

.row--locked .row__header {
  background-image: repeating-linear-gradient(135deg, transparent 0 5px, rgb(255 255 255 / 0.05) 5px 10px);
}

.transition {
  position: absolute;
  top: 3px;
  bottom: 3px;
  z-index: 2;
  background-image: repeating-linear-gradient(45deg, rgb(255 255 255 / 0.55) 0 3px, transparent 3px 6px);
  pointer-events: none;
}
</style>
