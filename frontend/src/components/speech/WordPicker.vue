<script setup lang="ts">
/* A transcrição de uma fala, palavra por palavra, em linhas de fôlego (uma pausa de 0,25 s abre a linha seguinte).
   A pessoa clica na primeira e na última palavra do trecho errado e o trecho fica marcado; clicar duas vezes na
   mesma palavra escolhe só ela, e um clique novo depois de escolher recomeça. */
import { computed, ref, watch } from 'vue'
import type { SpeechWord } from '@/api'
import {
  BREATH_PAUSE_S,
  describeSelection,
  formatSeconds,
  formatSecondsPrecise,
  groupWordsByBreath,
  selectionFor,
  type WordSelection,
} from '@/lib/speech'

const props = withDefaults(defineProps<{ words: SpeechWord[]; pauseSeconds?: number }>(), { pauseSeconds: BREATH_PAUSE_S })

const selection = defineModel<WordSelection | null>({ default: null })

/** A primeira palavra clicada, enquanto a última não vem. */
const anchor = ref<number | null>(null)

const lines = computed(() =>
  groupWordsByBreath(props.words, props.pauseSeconds).map((indexes) => ({
    indexes,
    start: props.words[indexes[0]!]?.start ?? 0,
  })),
)
const status = computed(() => describeSelection(selection.value, anchor.value !== null))

// uma transcrição nova não tem a ver com o clique que ficou pela metade
watch(
  () => props.words,
  () => {
    anchor.value = null
  },
)

function pick(index: number): void {
  if (anchor.value === null || selection.value) {
    anchor.value = index
    selection.value = null
    return
  }
  selection.value = selectionFor(props.words, anchor.value, index)
  anchor.value = null
}

function isInside(index: number): boolean {
  const picked = selection.value
  return !!picked && index >= picked.first && index <= picked.last
}

function wordTitle(word: SpeechWord): string {
  return `${formatSecondsPrecise(word.start)} a ${formatSecondsPrecise(word.end)} s`
}
</script>

<template>
  <div class="picker">
    <p class="picker__hint">
      Clique na primeira e na última palavra do trecho errado (uma palavra só: clique nela duas vezes).
    </p>
    <div class="picker__words" role="group" aria-label="Palavras da transcrição">
      <div v-for="line in lines" :key="line.start + ':' + line.indexes[0]" class="picker__line">
        <span class="picker__time">{{ formatSeconds(line.start) }} s</span>
        <button
          v-for="index in line.indexes"
          :key="index"
          type="button"
          :class="['word', { 'is-selected': isInside(index), 'is-anchor': anchor === index }]"
          :aria-pressed="isInside(index) || anchor === index"
          :title="wordTitle(words[index]!)"
          @click="pick(index)"
        >
          {{ words[index]!.text }}
        </button>
      </div>
    </div>
    <p class="picker__status" role="status">{{ status }}</p>
  </div>
</template>

<style scoped>
.picker {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.picker__hint {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.picker__words {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-height: 20rem;
  overflow-y: auto;
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-soft);
}

.picker__line {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--space-1) var(--space-2);
}

.picker__time {
  min-width: 3.5rem;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}

.word {
  padding: 0.1rem 0.4rem;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  font-size: var(--text-md);
  line-height: 1.5;
  transition:
    background var(--transition),
    border-color var(--transition);
}

.word:hover {
  background: var(--color-surface-hover);
}

.word.is-anchor {
  border-color: var(--color-accent);
  background: var(--color-accent-bg);
}

.word.is-selected {
  border-color: var(--color-accent);
  background: var(--color-accent);
  color: var(--color-on-accent);
}

.picker__status {
  font-size: var(--text-sm);
  font-weight: 500;
  overflow-wrap: anywhere;
}
</style>
