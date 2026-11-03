<script setup lang="ts">
/* A aba Propriedades: o formulário da spec, em blocos (saída, fontes, trechos, sobreposições, legendas e áudio).
   Quais blocos estão abertos fica guardado no navegador. Tudo que não tem formulário se edita na aba JSON. */
import { reactive, watch } from 'vue'
import { readStored, writeStored } from '@/lib/storage'
import { useEditorStore } from '@/stores/editor'
import AudioSection from './AudioSection.vue'
import CaptionsSettingsSection from './CaptionsSettingsSection.vue'
import OutputSection from './OutputSection.vue'
import OverlaysSection from './OverlaysSection.vue'
import SegmentsSection from './SegmentsSection.vue'
import SourcesSection from './SourcesSection.vue'

const STORAGE_KEY = 'dmaker.editor.sections'
const SECTIONS = ['output', 'sources', 'segments', 'overlays', 'captions', 'audio'] as const

const editor = useEditorStore()

function readOpen(): Record<string, boolean> {
  const open: Record<string, boolean> = Object.fromEntries(SECTIONS.map((id) => [id, true]))
  try {
    const saved = JSON.parse(readStored(STORAGE_KEY) ?? '{}') as Record<string, unknown>
    for (const id of SECTIONS) if (typeof saved[id] === 'boolean') open[id] = saved[id]
  } catch {
    // preferência ilegível: todos os blocos abertos
  }
  return open
}

const open = reactive(readOpen())

watch(open, (value) => writeStored(STORAGE_KEY, JSON.stringify(value)), { deep: true })
</script>

<template>
  <div v-if="editor.spec" class="properties">
    <OutputSection v-model:open="open.output" />
    <SourcesSection v-model:open="open.sources" />
    <SegmentsSection v-model:open="open.segments" />
    <OverlaysSection v-model:open="open.overlays" />
    <CaptionsSettingsSection v-model:open="open.captions" />
    <AudioSection v-model:open="open.audio" />
  </div>
</template>

<style scoped>
.properties {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
</style>
