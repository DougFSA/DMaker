<script setup lang="ts">
/* O corpo de um efeito Plugin no cartão: o nome do plugin e, se ele não vai tocar aqui, o motivo; depois um campo por
   controle que o próprio plugin declara. Nada é específico de um plugin: a lista vem da varredura (GET /api/audio-plugins). */
import { computed, onMounted } from 'vue'
import type { AudioEffectSettings } from '@/api'
import { pluginProblem } from '@/lib/audioPlugins'
import { useAudioPluginsStore } from '@/stores/audioPlugins'
import PluginControlField from './PluginControlField.vue'

const props = defineProps<{
  effect: AudioEffectSettings
  listPath: string
  index: number
  /** Mostra o nome e o aviso (o campo `plugin`) ou os controles (o campo `params`). */
  part: 'name' | 'controls'
}>()

const plugins = useAudioPluginsStore()
onMounted(() => void plugins.load())

const plugin = computed(() => plugins.find(props.effect))
const problem = computed(() => (plugins.loaded ? pluginProblem(plugin.value) : ''))
const reference = computed(() => String(props.effect.plugin ?? ''))
</script>

<template>
  <div v-if="part === 'name'" class="plugin-name" data-plugin-name>
    <p class="plugin-name__title">
      {{ plugin?.name ?? reference }}
      <span class="plugin-name__format">{{ String(effect.format ?? '').toUpperCase() }}</span>
    </p>
    <p v-if="plugin?.maker" class="plugin-name__maker">{{ plugin.maker }}</p>
    <p v-if="problem" class="plugin-name__warn" role="status" data-plugin-problem>{{ problem }}</p>
  </div>
  <template v-else-if="plugin && plugin.usable">
    <PluginControlField
      v-for="control in plugin.controls"
      :key="control.name"
      :control="control"
      :effect="effect"
      :list-path="listPath"
      :index="index"
    />
    <p v-if="plugin.controls.length === 0" class="plugin-name__maker">Este plugin não tem controles.</p>
  </template>
</template>

<style scoped>
.plugin-name {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.plugin-name__title {
  margin: 0;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--color-text);
}

.plugin-name__format {
  margin-left: var(--space-1);
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--color-text-muted);
}

.plugin-name__maker {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.plugin-name__warn {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--color-warning-bg);
  color: var(--color-warning);
  font-size: var(--text-sm);
}
</style>
