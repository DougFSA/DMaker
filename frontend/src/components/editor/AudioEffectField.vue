<script setup lang="ts">
/* Um parâmetro de um efeito de áudio, desenhado pelo que o catálogo diz dele (número, inteiro, caixa de marcar ou
   escolha). O número digitado espera 300 ms de silêncio e vale um passo do desfazer por campo; a caixa e a escolha
   gravam na hora, cada uma num passo. Número fora da faixa do catálogo é limitado antes de ir para a spec. As listas do EQ
   (os 31 controles do EQ Gráfico e os pontos do EQ por Curva) têm o controle próprio com o gráfico, e gravam ao soltar. */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { AudioEffectParam, AudioEffectSettings, CarrierValue, CurvePoint } from '@/api'
import AppCheckbox from '@/components/ui/AppCheckbox.vue'
import AppNumberInput from '@/components/ui/AppNumberInput.vue'
import AppSelect from '@/components/ui/AppSelect.vue'
import {
  AUTO_PROFILE,
  choiceText,
  choiceValue,
  clampParam,
  GENERATED_CARRIER,
  carrierTrackOptions,
  effectPath,
  hostTrackOf,
  isCarrier,
  isListParam,
  isParamShown,
  paramValue,
  profileNames,
  setEffectFieldIn,
} from '@/lib/audioEffects'
import { isDuckTrack } from '@/lib/autoDuck'
import { useAudioEffectsStore } from '@/stores/audioEffects'
import { useEditorStore } from '@/stores/editor'
import CarrierControl from './audio/CarrierControl.vue'
import EqParamControl from './audio/EqParamControl.vue'
import PluginControls from './audio/PluginControls.vue'

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
  /** Os parâmetros do mesmo efeito: o padrão de quem a condição `shown_when` cita e a spec não guarda. */
  siblings?: readonly AudioEffectParam[]
}>()

const editor = useEditorStore()
const catalog = useAudioEffectsStore()

/** O campo de um modo de unidade só aparece no modo dele: sem `shown_when` aparece sempre. */
const shown = computed(() => isParamShown(props.param, props.effect, props.siblings))

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

function onDiscrete(value: boolean | string | number | number[] | CurvePoint[] | CarrierValue): void {
  commit()
  editor.flushPendingEdits()
  const { listPath, index } = props
  editor.mutate((draft) => setEffectFieldIn(draft, listPath, index, props.param.name, value))
}

/** A escolha vira o tipo que a spec guarda: número se as opções são números (a inclinação em dB por oitava). */
const onChoice = (text: string) => onDiscrete(choiceValue(props.param, text))

/** A lista do EQ como a spec a tem (ou o padrão do catálogo), e o nome do efeito para os rótulos do gráfico. */
const listValue = computed(() => (paramValue(props.effect, props.param) ?? []) as number[] | CurvePoint[])
const effectName = computed(() => catalog.infoOf(props.effect.type)?.label ?? props.effect.type)

/** As opções do perfil de ruído: o automático e os que o projeto guarda; o que a spec cita sem existir fica marcado. */
const profileOptions = computed(() => {
  const names = profileNames(editor.spec)
  const options = [
    { value: AUTO_PROFILE, label: 'Automático (o trecho mais quieto do item)' },
    ...names.map((profile) => ({ value: profile, label: profile })),
  ]
  const current = typeof stored.value === 'string' ? stored.value : AUTO_PROFILE
  if (!options.some((option) => option.value === current)) options.push({ value: current, label: `${current} (não existe)` })
  return options
})

/** As opções da portadora: o som gerado e as trilhas que o par aceita e o projeto tem. Nulo no PiP e no master. */
const carrierTrackChoices = computed(() => {
  const present = (editor.view?.tracks ?? []).map((track) => track.id).filter(isDuckTrack)
  return carrierTrackOptions(hostTrackOf(props.listPath), present, typeof stored.value === 'string' ? stored.value : undefined)
})

/** Escolher o som gerado apaga a chave: a spec de antes de existir a escolha segue igual. Um passo do desfazer, como os outros. */
function onCarrierTrack(value: string): void {
  commit()
  editor.flushPendingEdits()
  const { listPath, index } = props
  editor.mutate((draft) =>
    setEffectFieldIn(draft, listPath, index, props.param.name, value === GENERATED_CARRIER ? undefined : value),
  )
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
  <!-- o campo de outro modo de unidade fica de fora da tela (a spec o guarda) -->
  <template v-if="!shown" />
  <!-- o efeito Plugin: o formato vem do plugin escolhido (não aparece), o nome dele com o aviso, e um campo por controle que ele declara -->
  <template v-else-if="param.kind === 'plugin_format'" />
  <div v-else-if="param.kind === 'plugin'" class="list-cell" :data-effect-param="param.name">
    <PluginControls part="name" :effect="effect" :list-path="listPath" :index="index" />
  </div>
  <PluginControls v-else-if="param.kind === 'plugin_params'" part="controls" :effect="effect" :list-path="listPath" :index="index" />
  <AppNumberInput
    v-else-if="param.kind === 'number' || param.kind === 'integer'"
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
    :model-value="choiceText(stored)"
    :options="param.options.map((option) => ({ value: option, label: option }))"
    :hint="param.hint || undefined"
    :data-effect-param="param.name"
    @update:model-value="onChoice"
  />
  <!-- o perfil de ruído: o automático ou um dos que o projeto guarda; um nome que a spec cita e não existe aparece marcado -->
  <AppSelect
    v-else-if="param.kind === 'profile'"
    class="profile-cell"
    :label="param.label"
    :model-value="typeof stored === 'string' ? stored : AUTO_PROFILE"
    :options="profileOptions"
    :hint="param.hint || undefined"
    :data-effect-param="param.name"
    @update:model-value="onDiscrete"
  />
  <!-- a trilha de onde a portadora vem: o som gerado ou uma trilha do projeto; no PiP e no master a escolha não existe -->
  <template v-else-if="param.kind === 'carrier_track'">
    <AppSelect
      v-if="carrierTrackChoices"
      :label="param.label"
      :model-value="typeof stored === 'string' ? stored : GENERATED_CARRIER"
      :options="carrierTrackChoices"
      :hint="param.hint || undefined"
      :data-effect-param="param.name"
      @update:model-value="onCarrierTrack"
    />
  </template>
  <!-- a portadora do Vocoder: a onda e a frequência do Tom, na linha inteira -->
  <div v-else-if="param.kind === 'carrier'" class="list-cell" :data-effect-param="param.name">
    <CarrierControl
      v-if="isCarrier(stored)"
      :model-value="stored"
      :label="param.label"
      :hint="param.hint || undefined"
      @commit="onDiscrete"
    />
  </div>
  <!-- as listas do EQ ocupam a linha inteira: 31 controles e um gráfico não cabem numa coluna de número -->
  <div v-else-if="isListParam(param)" class="list-cell" :data-effect-param="param.name">
    <EqParamControl :param="param" :effect="effect" :name="effectName" :model-value="listValue" @commit="onDiscrete" />
  </div>
  <!-- a caixa de marcar ocupa a linha inteira da grade: o rótulo e a dica são longos para a coluna do número -->
  <div v-else-if="param.kind === 'boolean'" class="check-cell" :data-effect-param="param.name">
    <AppCheckbox
      :label="param.label"
      :model-value="stored === true"
      :hint="param.hint || undefined"
      @update:model-value="onDiscrete"
    />
  </div>
</template>

<style scoped>
.check-cell,
.list-cell {
  grid-column: 1 / -1;
}
</style>
