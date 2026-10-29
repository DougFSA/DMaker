<script setup lang="ts">
/* Campo de caminho de arquivo: o texto editável e o botão que abre o navegador de arquivos do servidor. */
import AppButton from '@/components/ui/AppButton.vue'
import AppInput from '@/components/ui/AppInput.vue'
import { useEditorFilePicker } from '@/composables/useEditorFilePicker'

defineProps<{ label: string; placeholder?: string }>()
const model = defineModel<string>({ default: '' })

const pickFile = useEditorFilePicker()

async function choose(): Promise<void> {
  const path = await pickFile?.()
  if (path) model.value = path
}
</script>

<template>
  <div class="file-field">
    <AppInput v-model="model" :label="label" :placeholder="placeholder" />
    <AppButton v-if="pickFile" :aria-label="`Escolher arquivo para ${label}`" @click="choose">
      Escolher...
    </AppButton>
  </div>
</template>

<style scoped>
.file-field {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
  gap: var(--space-2);
  /* um caminho é longo: o campo ocupa a linha inteira da grade de campos */
  grid-column: 1 / -1;
}
</style>
