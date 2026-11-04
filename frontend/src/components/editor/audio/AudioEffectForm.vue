<script setup lang="ts">
/* O formulário dos parâmetros de um efeito do catálogo na janela do painel Áudio. Os controles saem do `kind` de cada
   parâmetro (número, inteiro, caixa de marcar, escolha), com a faixa, a unidade e a dica do servidor; os valores ficam num
   rascunho do pai, que só vai para a spec quando a pessoa aplica. O intervalo (início e fim) não aparece: é o da seleção.
   Nos efeitos de equalização o formulário mostra também o gráfico da resposta de frequência (e, nas listas do EQ Gráfico e do
   EQ por Curva, os controles deslizantes e os pontos arrastáveis), que se redesenha a cada mudança. */
import { computed } from 'vue'
import type { AudioEffectInfo, AudioEffectParam, AudioEffectSettings, AudioEffectValue, CurvePoint } from '@/api'
import AppCheckbox from '@/components/ui/AppCheckbox.vue'
import AppNumberInput from '@/components/ui/AppNumberInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import { choiceText, choiceValue, clampParam, isListParam, isParamShown } from '@/lib/audioEffects'
import EffectResponsePanel from './EffectResponsePanel.vue'
import EqParamControl from './EqParamControl.vue'

const props = defineProps<{ info: AudioEffectInfo }>()
const values = defineModel<Record<string, AudioEffectValue>>({ required: true })

/** Os parâmetros que o formulário mostra: a curva de pontos tem a ferramenta de envelope, e o campo de um modo de unidade
    só aparece no modo dele (`shown_when`). */
const fields = computed(() =>
  props.info.parameters.filter(
    (param) => param.kind !== 'points' && isParamShown(param, values.value, props.info.parameters),
  ),
)

function numberOf(param: AudioEffectParam): number | null {
  const value = values.value[param.name]
  return typeof value === 'number' ? value : null
}

function problem(param: AudioEffectParam): string | undefined {
  const value = numberOf(param)
  if (value === null || clampParam(param, value) === value) return undefined
  const { minimum, maximum } = param
  if (minimum !== null && maximum !== null) return `Use de ${minimum} a ${maximum}.`
  return minimum !== null ? `Use ${minimum} ou mais.` : `Use ${maximum} ou menos.`
}

function setNumber(param: AudioEffectParam, value: number | null): void {
  const next = { ...values.value }
  if (value === null) delete next[param.name]
  else next[param.name] = value
  values.value = next
}

function setDiscrete(param: AudioEffectParam, value: boolean | string | number): void {
  values.value = { ...values.value, [param.name]: value }
}

/** A escolha vira o tipo que a spec guarda: número se as opções são números (a inclinação em dB por oitava). */
const setChoice = (param: AudioEffectParam, text: string) => setDiscrete(param, choiceValue(param, text))

function listOf(param: AudioEffectParam): number[] | CurvePoint[] {
  const value = values.value[param.name]
  return Array.isArray(value) ? (value as number[] | CurvePoint[]) : ((param.default ?? []) as number[] | CurvePoint[])
}

function setList(param: AudioEffectParam, value: number[] | CurvePoint[]): void {
  values.value = { ...values.value, [param.name]: value }
}

/** O efeito como o rascunho o descreve: é o que o gráfico pede ao servidor. */
const draftEffect = computed<AudioEffectSettings>(() => ({ type: props.info.type, ...values.value }))

/** O gráfico simples (sem controle de curva próprio): os efeitos de equalização que não têm uma lista do EQ. */
const showPlainChart = computed(() => props.info.has_response === true && !props.info.parameters.some(isListParam))
</script>

<template>
  <div class="effect-form" data-audio-effect-form>
    <template v-for="param in fields" :key="param.name">
      <AppNumberInput
        v-if="param.kind === 'number' || param.kind === 'integer'"
        :label="param.label"
        :model-value="numberOf(param)"
        :min="param.minimum ?? undefined"
        :max="param.maximum ?? undefined"
        :step="param.kind === 'integer' ? 1 : 0.1"
        :unit="param.unit || undefined"
        :hint="param.hint || undefined"
        :error="problem(param)"
        :data-effect-param="param.name"
        @update:model-value="setNumber(param, $event)"
      />
      <AppSelect
        v-else-if="param.kind === 'choice'"
        :label="param.label"
        :model-value="choiceText(values[param.name])"
        :options="param.options.map((option) => ({ value: option, label: option }))"
        :hint="param.hint || undefined"
        :data-effect-param="param.name"
        @update:model-value="setChoice(param, $event)"
      />
      <div v-else-if="isListParam(param)" class="effect-form__wide" :data-effect-param="param.name">
        <EqParamControl
          :param="param"
          :effect="draftEffect"
          :name="info.label"
          :model-value="listOf(param)"
          @update:model-value="setList(param, $event)"
        />
      </div>
      <div v-else-if="param.kind === 'boolean'" class="effect-form__wide" :data-effect-param="param.name">
        <AppCheckbox
          :label="param.label"
          :model-value="values[param.name] === true"
          :hint="param.hint || undefined"
          @update:model-value="setDiscrete(param, $event)"
        />
      </div>
    </template>
    <EffectResponsePanel v-if="showPlainChart" class="effect-form__wide" :effect="draftEffect" :name="info.label" />
    <p v-if="fields.length === 0" class="effect-form__none">Este efeito não tem parâmetros.</p>
  </div>
</template>

<style scoped>
.effect-form {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
  gap: var(--space-3);
}

.effect-form__wide,
.effect-form__none {
  grid-column: 1 / -1;
}

.effect-form__none {
  margin: 0;
  color: var(--color-text-soft);
  font-size: var(--text-sm);
}
</style>
