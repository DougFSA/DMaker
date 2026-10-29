<script setup lang="ts">
/* Um campo da spec ligado ao store do editor: lê o valor por caminho, mostra o padrão do schema quando a spec
   não tem o campo e escreve de volta por `setField`. Opções e limites vêm do schema, não de uma lista copiada.
   Com `debounceMs`, o texto e o número esperam a pessoa parar de digitar antes de gravar (o painel Filtros usa 300 ms);
   lista e caixa de marcar gravam na hora. */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
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
  /** Espera, em milissegundos, antes de gravar o que se digita em campo de texto ou número. */
  debounceMs?: number
}>()

const editor = useEditorStore()

const path = computed(() => (props.base ? `${props.base}.${props.field.key}` : props.field.key))
const info = computed(() => fieldInfo(editor.schema, props.field.def, propOf(props.field)))

/** O que a pessoa digitou e ainda não foi para a spec, com o caminho de quando digitou (a seleção pode mudar antes). */
const pending = ref<{ path: string; value: unknown } | null>(null)
let timer: ReturnType<typeof setTimeout> | null = null

function commit(): void {
  if (timer) clearTimeout(timer)
  timer = null
  const waiting = pending.value
  if (!waiting) return
  pending.value = null
  editor.setField(waiting.path, waiting.value)
}

// enquanto a digitação espera, o campo mostra o que foi digitado, não o valor antigo da spec
const stored = computed(() => (pending.value ? pending.value.value : editor.get(path.value)))

function schemaDefault(type: 'string' | 'number' | 'boolean'): unknown {
  const value = info.value?.default
  return typeof value === type ? value : undefined
}

const numberValue = computed<number | null>(() => {
  if (typeof stored.value === 'number') return stored.value
  // campo esvaziado pela pessoa: fica vazio até gravar, em vez de pular para o padrão no meio da digitação
  if (props.field.optional || pending.value) return null
  return (props.field.fallback as number | undefined) ?? (schemaDefault('number') as number | undefined) ?? null
})

const textValue = computed(() => {
  if (typeof stored.value === 'string') return stored.value
  if (props.field.optional || pending.value) return ''
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

/** `typed`: veio de teclado (texto, número), o único que pode esperar. */
function write(value: unknown, typed = false): void {
  const next = value === '' || value === null ? undefined : value
  if (typed && props.debounceMs) {
    pending.value = { path: path.value, value: next }
    if (timer) clearTimeout(timer)
    timer = setTimeout(commit, props.debounceMs)
    return
  }
  commit()
  editor.setField(path.value, next)
}

// outro caminho (a seleção mudou e o campo foi reaproveitado): o que esperava vai para o caminho de antes
watch(path, commit, { flush: 'sync' })

// a tela do editor grava a digitação que espera antes de salvar ou operar na linha do tempo
const stopListening = editor.onPendingEdits(commit)
onBeforeUnmount(() => {
  stopListening()
  commit()
})
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
    @update:model-value="write($event, true)"
    @focusout="commit"
  />
  <AppInput
    v-else-if="field.kind === 'text'"
    :label="field.label"
    :model-value="textValue"
    :placeholder="field.placeholder"
    :hint="field.hint"
    :disabled="disabled"
    @update:model-value="write($event, true)"
    @focusout="commit"
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
    @update:model-value="write($event, true)"
    @focusout="commit"
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
