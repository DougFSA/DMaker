<script setup lang="ts">
/* Um efeito da cadeia: a alça de arrastar, o interruptor que liga e desliga (o bypass), o nome, subir, descer e
   remover, o formulário dos parâmetros que o catálogo descreve e o intervalo recolhível. Não grava nada sozinho no
   que é da cadeia (ligar, mover, remover): avisa a seção, que faz de cada ação um passo do desfazer. */
import { computed, ref } from 'vue'
import type { AudioEffectInfo, AudioEffectParam, AudioEffectSettings } from '@/api'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { intervalProblem, isEnabled } from '@/lib/audioEffects'
import { formatSeconds } from '@/lib/speech'
import AudioEffectField from './AudioEffectField.vue'

const props = defineProps<{
  effect: AudioEffectSettings
  /** A descrição do catálogo; nula quando o tipo não está nele (um efeito de uma versão mais nova): o cartão só liga, move e remove. */
  info: AudioEffectInfo | undefined
  /** O início e o fim do intervalo, como o catálogo os descreve (unidade e limite). */
  startParam: AudioEffectParam | undefined
  endParam: AudioEffectParam | undefined
  index: number
  count: number
  listPath: string
  dragging?: boolean
  dropTarget?: boolean
}>()

const emit = defineEmits<{
  toggle: [enabled: boolean]
  remove: []
  move: [delta: -1 | 1]
  dragStart: []
  dragEnd: []
  dragOver: [event: DragEvent]
  drop: [event: DragEvent]
}>()

const name = computed(() => props.info?.label ?? props.effect.type)
const enabled = computed(() => isEnabled(props.effect))
const hasInterval = computed(() => typeof props.effect.start === 'number' || typeof props.effect.end === 'number')

const intervalOpen = ref(hasInterval.value)

/** O resumo do intervalo no título recolhido ("1,5 s a 4,0 s", "a partir de 2,0 s", "até 3,0 s"). */
const intervalSummary = computed(() => {
  const { start, end } = props.effect
  const from = typeof start === 'number' ? `${formatSeconds(start)} s` : null
  const to = typeof end === 'number' ? `${formatSeconds(end)} s` : null
  if (from && to) return `${from} a ${to}`
  if (from) return `a partir de ${from}`
  return to ? `até ${to}` : 'item todo'
})

const checkStart = (value: number | null) => intervalProblem(value, props.effect.end)
const checkEnd = (value: number | null) => intervalProblem(props.effect.start, value)

function onDetailsToggle(event: Event): void {
  intervalOpen.value = (event.target as HTMLDetailsElement).open
}

function onDragStart(event: DragEvent): void {
  const card = (event.target as HTMLElement).closest<HTMLElement>('[data-effect-type]')
  if (event.dataTransfer) {
    // o Firefox só começa o arraste se houver algum dado; o cartão inteiro vira a imagem do que se arrasta
    event.dataTransfer.setData('text/plain', String(props.index))
    event.dataTransfer.effectAllowed = 'move'
    if (card && typeof event.dataTransfer.setDragImage === 'function') event.dataTransfer.setDragImage(card, 16, 16)
  }
  emit('dragStart')
}
</script>

<template>
  <li
    :class="['effect', { 'is-off': !enabled, 'is-dragging': dragging, 'is-drop-target': dropTarget }]"
    :data-effect-type="effect.type"
    :data-effect-index="index"
    :data-enabled="enabled ? 'true' : 'false'"
    @dragover="emit('dragOver', $event)"
    @drop="emit('drop', $event)"
  >
    <header class="effect__head">
      <span
        class="effect__grip"
        draggable="true"
        data-effect-grip
        title="Arraste para mudar a ordem do efeito na cadeia"
        @dragstart="onDragStart"
        @dragend="emit('dragEnd')"
      >
        <AppIcon name="grip" :size="16" />
      </span>
      <button
        type="button"
        role="switch"
        class="effect__switch"
        :aria-checked="enabled"
        :aria-label="`${enabled ? 'Desligar' : 'Ligar'} o efeito ${name}`"
        :title="enabled ? 'Ligado: clique para desligar sem apagar' : 'Desligado: o som passa sem este efeito'"
        data-effect-toggle
        @click="emit('toggle', !enabled)"
      >
        <span class="effect__knob" aria-hidden="true" />
      </button>
      <div class="effect__name" :title="info?.summary">
        <span class="effect__order">{{ index + 1 }}</span>
        <h5 class="effect__title">{{ name }}</h5>
        <span v-if="info && info.audacity_name !== info.label" class="effect__audacity">{{ info.audacity_name }}</span>
        <span v-if="!info" class="effect__audacity">fora do catálogo</span>
      </div>
      <div class="effect__actions">
        <AppButton
          variant="ghost"
          size="sm"
          icon-only
          :disabled="index === 0"
          :aria-label="`Subir o efeito ${name}`"
          title="Sobe na cadeia: passa a ser aplicado mais cedo"
          data-effect-move="up"
          @click="emit('move', -1)"
        >
          <AppIcon name="chevron-down" :size="16" class="effect__flip" />
        </AppButton>
        <AppButton
          variant="ghost"
          size="sm"
          icon-only
          :disabled="index >= count - 1"
          :aria-label="`Descer o efeito ${name}`"
          title="Desce na cadeia: passa a ser aplicado mais tarde"
          data-effect-move="down"
          @click="emit('move', 1)"
        >
          <AppIcon name="chevron-down" :size="16" />
        </AppButton>
        <AppButton
          variant="ghost"
          size="sm"
          icon-only
          :aria-label="`Remover o efeito ${name}`"
          title="Remover este efeito"
          data-effect-remove
          @click="emit('remove')"
        >
          <AppIcon name="x" :size="16" />
        </AppButton>
      </div>
    </header>

    <div v-if="info" class="effect__body">
      <div v-if="info.parameters.length > 0" class="effect__fields">
        <AudioEffectField
          v-for="param in info.parameters"
          :key="param.name"
          :param="param"
          :effect="effect"
          :list-path="listPath"
          :index="index"
        />
      </div>
      <p v-else class="effect__plain">Este efeito não tem parâmetros.</p>

      <details v-if="startParam && endParam" class="effect__interval" :open="intervalOpen" data-effect-interval @toggle="onDetailsToggle">
        <summary class="effect__interval-title">
          Intervalo <span class="effect__interval-summary">{{ intervalSummary }}</span>
        </summary>
        <div class="effect__fields">
          <AudioEffectField :param="startParam" :effect="effect" :list-path="listPath" :index="index" optional :check="checkStart" />
          <AudioEffectField :param="endParam" :effect="effect" :list-path="listPath" :index="index" optional :check="checkEnd" />
        </div>
        <p class="effect__interval-hint">
          Os segundos contam a partir do começo do item. Fora do intervalo o som passa intacto. Vazio vale o item todo.
        </p>
      </details>
    </div>
  </li>
</template>

<style scoped>
.effect {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-soft);
}

.effect.is-dragging {
  opacity: 0.45;
}

.effect.is-drop-target {
  outline: 2px dashed var(--color-accent);
  outline-offset: -3px;
}

/* desligado: o cartão fica apagado (o bypass não apaga os parâmetros), mas continua editável */
.effect.is-off .effect__body,
.effect.is-off .effect__name {
  opacity: 0.5;
}

.effect__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

.effect__grip {
  display: inline-grid;
  place-items: center;
  width: 1.5rem;
  height: 2rem;
  color: var(--color-text-muted);
  cursor: grab;
}

.effect__grip:active {
  cursor: grabbing;
}

.effect__switch {
  position: relative;
  flex: none;
  width: 2.25rem;
  height: 1.25rem;
  padding: 0;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-pill);
  background: var(--color-surface-raised);
  transition:
    background var(--transition),
    border-color var(--transition);
}

.effect__switch[aria-checked='true'] {
  border-color: var(--color-accent);
  background: var(--color-accent-bg);
}

.effect__knob {
  position: absolute;
  top: 50%;
  left: 2px;
  width: 0.9rem;
  height: 0.9rem;
  border-radius: 50%;
  background: var(--color-text-muted);
  transform: translateY(-50%);
  transition:
    left var(--transition),
    background var(--transition);
}

.effect__switch[aria-checked='true'] .effect__knob {
  left: calc(100% - 0.9rem - 2px);
  background: var(--color-accent);
}

.effect__switch:focus-visible {
  outline: 2px solid var(--color-focus);
  outline-offset: 2px;
}

.effect__name {
  display: flex;
  flex: 1;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--space-1) var(--space-2);
  min-width: 6rem;
}

.effect__order {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.effect__title {
  font-size: var(--text-sm);
  font-weight: 600;
}

.effect__audacity {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.effect__actions {
  display: flex;
  gap: var(--space-1);
}

.effect__flip {
  transform: rotate(180deg);
}

.effect__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.effect__fields {
  display: grid;
  /* o painel é estreito: duas colunas quando cabem, uma quando não */
  grid-template-columns: repeat(auto-fill, minmax(8rem, 1fr));
  gap: var(--space-3);
  align-items: start;
}

.effect__plain,
.effect__interval-hint {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.effect__interval-title {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--color-text-soft);
  cursor: pointer;
}

.effect__interval-summary {
  margin-left: var(--space-2);
  font-size: var(--text-xs);
  font-weight: 400;
  color: var(--color-text-muted);
}

/* o <details> não é contêiner flex em todo navegador: o espaço entre o título, os campos e a dica vem de margens */
.effect__interval[open] > .effect__interval-title {
  margin-bottom: var(--space-3);
}

.effect__interval-hint {
  margin-top: var(--space-3);
}
</style>
