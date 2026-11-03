<script setup lang="ts">
/* As sobreposições do vídeo (texto, imagem, picture-in-picture e barra de progresso), uma por cartão. */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import { OPEN_CARDS_LIMIT, useCardExpansion } from '@/composables/useCardExpansion'
import { OVERLAY_TYPES, OVERLAY_TYPE_LABEL, newOverlay, stableKey, type OverlayType } from '@/lib/editorSpec'
import { useEditorStore } from '@/stores/editor'
import EditorSection from './EditorSection.vue'
import OverlayCard from './OverlayCard.vue'

const open = defineModel<boolean>('open', { default: true })
const editor = useEditorStore()

const overlays = computed(() => (editor.get('overlays') as Array<Record<string, unknown>> | undefined) ?? [])
const cards = useCardExpansion(overlays.value.length)
const list = ref<HTMLElement | null>(null)

/** Mostra a sobreposição escolhida no palco: abre o bloco e o cartão e leva o cartão para dentro da tela. */
function revealSelected(): void {
  const index = editor.selectedOverlay
  if (index === null) return
  open.value = true
  cards.reveal(overlays.value[index])
  void nextTick(() => list.value?.querySelector(`[data-overlay-card="${index}"]`)?.scrollIntoView?.({ block: 'nearest' }))
}

watch(() => editor.overlayReveal, revealSelected)
onMounted(revealSelected)

function add(type: OverlayType): void {
  editor.mutate((spec) => {
    ;(spec.overlays as unknown[]).push(newOverlay(type))
  })
  cards.reveal(overlays.value.at(-1))
}
</script>

<template>
  <EditorSection v-model:open="open" title="Sobreposições" :count="overlays.length">
    <template #actions>
      <AppButton v-for="type in OVERLAY_TYPES" :key="type" size="sm" @click="add(type)">
        Adicionar {{ OVERLAY_TYPE_LABEL[type].toLowerCase() }}
      </AppButton>
    </template>

    <p v-if="overlays.length > OPEN_CARDS_LIMIT" class="hint">
      Com muitas sobreposições, os cartões começam recolhidos. Clique no cartão para abrir.
    </p>
    <p v-if="overlays.length === 0" class="hint">Sem sobreposições ainda: textos, logos, vídeos em PiP e barra de progresso.</p>

    <ul ref="list" class="cards">
      <li v-for="(overlay, index) in overlays" :key="stableKey(overlay)" :data-overlay-card="index">
        <OverlayCard
          :index="index"
          :overlay="overlay"
          :count="overlays.length"
          :expanded="cards.isOpen(overlay)"
          @update:expanded="cards.setOpen(overlay, $event)"
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
