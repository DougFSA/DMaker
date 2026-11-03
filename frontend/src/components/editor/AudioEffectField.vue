<script setup lang="ts">
/* Um parâmetro de um efeito de áudio, desenhado pelo que o catálogo diz dele (número, inteiro, caixa de marcar ou
   escolha). O número digitado espera 300 ms de silêncio e vale um passo do desfazer por campo; a caixa e a escolha
   gravam na hora, cada uma num passo. Número fora da faixa do catálogo é limitado antes de ir para a spec. */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { AudioEffectParam, AudioEffectSettings } from '@/api'
import AppCheckbox from '@/components/ui/AppCheckbox.vue'
import AppNumberInput from '@/components/ui/AppNumberInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import { clampParam, effectPath, paramValue, setEffectFieldIn } from '@/lib/audioEffects'
import { useEditorStore } from '@/stores/editor'

/** A espera do número digitado: cada tecla reinicia, e a spec só muda quando a pessoa para (a mesma do painel Filtros). */
const EFFECT_DEBOUNCE_MS = 300

const props = defineProps<{
  param: AudioEffectParam
  effect: AudioEffectSettings
  /** Onde a cadeia mora na spec (`audio.voiceover.0.effects`) e a posição deste efeito nela. */
  listPath: string
  index: number
  /** Vazio é um valor (o intervalo do efeito): o campo some da spec em vez de voltar ao padrão. */
  optional?: boolean
  /** Diz o que há de errado com o número antes de gravar (o fim antes do início); nulo quando está certo. */
  check?: (value: number | null) => string | null
}>()

const editor = useEditorStore()

const path = computed(() => effectPath(props.listPath, props.index, props.param.name))

/** O que a pessoa digitou e ainda não foi para a spec, com o caminho de quando digitou (a ordem pode mudar antes). */
const pending = ref<{ path: string; value: number | null } | null>(null)
let timer: ReturnType<typeof setTimeout> | null = null

const stored = computed(() => paramValue(props.effect, props.param))
const numberValue = computed<number | null>(() => {
  if (pending.value) return pending.value.value
  return typeof stored.value === 'number' ? stored.value : null
})

const limits = computed(() => ({
  min: props.param.minimum ?? undefined,
  max: props.param.maximum ?? undefined,
}))

/** O número digitado fora da faixa não é gravado como está: avisa até a pessoa corrigir ou o campo gravar o limite. */
const rangeProblem = computed(() => {
  const typed = pending.value?.value
  if (typed === null || typed === undefined) return null
  if (clampParam(props.param, typed) === typed) return null
  const { minimum, maximum } = props.param
  if (minimum !== null && maximum !== null) return `Use de ${minimum} a ${maximum}.`
  return minimum !== null ? `Use ${minimum} ou mais.` : `Use ${maximum} ou menos.`
})
const problem = computed(() => rangeProblem.value ?? (pending.value && props.check ? props.check(pending.value.value) : null))

function writeNumber(waiting: { path: string; value: number | null }): boolean {
  if (waiting.value === null) {
    // campo esvaziado: no intervalo isso é "o item todo" e apaga a chave; nos outros a spec fica como estava
    if (!props.optional) return true
    editor.setField(waiting.path, undefined)
    return true
  }
  if (props.check?.(waiting.value)) return false
  editor.setField(waiting.path, clampParam(props.param, waiting.value))
  return true
}

function commit(): void {
  if (timer) clearTimeout(timer)
  timer = null
  const waiting = pending.value
  if (!waiting) return
  // o intervalo errado fica na tela com o aviso, sem ir para a spec
  if (!writeNumber(waiting)) return
  pending.value = null
}

function onNumber(value: number | null): void {
  pending.value = { path: path.value, value }
  if (timer) clearTimeout(timer)
  // campo vazio num parâmetro que não aceita vazio só grava ao sair do campo, senão apagar para digitar outro número já o devolveria
  timer = value === null && !props.optional ? null : setTimeout(commit, EFFECT_DEBOUNCE_MS)
}

function onDiscrete(value: boolean | string): void {
  commit()
  editor.flushPendingEdits()
  const { listPath, index } = props
  editor.mutate((draft) => setEffectFieldIn(draft, listPath, index, props.param.name, value))
}

// outro caminho (o efeito subiu ou desceu e o cartão foi reaproveitado): o que esperava vai para o caminho de antes
watch(path, commit, { flush: 'sync' })

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
    :min="limits.min"
    :max="limits.max"
    :step="param.kind === 'integer' ? 1 : 0.1"
    :unit="param.unit || undefined"
    :hint="param.hint || undefined"
    :error="problem ?? undefined"
    :data-effect-param="param.name"
    @update:model-value="onNumber"
    @focusout="commit"
  />
  <AppSelect
    v-else-if="param.kind === 'choice'"
    :label="param.label"
    :model-value="typeof stored === 'string' ? stored : ''"
    :options="param.options.map((option) => ({ value: option, label: option }))"
    :hint="param.hint || undefined"
    :data-effect-param="param.name"
    @update:model-value="onDiscrete"
  />
  <!-- a caixa de marcar ocupa a linha inteira da grade: o rótulo e a dica são longos para a coluna do número -->
  <div v-else class="check-cell" :data-effect-param="param.name">
    <AppCheckbox
      :label="param.label"
      :model-value="stored === true"
      :hint="param.hint || undefined"
      @update:model-value="onDiscrete"
    />
  </div>
</template>

<style scoped>
.check-cell {
  grid-column: 1 / -1;
}
</style>
