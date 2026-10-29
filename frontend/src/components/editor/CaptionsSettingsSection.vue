<script setup lang="ts">
/* A configuração das legendas automáticas (origem, idioma, modelo e estilo). A tabela com o texto de cada frase
   fica na aba Legendas, que aparece depois que o primeiro render gerou as legendas. */
import { computed } from 'vue'
import AppCheckbox from '@/components/ui/AppCheckbox.vue'
import { CAPTION_FIELDS } from '@/lib/editorFields'
import { setCaptionsEnabled } from '@/lib/editorSpec'
import { useEditorStore } from '@/stores/editor'
import EditorSection from './EditorSection.vue'
import FieldGrid from './FieldGrid.vue'

const open = defineModel<boolean>('open', { default: true })
const editor = useEditorStore()

const enabled = computed(() => !!editor.get('captions'))
</script>

<template>
  <EditorSection v-model:open="open" title="Legendas">
    <AppCheckbox
      :model-value="enabled"
      label="Gerar legendas automáticas"
      @update:model-value="editor.mutate((spec) => setCaptionsEnabled(spec, $event))"
    />
    <FieldGrid v-if="enabled" :fields="CAPTION_FIELDS" base="captions" />
  </EditorSection>
</template>
