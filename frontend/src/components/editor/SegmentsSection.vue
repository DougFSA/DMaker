<script setup lang="ts">
/* Os trechos da linha do tempo: um cartão por trecho (clipe, imagem ou cartão), com subir, descer, duplicar e remover. */
import { computed } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import { OPEN_CARDS_LIMIT, useCardExpansion } from '@/composables/useCardExpansion'
import { SEGMENT_TYPES, SEGMENT_TYPE_LABEL, newSegment, stableKey, type SegmentType } from '@/lib/editorSpec'
import { useEditorStore } from '@/stores/editor'
import EditorSection from './EditorSection.vue'
import SegmentCard from './SegmentCard.vue'

const open = defineModel<boolean>('open', { default: true })
const editor = useEditorStore()

const segments = computed(() => (editor.get('timeline') as Array<Record<string, unknown>> | undefined) ?? [])
const cards = useCardExpansion(segments.value.length)

function add(type: SegmentType): void {
  editor.mutate((spec) => {
    ;(spec.timeline as unknown[]).push(newSegment(type))
  })
  cards.reveal(segments.value.at(-1))
}
</script>

<template>
  <EditorSection v-model:open="open" title="Trechos" :count="segments.length">
    <template #actions>
      <AppButton v-for="type in SEGMENT_TYPES" :key="type" size="sm" @click="add(type)">
        Adicionar {{ SEGMENT_TYPE_LABEL[type].toLowerCase() }}
      </AppButton>
    </template>

    <p v-if="segments.length > OPEN_CARDS_LIMIT" class="hint">
      Com muitos trechos, os cartões começam recolhidos. Clique no cartão para abrir.
    </p>
    <p v-if="segments.length === 0" class="hint">Sem trechos ainda. Adicione um clipe, uma imagem ou um cartão.</p>

    <ul class="cards">
      <li v-for="(segment, index) in segments" :key="stableKey(segment)">
        <SegmentCard
          :index="index"
          :segment="segment"
          :count="segments.length"
          :expanded="cards.isOpen(segment)"
          @update:expanded="cards.setOpen(segment, $event)"
        />
      </li>
    </ul>
  </EditorSection>
</template>

<style scoped>
.hint {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.cards {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}
</style>
