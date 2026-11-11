<script setup lang="ts">
/* Os dois parâmetros de lista do EQ: os 31 controles deslizantes do EQ Gráfico (`band_gains`) e os pontos arrastáveis do
   EQ por Curva (`freq_points`), cada um com o gráfico da resposta, que o servidor recalcula a cada mudança (a mesma conta
   do render). A lista que se mexe fica num rascunho aqui dentro: `update:modelValue` avisa a cada passo (a janela de efeito
   usa, para refazer a prévia) e `commit` entrega a lista final ao soltar (o cartão grava aí, um passo do desfazer). */
import { computed, ref, watch } from 'vue'
import type { AudioEffectParam, AudioEffectSettings, CurvePoint } from '@/api'
import { useEffectResponse } from '@/composables/useEffectResponse'
import BandSliders from './BandSliders.vue'
import EqResponseChart from './EqResponseChart.vue'

type ListValue = number[] | CurvePoint[]

const props = defineProps<{
  param: AudioEffectParam
  /** O efeito inteiro (o tipo e os outros parâmetros, que também mudam a curva). */
  effect: AudioEffectSettings
  modelValue: ListValue
  /** O nome do efeito, para os rótulos de leitor de tela. */
  name: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: ListValue]
  commit: [value: ListValue]
}>()

/** A faixa de dB dos pontos arrastáveis: trava o desenho enquanto se arrasta (a curva de um ponto a -40 dB ainda aparece). */
const POINTS_RANGE = { min: -48, max: 24 }

const draft = ref<ListValue>(clone(props.modelValue))
let gesture = false

function clone(value: ListValue): ListValue {
  return (value as unknown[]).map((item) => (typeof item === 'object' && item ? { ...(item as object) } : item)) as ListValue
}

// o que a spec diz vale quando a pessoa não está no meio de um gesto (desfazer, trocar de projeto, predefinição)
watch(
  () => props.modelValue,
  (value) => {
    if (!gesture) draft.value = clone(value)
  },
  { deep: true },
)

const chartEffect = computed<AudioEffectSettings>(() => ({ ...props.effect, [props.param.name]: draft.value }))
const { curve, error } = useEffectResponse(chartEffect)

const isBands = computed(() => props.param.kind === 'band_gains')

function update(value: ListValue): void {
  gesture = true
  draft.value = value
  emit('update:modelValue', value)
}

function commit(): void {
  gesture = false
  emit('commit', clone(draft.value))
}
</script>

<template>
  <div class="eq-control" :data-eq-control="param.kind">
    <BandSliders
      v-if="isBands"
      :model-value="draft as number[]"
      :labels="param.options"
      :minimum="param.minimum ?? -20"
      :maximum="param.maximum ?? 20"
      :name="name"
      @update:model-value="update"
      @commit="commit"
    />
    <EqResponseChart
      :curve="curve"
      :points="isBands ? undefined : (draft as CurvePoint[])"
      :range="isBands ? undefined : POINTS_RANGE"
      :label="`Resposta de frequência de ${name}`"
      @update:points="update"
      @commit="commit"
    />
    <p v-if="error" class="eq-control__error" role="status" data-eq-error>Não foi possível desenhar a resposta: {{ error }}</p>
  </div>
</template>

<style scoped>
.eq-control {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.eq-control__error {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-warning);
}
</style>
