<script setup lang="ts">
/* Os takes da voz gravada aberta no painel Áudio: o que toca agora e os outros do mesmo trecho (o punch-in guarda a gravação
   antiga aqui). Trocar é um passo do desfazer (`voiceover_take_set`); nada é apagado. */
import { computed } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useAudioPanelStore } from '@/stores/audioPanel'
import { useEditorStore } from '@/stores/editor'

interface TakeEntry {
  index: number
  label: string
  src: string
}

const panel = useAudioPanelStore()
const editor = useEditorStore()

const current = computed(() => {
  const found = panel.itemId ? editor.findItem(panel.itemId) : null
  if (!found || found.item.kind !== 'voiceover') return null
  const takes = (found.item.extra.takes as TakeEntry[] | undefined) ?? []
  return takes.length > 0 ? { label: String(found.item.extra.take_label ?? 'Take atual'), takes } : null
})

function swap(take: TakeEntry): void {
  if (!panel.target) return
  void editor.applyOp({ type: 'voiceover_take_set', target: panel.target, take: take.index }).then((ok) => {
    if (ok) panel.soundChanged()
  })
}
</script>

<template>
  <section v-if="current" class="takes" aria-label="Takes desta voz" data-voice-takes>
    <strong class="takes__title">Takes deste trecho</strong>
    <span class="takes__now" data-take-current>Tocando: {{ current.label }}</span>
    <ul class="takes__list">
      <li v-for="take in current.takes" :key="take.index">
        <AppButton size="sm" :disabled="panel.busy" :title="`Trocar para ${take.label} (${take.src})`" data-take-swap @click="swap(take)">
          {{ take.label }}
        </AppButton>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.takes {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
}

.takes__now {
  color: var(--color-text-soft);
}

.takes__list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}
</style>
