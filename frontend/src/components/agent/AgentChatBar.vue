<script setup lang="ts">
/* A barra da conversa: o modo (escolhido na conversa nova, travado depois da primeira mensagem), o modelo com o
   tamanho e os selos do que ele faz, o esforço do raciocínio e o aviso de memória. O slot `advanced` recebe as
   opções avançadas (contexto, temperatura, semente e descarregar o modelo). */
import { computed } from 'vue'
import type { AgentMemory, AgentMode, AgentModel } from '@/api'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppSelect, { type SelectOption } from '@/components/ui/AppSelect.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import {
  cannotOperate,
  capabilityLabels,
  defaultEffortLabel,
  memoryNotice,
  MODE_HINTS,
  MODE_LABELS,
  modelOptionLabel,
  toolsNotice,
} from '@/lib/agentModels'

const props = defineProps<{
  mode: AgentMode
  /** Depois da primeira mensagem o modo não muda mais. */
  modeLocked: boolean
  /** Os modelos instalados; vazio quando o servidor do modelo não respondeu. */
  models: AgentModel[]
  memory: AgentMemory | null
  modelName: string
  /** O modelo escolhido na lista, quando ele está nela. */
  selected: AgentModel | undefined
  effort: string | null
  /** O agente está respondendo: o modelo da conversa não pode mudar no meio da resposta. */
  busy: boolean
}>()

const emit = defineEmits<{
  'update:mode': [mode: AgentMode]
  'update:model': [name: string]
  'update:effort': [value: string | null]
}>()

const modeOptions = [
  { value: 'operate', label: MODE_LABELS.operate },
  { value: 'free', label: MODE_LABELS.free },
] satisfies { value: AgentMode; label: string }[]

const modelOptions = computed<SelectOption[]>(() => {
  // quem opera o DMaker precisa de ferramentas: o modelo sem elas aparece avisado e não se escolhe (na Conversa livre, sim)
  const listed = props.models.map((model) => ({
    value: model.name,
    label: modelOptionLabel(model, props.mode),
    disabled: cannotOperate(model, props.mode),
  }))
  // o modelo da conversa que não está na lista (desinstalado) continua aparecendo, para a tela não mentir
  return props.selected || !props.modelName
    ? listed
    : [{ value: props.modelName, label: `${props.modelName}${props.models.length ? ' · não instalado' : ''}` }, ...listed]
})

const levels = computed(() => props.selected?.effort_levels ?? [])
const effortOptions = computed<SelectOption[]>(() => levels.value.map((level) => ({ value: level.value, label: level.label })))
const badges = computed(() => capabilityLabels(props.selected?.capabilities ?? []))
const notice = computed(() => memoryNotice(props.selected, props.memory))
const toolsProblem = computed(() => toolsNotice(props.selected, props.mode))
</script>

<template>
  <div class="bar">
    <div class="bar__top">
      <SegmentedControl
        v-if="!modeLocked"
        label="Modo da conversa"
        :options="modeOptions"
        :model-value="mode"
        @update:model-value="emit('update:mode', $event)"
      />
      <p v-else class="bar__locked">
        <AppBadge tone="accent">{{ MODE_LABELS[mode] }}</AppBadge>
        <span class="bar__locked-note">O modo não muda depois da primeira mensagem.</span>
      </p>
      <p class="bar__hint">{{ MODE_HINTS[mode] }}</p>
      <ul v-if="badges.length" class="bar__badges" aria-label="O que este modelo faz">
        <li v-for="label in badges" :key="label"><AppBadge tone="info">{{ label }}</AppBadge></li>
      </ul>
    </div>

    <div class="bar__choices">
      <AppSelect
        class="bar__select"
        label="Modelo"
        :options="modelOptions"
        :model-value="modelName"
        :disabled="busy || !modelOptions.length"
        :hint="busy ? 'O modelo só muda entre uma resposta e outra.' : undefined"
        @update:model-value="emit('update:model', $event)"
      />
      <AppSelect
        v-if="levels.length"
        class="bar__select"
        label="Esforço do raciocínio"
        :options="effortOptions"
        :placeholder="defaultEffortLabel(selected)"
        :model-value="effort ?? ''"
        @update:model-value="emit('update:effort', $event || null)"
      />
    </div>

    <p v-if="toolsProblem" class="bar__memory" data-tone="error" data-notice="tools" role="alert">{{ toolsProblem }}</p>
    <p v-if="notice" class="bar__memory" :data-tone="notice.tone" role="status">{{ notice.text }}</p>

    <slot name="advanced" />
  </div>
</template>

<style scoped>
.bar {
  display: grid;
  flex: none;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-surface);
}

.bar__top {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2) var(--space-4);
}

.bar__locked {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  color: var(--color-text-muted);
  font-size: var(--text-xs);
}

.bar__hint {
  flex: 1 1 14rem;
  color: var(--color-text-soft);
  font-size: var(--text-sm);
}

.bar__choices {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
  gap: var(--space-3);
}

.bar__select {
  min-width: 0;
}

.bar__badges {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.bar__memory {
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  line-height: 1.5;
}

.bar__memory[data-tone='warning'] {
  background: var(--color-warning-bg);
  color: var(--color-warning);
}

.bar__memory[data-tone='error'] {
  background: var(--color-error-bg);
  color: var(--color-error);
}

/* tela estreita: a barra perde as frases de apoio para os seletores caberem sem empurrar a conversa para baixo */
@container agent (max-width: 520px) {
  .bar {
    padding: var(--space-3);
  }

  .bar__hint,
  .bar__locked-note {
    display: none;
  }
}
</style>
