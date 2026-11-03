<script setup lang="ts">
/* De onde vem o vídeo de um clipe ou de um PiP: um arquivo avulso ou uma fonte sincronizada. A spec exige
   exatamente um dos dois, então escolher uma fonte limpa o arquivo e voltar para "avulso" limpa a fonte. */
import { computed } from 'vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import { setOrigin, sourceNames } from '@/lib/editorSpec'
import { useEditorStore } from '@/stores/editor'
import FileField from './FileField.vue'

const props = defineProps<{
  /** O item da spec: "timeline.2" ou "overlays.0". */
  base: string
  /** O que o início e o fim significam quando a origem é uma fonte. */
  sourceHint: string
}>()

const editor = useEditorStore()

const source = computed(() => {
  const value = editor.get(`${props.base}.source`)
  return typeof value === 'string' ? value : ''
})
const file = computed(() => {
  const value = editor.get(`${props.base}.src`)
  return typeof value === 'string' ? value : ''
})
const options = computed(() => {
  const names = editor.spec ? sourceNames(editor.spec) : []
  // uma fonte que a spec cita e que não existe mais continua visível, para a pessoa trocar
  const known = source.value && !names.includes(source.value) ? [...names, source.value] : names
  return known.map((name) => ({ value: name, label: name }))
})

function chooseOrigin(name: string): void {
  editor.mutate((spec) => setOrigin(spec, props.base, name))
}
</script>

<template>
  <AppSelect
    :model-value="source"
    label="Origem"
    placeholder="Arquivo avulso"
    :options="options"
    :hint="source ? sourceHint : undefined"
    @update:model-value="chooseOrigin"
  />
  <FileField v-if="!source" :model-value="file" label="Arquivo" @update:model-value="editor.setField(`${base}.src`, $event || undefined)" />
</template>
