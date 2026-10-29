<script setup lang="ts">
import { computed } from 'vue'
import type { InfographicInfo, InfographicParam } from '@/api'
import { formProblems, type FieldValue } from '@/lib/infographics'

/** O formulário montado a partir do esquema do modelo: um campo por parâmetro, com o rótulo e os limites dele. */
const props = defineProps<{ info: InfographicInfo; modelValue: Record<string, FieldValue | undefined> }>()
const emit = defineEmits<{ 'update:modelValue': [values: Record<string, FieldValue | undefined>] }>()

const problems = computed(() => formProblems(props.info, props.modelValue))

function setValue(name: string, value: FieldValue | undefined): void {
  emit('update:modelValue', { ...props.modelValue, [name]: value })
}

function hint(param: InfographicParam): string {
  const parts: string[] = []
  if (param.description) parts.push(param.description)
  if (param.min !== undefined && param.max !== undefined) parts.push(`De ${param.min} a ${param.max}.`)
  if (param.type === 'color') parts.push('Uma cor da marca (accent, primary, white...) ou #RRGGBB.')
  if (param.type === 'path') parts.push('O caminho do arquivo no disco.')
  return parts.join(' ')
}

function onInput(param: InfographicParam, event: Event): void {
  setValue(param.name, (event.target as HTMLInputElement).value)
}

function onCheck(param: InfographicParam, event: Event): void {
  setValue(param.name, (event.target as HTMLInputElement).checked)
}
</script>

<template>
  <form class="form" @submit.prevent>
    <div v-for="param in info.params" :key="param.name" class="field">
      <template v-if="param.type === 'bool'">
        <label class="check">
          <input
            type="checkbox"
            :checked="modelValue[param.name] === true"
            :aria-describedby="`${info.name}-${param.name}-hint`"
            @change="onCheck(param, $event)"
          />
          <span>{{ param.label }}</span>
        </label>
      </template>
      <template v-else>
        <label class="field-label" :for="`${info.name}-${param.name}`">
          {{ param.label }}<span v-if="param.required" class="required" aria-label="obrigatório"> *</span>
        </label>
        <select
          v-if="param.type === 'choice'"
          :id="`${info.name}-${param.name}`"
          class="input"
          :value="String(modelValue[param.name] ?? '')"
          :aria-describedby="`${info.name}-${param.name}-hint`"
          @change="onInput(param, $event)"
        >
          <option v-if="!param.required && param.default === undefined" value="">(nenhum)</option>
          <option v-for="option in param.options" :key="option" :value="option">{{ option }}</option>
        </select>
        <input
          v-else
          :id="`${info.name}-${param.name}`"
          class="input"
          type="text"
          :inputmode="param.type === 'number' || param.type === 'integer' ? 'decimal' : undefined"
          :value="String(modelValue[param.name] ?? '')"
          :placeholder="param.example !== undefined ? String(param.example) : ''"
          :aria-invalid="problems[param.name] ? 'true' : undefined"
          :aria-describedby="`${info.name}-${param.name}-hint`"
          autocomplete="off"
          @input="onInput(param, $event)"
        />
      </template>
      <p :id="`${info.name}-${param.name}-hint`" class="field-hint">{{ hint(param) }}</p>
      <p v-if="problems[param.name]" class="problem" role="alert">{{ problems[param.name] }}</p>
    </div>
  </form>
</template>

<style scoped>
.form {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 16rem), 1fr));
  gap: var(--space-4);
}

.required {
  color: var(--color-error);
}

.problem {
  font-size: var(--text-xs);
  color: var(--color-error);
}
</style>
