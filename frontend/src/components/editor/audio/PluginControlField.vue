<script setup lang="ts">
/* Um controle de um plugin LV2 ou LADSPA, desenhado pelo que o próprio plugin declara (nome, faixa e padrão lidos pelo
   ffmpeg na varredura): número, inteiro ou caixa de marcar. O número digitado espera 300 ms de silêncio e vale um passo do
   desfazer; a caixa grava na hora. O valor mora em `params.<nome>` do efeito, e o que a pessoa não mexeu fica de fora, com o
   padrão do plugin. */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { AudioEffectSettings, PluginControl } from '@/api'
import AppCheckbox from '@/components/ui/AppCheckbox.vue'
import AppNumberInput from '@/components/ui/AppNumberInput.vue'
import { effectPath } from '@/lib/audioEffects'
import { clampControl, controlValue } from '@/lib/audioPlugins'
import { useEditorStore } from '@/stores/editor'

/** A espera do número digitado, a mesma dos outros campos de efeito. */
const DEBOUNCE_MS = 300

const props = defineProps<{
  control: PluginControl
  effect: AudioEffectSettings
  listPath: string
  index: number
}>()

const editor = useEditorStore()

const path = computed(() => effectPath(props.listPath, props.index, `params.${props.control.name}`))
const pending = ref<{ path: string; value: number | null } | null>(null)
let timer: ReturnType<typeof setTimeout> | null = null

const current = computed(() => controlValue(props.effect, props.control))
const shown = computed(() => (pending.value ? pending.value.value : current.value))

const problem = computed(() => {
  const typed = pending.value?.value
  if (typed === null || typed === undefined || clampControl(props.control, typed) === typed) return undefined
  const { minimum, maximum } = props.control
  if (minimum !== null && maximum !== null) return `Use de ${minimum} a ${maximum}.`
  return minimum !== null ? `Use ${minimum} ou mais.` : `Use ${maximum} ou menos.`
})

function commit(): void {
  if (timer) clearTimeout(timer)
  timer = null
  const waiting = pending.value
  if (!waiting) return
  pending.value = null
  // campo esvaziado: o controle volta ao padrão do plugin (a chave sai da spec)
  editor.setField(waiting.path, waiting.value === null ? undefined : clampControl(props.control, waiting.value))
}

function onNumber(value: number | null): void {
  pending.value = { path: path.value, value }
  if (timer) clearTimeout(timer)
  timer = setTimeout(commit, DEBOUNCE_MS)
}

function onToggle(on: boolean): void {
  commit()
  editor.setField(path.value, on ? 1 : 0)
}

// o cartão foi reaproveitado por outro efeito: o que esperava vai para o caminho de antes
watch(path, commit, { flush: 'sync' })
const stopListening = editor.onPendingEdits(commit)
onBeforeUnmount(() => {
  stopListening()
  commit()
})
</script>

<template>
  <div class="plugin-check" v-if="control.kind === 'boolean'" :data-plugin-control="control.name">
    <AppCheckbox :label="control.label" :model-value="current !== 0" @update:model-value="onToggle" />
  </div>
  <AppNumberInput
    v-else
    :label="control.label"
    :model-value="shown"
    :min="control.minimum ?? undefined"
    :max="control.maximum ?? undefined"
    :step="control.kind === 'integer' ? 1 : 0.1"
    :hint="`${control.name}, padrão ${control.default}`"
    :error="problem"
    :data-plugin-control="control.name"
    @update:model-value="onNumber"
    @focusout="commit"
  />
</template>

<style scoped>
.plugin-check {
  grid-column: 1 / -1;
}
</style>
