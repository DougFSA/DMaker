<script setup lang="ts">
/* Abas de painéis na mesma página (Reka UI: setas movem o foco, Home e End vão às pontas). O conteúdo de cada
   aba entra pelo slot que tem o `value` dela como nome. Abas que são páginas (rotas) usam RouteTabs. */
import { TabsContent, TabsList, TabsRoot, TabsTrigger } from 'reka-ui'

export interface TabItem {
  value: string
  label: string
  disabled?: boolean
}

defineProps<{
  items: TabItem[]
  /** Nome do grupo de abas para leitor de tela ("Opções de voz"). */
  label: string
}>()

const active = defineModel<string>({ required: true })
</script>

<template>
  <TabsRoot v-model="active" class="tabs">
    <TabsList class="tabs__list" :aria-label="label">
      <TabsTrigger
        v-for="item in items"
        :key="item.value"
        :value="item.value"
        :disabled="item.disabled"
        class="tabs__tab"
      >
        {{ item.label }}
      </TabsTrigger>
    </TabsList>
    <TabsContent v-for="item in items" :key="item.value" :value="item.value" class="tabs__panel">
      <slot :name="item.value" />
    </TabsContent>
  </TabsRoot>
</template>

<style scoped src="./tabs.css"></style>

<style scoped>
.tabs__panel {
  padding-top: var(--space-4);
}

.tabs__panel:focus-visible {
  outline-offset: 4px;
}
</style>
