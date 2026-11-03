<script setup lang="ts">
/* O painel Avançado, recolhido: o contexto, a temperatura e a semente do modelo, e o que está carregado na memória agora,
   com o botão de descarregar. O que o motor não tem (contexto, o que está carregado) fica escondido. As opções valem a
   partir da mensagem seguinte e são gravadas um instante depois da última tecla. */
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import type { AgentEngine, AgentLoadedModel, AgentModel, AgentOptions } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import AppNumberInput from '@/components/ui/AppNumberInput.vue'
import {
  CONTEXT_WARNING,
  contextMax,
  contextProblem,
  expiryTime,
  loadedLabel,
  MAX_TEMPERATURE,
  MIN_CONTEXT,
  optionsFrom,
  sameOptions,
  seedProblem,
  temperatureProblem,
  valuesOf,
  type OptionValues,
} from '@/lib/agentAdvanced'

const props = defineProps<{
  /** Só o Ollama tem contexto ajustável e modelos que se carregam e descarregam. */
  engine: AgentEngine | null
  /** O modelo escolhido: dele vem o contexto máximo. */
  model: AgentModel | undefined
  options: AgentOptions
  /** O agente está respondendo: as opções só mudam entre uma resposta e outra. */
  disabled: boolean
  /** O que está carregado agora; `null` enquanto a leitura não veio. */
  loaded: AgentLoadedModel[] | null
  /** O modelo que está sendo descarregado agora. */
  unloading: string | null
  unloadError: string
}>()

const emit = defineEmits<{
  'update:options': [options: AgentOptions]
  unload: [name: string]
  /** O painel foi aberto: quem usa atualiza o que está carregado. */
  open: []
}>()

const COMMIT_DELAY_MS = 600
const values = reactive<OptionValues>(valuesOf(props.options))
const isOllama = computed(() => props.engine === 'ollama')
const max = computed(() => contextMax(props.model))
const errors = computed(() => ({
  num_ctx: contextProblem(values.num_ctx, props.model),
  temperature: temperatureProblem(values.temperature),
  seed: seedProblem(values.seed),
}))
const valid = computed(() => !errors.value.num_ctx && !errors.value.temperature && !errors.value.seed)
const contextHint = computed(
  () => `De ${MIN_CONTEXT} até ${max.value ? max.value.toLocaleString('pt-BR') : 'o máximo do modelo'} tokens. Vazio usa o padrão.`,
)
const busyHint = computed(() => (props.disabled ? 'Espere a resposta terminar para mudar.' : undefined))

let timer: ReturnType<typeof setTimeout> | undefined

// o servidor pode ter ajustado as opções (outra conversa aberta, valor recusado): o painel mostra o que vale,
// menos enquanto a pessoa ainda digita, para a resposta de uma gravação anterior não apagar o que ela escreve agora
watch(
  () => props.options,
  (next) => {
    if (timer === undefined) Object.assign(values, valuesOf(next))
  },
  { deep: true },
)

function commit(): void {
  timer = undefined
  if (!valid.value) return
  const next = optionsFrom(values)
  if (!sameOptions(next, props.options)) emit('update:options', next)
}

function change(key: keyof OptionValues, value: number | null): void {
  values[key] = value
  clearTimeout(timer)
  timer = setTimeout(commit, COMMIT_DELAY_MS)
}

onBeforeUnmount(() => clearTimeout(timer))

const opened = ref(false)
function onToggle(event: Event): void {
  const now = (event.target as HTMLDetailsElement).open
  if (now && !opened.value) emit('open')
  opened.value = now
}
</script>

<template>
  <details class="advanced" @toggle="onToggle">
    <summary>Avançado</summary>
    <div class="advanced__body">
      <div class="advanced__fields">
        <AppNumberInput
          v-if="isOllama"
          label="Contexto (tokens)"
          :model-value="values.num_ctx"
          :min="MIN_CONTEXT"
          :max="max ?? undefined"
          :step="1024"
          placeholder="Padrão"
          :hint="busyHint ?? contextHint"
          :error="errors.num_ctx"
          :disabled="disabled"
          @update:model-value="change('num_ctx', $event)"
        />
        <AppNumberInput
          label="Temperatura"
          :model-value="values.temperature"
          :min="0"
          :max="MAX_TEMPERATURE"
          :step="0.1"
          placeholder="Padrão"
          :hint="busyHint ?? `De 0 a ${MAX_TEMPERATURE}. Mais baixa responde mais igual; mais alta, mais variada.`"
          :error="errors.temperature"
          :disabled="disabled"
          @update:model-value="change('temperature', $event)"
        />
        <AppNumberInput
          label="Semente"
          :model-value="values.seed"
          :step="1"
          placeholder="Aleatória"
          :hint="busyHint ?? 'Com a mesma semente a resposta se repete.'"
          :error="errors.seed"
          :disabled="disabled"
          @update:model-value="change('seed', $event)"
        />
      </div>

      <p v-if="isOllama" class="advanced__warn" data-notice="context">{{ CONTEXT_WARNING }}</p>

      <section v-if="isOllama" class="advanced__loaded" aria-label="Modelo carregado agora">
        <h3 class="advanced__title">Modelo carregado agora</h3>
        <p v-if="loaded === null" class="advanced__empty">Lendo o que está na memória...</p>
        <p v-else-if="!loaded.length" class="advanced__empty">Nenhum modelo está carregado na memória.</p>
        <ul v-else class="advanced__models">
          <li v-for="model in loaded" :key="model.name" class="advanced__model">
            <span class="advanced__model-text">
              <span>{{ loadedLabel(model) }}</span>
              <span v-if="expiryTime(model.expires_at)" class="advanced__until">Sai da memória sozinho às {{ expiryTime(model.expires_at) }}.</span>
            </span>
            <AppButton size="sm" variant="secondary" :loading="unloading === model.name" :disabled="!!unloading" @click="emit('unload', model.name)">
              Descarregar
            </AppButton>
          </li>
        </ul>
        <p v-if="unloadError" class="advanced__error" role="alert">{{ unloadError }}</p>
      </section>
    </div>
  </details>
</template>

<style scoped>
.advanced {
  color: var(--color-text-soft);
  font-size: var(--text-sm);
}

.advanced summary {
  width: fit-content;
  cursor: pointer;
}

.advanced__body {
  display: grid;
  gap: var(--space-3);
  margin-top: var(--space-3);
}

.advanced__fields {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
  gap: var(--space-3);
}

.advanced__warn {
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  background: var(--color-warning-bg);
  color: var(--color-warning);
  line-height: 1.5;
}

.advanced__title {
  margin-bottom: var(--space-2);
  color: var(--color-text);
  font-size: var(--text-sm);
  font-weight: 600;
}

.advanced__models {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.advanced__model {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2) var(--space-3);
}

.advanced__model-text {
  display: grid;
  min-width: 0;
  overflow-wrap: anywhere;
}

.advanced__until {
  color: var(--color-text-muted);
  font-size: var(--text-xs);
}

.advanced__error {
  margin-top: var(--space-2);
  color: var(--color-error);
}
</style>
