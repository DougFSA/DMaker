<script setup lang="ts">
/* Um campo de um som gerado, desenhado pelo que o catálogo diz dele (número, inteiro, caixa de marcar, escolha ou texto):
   tanto um parâmetro do gerador (`audio.generated.N.params.frequency_hz`) quanto um campo do item (`start`, `duration`).
   O número digitado espera 300 ms de silêncio e vale um passo do desfazer por campo; a caixa e a escolha gravam na hora.
   Número fora da faixa é limitado antes de ir para a spec, e o servidor recusa o resto. */
import { computed, onBeforeUnmount, ref } from 'vue'
import type { AudioEffectParam, AudioEffectValue } from '@/api'
import AppCheckbox from '@/components/ui/AppCheckbox.vue'
import AppInput from '@/components/ui/AppInput.vue'
import AppNumberInput from '@/components/ui/AppNumberInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import { choiceText, choiceValue, clampParam } from '@/lib/audioEffects'
import { useEditorStore } from '@/stores/editor'

/** A espera do número digitado: cada tecla reinicia, e a spec só muda quando a pessoa para (a mesma do painel Filtros). */
const DEBOUNCE_MS = 300

const props = defineProps<{
  param: Pick<AudioEffectParam, 'name' | 'label' | 'kind' | 'unit' | 'hint' | 'minimum' | 'maximum' | 'options'>
  /** O valor que a spec tem (ou o padrão do catálogo). */
  value: AudioEffectValue | null
  /** Onde o campo mora na spec. */
  path: string
}>()

const editor = useEditorStore()
const pending = ref<number | string | null | undefined>(undefined)
let timer: ReturnType<typeof setTimeout> | null = null

const numberValue = computed<number | null>(() => {
  if (typeof pending.value === 'number') return pending.value
  if (pending.value === null) return null
  return typeof props.value === 'number' ? props.value : null
})
const textValue = computed(() => (typeof pending.value === 'string' ? pending.value : typeof props.value === 'string' ? props.value : ''))

function commit(): void {
  if (timer) clearTimeout(timer)
  timer = null
  const waiting = pending.value
  if (waiting === undefined) return
  pending.value = undefined
  // campo esvaziado: a spec fica como estava (apagar para digitar outro valor não pode zerar o som)
  if (typeof waiting === 'number') editor.setField(props.path, clampParam(props.param, waiting))
  else if (typeof waiting === 'string' && waiting !== '') editor.setField(props.path, waiting)
}

/** Número ou texto digitado: espera a pessoa parar para gravar (cada tecla reinicia a espera). */
function onTyped(value: number | string | null): void {
  pending.value = value
  if (timer) clearTimeout(timer)
  timer = value === null || value === '' ? null : setTimeout(commit, DEBOUNCE_MS)
}

function onDiscrete(value: boolean | string | number): void {
  commit()
  editor.flushPendingEdits()
  editor.setField(props.path, value)
}

const stopListening = editor.onPendingEdits(commit)
onBeforeUnmount(() => {
  stopListening()
  commit()
})
</script>

<template>
  <AppNumberInput
    v-if="param.kind === 'number' || param.kind === 'integer'"
    :label="param.label"
    :model-value="numberValue"
    :min="param.minimum ?? undefined"
    :max="param.maximum ?? undefined"
    :step="param.kind === 'integer' ? 1 : 'any'"
    :unit="param.unit || undefined"
    :hint="param.hint || undefined"
    :data-sound-field="param.name"
    @update:model-value="onTyped"
    @focusout="commit"
  />
  <AppSelect
    v-else-if="param.kind === 'choice'"
    :label="param.label"
    :model-value="choiceText(value)"
    :options="param.options.map((option) => ({ value: option, label: option }))"
    :hint="param.hint || undefined"
    :data-sound-field="param.name"
    @update:model-value="(text: string) => onDiscrete(choiceValue(param, text))"
  />
  <AppInput
    v-else-if="param.kind === 'text'"
    :label="param.label"
    :model-value="textValue"
    :hint="param.hint || undefined"
    :data-sound-field="param.name"
    @update:model-value="onTyped"
    @focusout="commit"
  />
  <div v-else-if="param.kind === 'boolean'" class="check-cell" :data-sound-field="param.name">
    <AppCheckbox :label="param.label" :model-value="value === true" :hint="param.hint || undefined" @update:model-value="onDiscrete" />
  </div>
</template>

<style scoped>
.check-cell {
  grid-column: 1 / -1;
}
</style>
