<script setup lang="ts">
/* Um campo da spec ligado ao store do editor: lê o valor por caminho, mostra o padrão do schema quando a spec
   não tem o campo e escreve de volta por `setField`. Opções e limites vêm do schema, não de uma lista copiada. */
import { computed } from 'vue'
import AppCheckbox from '@/components/ui/AppCheckbox.vue'
import AppInput from '@/components/ui/AppInput.vue'
import AppNumberInput from '@/components/ui/AppNumberInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import { numberLimits, propOf, selectChoices, type FieldDef } from '@/lib/editorFields'
import type { OptionItem } from '@/lib/editorLabels'
import { fieldInfo } from '@/lib/editorSchema'
import { useEditorStore } from '@/stores/editor'
import FileField from './FileField.vue'

const props = defineProps<{
  field: FieldDef
  /** Caminho do item na spec ("timeline.2", "audio"); o campo é `${base}.${field.key}`. */
  base: string
  /** Opções vindas de fora (as transições do catálogo), no lugar das do schema. */
  choices?: OptionItem[]
  disabled?: boolean
}>()

const editor = useEditorStore()

const path = computed(() => (props.base ? `${props.base}.${props.field.key}` : props.field.key))
const info = computed(() => fieldInfo(editor.schema, props.field.def, propOf(props.field)))
const stored = computed(() => editor.get(path.value))

function schemaDefault(type: 'string' | 'number' | 'boolean'): unknown {
  const value = info.value?.default
  return typeof value === type ? value : undefined
}

const numberValue = computed<number | null>(() => {
  if (typeof stored.value === 'number') return stored.value
  if (props.field.optional) return null
  return (props.field.fallback as number | undefined) ?? (schemaDefault('number') as number | undefined) ?? null
})

const textValue = computed(() => {
  if (typeof stored.value === 'string') return stored.value
  if (props.field.optional) return ''
  return String(props.field.fallback ?? schemaDefault('string') ?? '')
})

const selectValue = computed(() => {
  if (typeof stored.value === 'string') return stored.value
  // lista que aceita "nenhuma" mostra a opção vazia; as outras, o padrão
  if (props.field.emptyLabel !== undefined) return ''
  return String(props.field.fallback ?? schemaDefault('string') ?? '')
})

const checkValue = computed(() =>
  typeof stored.value === 'boolean' ? stored.value : ((schemaDefault('boolean') as boolean | undefined) ?? false),
)

const limits = computed(() => numberLimits(props.field, info.value))
const options = computed(() => selectChoices(props.field, info.value, selectValue.value, props.choices))

function write(value: unknown): void {
  editor.setField(path.value, value === '' || value === null ? undefined : value)
}
</script>

<template>
  <AppNumberInput
    v-if="field.kind === 'number'"
    :label="field.label"
    :model-value="numberValue"
    :min="limits.min"
    :max="limits.max"
    :step="limits.step"
    :placeholder="field.placeholder"
    :hint="field.hint"
    :disabled="disabled"
    @update:model-value="write"
  />
  <AppInput
    v-else-if="field.kind === 'text'"
    :label="field.label"
    :model-value="textValue"
    :placeholder="field.placeholder"
    :hint="field.hint"
    :disabled="disabled"
    @update:model-value="write"
  />
  <AppSelect
    v-else-if="field.kind === 'select'"
    :label="field.label"
    :model-value="selectValue"
    :options="options"
    :placeholder="field.emptyLabel"
    :hint="field.hint"
    :disabled="disabled"
    @update:model-value="write"
  />
  <!-- a caixa de marcar não tem rótulo acima: desce até a linha dos campos ao lado -->
  <div v-else-if="field.kind === 'check'" class="check-cell">
    <AppCheckbox
      :label="field.label"
      :model-value="checkValue"
      :hint="field.hint"
      :disabled="disabled"
      @update:model-value="write"
    />
  </div>
  <FileField
    v-else
    :label="field.label"
    :model-value="typeof stored === 'string' ? stored : ''"
    :placeholder="field.placeholder"
    @update:model-value="write"
  />
</template>

<style scoped>
.check-cell {
  display: flex;
  align-items: center;
  align-self: end;
  min-height: 2.5rem;
}
</style>
