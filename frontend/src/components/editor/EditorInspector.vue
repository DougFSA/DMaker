<script setup lang="ts">
/* As abas do inspetor (Propriedades, JSON, Legendas e Preview), vindas do registro de painéis. Uma aba que já foi
   aberta continua montada ao trocar: o texto do JSON que a pessoa está digitando e o preview escolhido não se perdem. */
import { computed, reactive, watch } from 'vue'
import { TabsContent, TabsList, TabsRoot, TabsTrigger } from 'reka-ui'
import { useEditorStore } from '@/stores/editor'
import EditorSlot from './EditorSlot.vue'
import { panelsIn } from './panels'

const editor = useEditorStore()
const active = defineModel<string>({ required: true })

const tabs = computed(() => panelsIn('inspector').filter((panel) => !panel.when || panel.when(editor)))
const visited = reactive(new Set<string>())

watch(
  active,
  (id) => {
    visited.add(id)
  },
  { immediate: true },
)

// a aba que a pessoa deixou aberta pode não existir neste projeto (Legendas, num projeto sem legendas automáticas):
// ela não fica numa aba que não existe, nem na abertura nem quando as legendas somem
watch(
  [tabs, active],
  ([list, id]) => {
    if (!list.some((panel) => panel.id === id)) active.value = 'properties'
  },
  { immediate: true },
)
</script>

<template>
  <TabsRoot v-model="active" class="inspector">
    <TabsList class="tabs__list" aria-label="Painéis do projeto">
      <TabsTrigger v-for="panel in tabs" :key="panel.id" :value="panel.id" class="tabs__tab">
        {{ panel.title }}
      </TabsTrigger>
    </TabsList>
    <TabsContent
      v-for="panel in tabs"
      :key="panel.id"
      :value="panel.id"
      :force-mount="visited.has(panel.id)"
      class="inspector__panel"
    >
      <EditorSlot :panel="panel" />
    </TabsContent>
  </TabsRoot>
</template>

<style scoped src="../ui/tabs.css"></style>

<style scoped>
.inspector__panel {
  padding-top: var(--space-4);
}

/* aba já aberta fica montada, só escondida */
.inspector__panel[data-state='inactive'] {
  display: none;
}

.inspector__panel:focus-visible {
  outline-offset: 4px;
}
</style>
