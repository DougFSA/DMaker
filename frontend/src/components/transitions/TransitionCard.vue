<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, type TransitionCurve, type TransitionInfo } from '@/api'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { CURVE_LABELS } from '@/lib/transitions'

const props = defineProps<{ transition: TransitionInfo; curve: TransitionCurve }>()
defineEmits<{ copy: [transition: TransitionInfo] }>()

type SheetState = 'loading' | 'ready' | 'failed'
const state = ref<SheetState>('loading')
// o servidor gera a folha na primeira vez que alguém pede; `attempt` força o navegador a pedir de novo
const attempt = ref(0)

const sheetUrl = computed(() => {
  const url = api.transitions.sheetUrl(props.transition.name, props.curve)
  return attempt.value ? `${url}&tentativa=${attempt.value}` : url
})
const description = computed(
  () => `Quadros da transição ${props.transition.name} com a curva ${CURVE_LABELS[props.curve].toLowerCase()}`,
)

watch(
  () => props.curve,
  () => {
    state.value = 'loading'
  },
)

function retry(): void {
  attempt.value += 1
  state.value = 'loading'
}
</script>

<template>
  <article class="transition">
    <header class="transition__head">
      <h3 class="transition__name">{{ transition.name }}</h3>
      <AppBadge :tone="transition.kind === 'motion' ? 'accent' : 'neutral'">
        {{ transition.kind === 'motion' ? 'movimento' : 'xfade' }}
      </AppBadge>
    </header>
    <p class="transition__summary">{{ transition.summary }}</p>

    <div class="transition__sheet" :data-state="state">
      <a v-show="state !== 'failed'" :href="sheetUrl" target="_blank" rel="noopener" title="Abrir em tamanho original">
        <img
          :key="sheetUrl"
          :src="sheetUrl"
          :alt="description"
          loading="lazy"
          @load="state = 'ready'"
          @error="state = 'failed'"
        />
      </a>
      <p v-if="state === 'loading'" class="transition__status" role="status">Gerando a prévia...</p>
      <div v-if="state === 'failed'" class="transition__failed" role="alert">
        <AppIcon name="alert" :size="18" />
        <span>Não foi possível gerar a prévia.</span>
        <AppButton size="sm" @click="retry">Tentar de novo</AppButton>
      </div>
    </div>

    <footer class="transition__foot">
      <AppButton size="sm" @click="$emit('copy', transition)">Copiar trecho da spec</AppButton>
    </footer>
  </article>
</template>

<style scoped>
.transition {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  transition:
    border-color var(--transition),
    box-shadow var(--transition);
}

.transition:hover {
  border-color: var(--color-accent-soft);
  box-shadow: var(--glow-accent);
}

.transition__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.transition__name {
  font-family: ui-monospace, monospace;
  font-size: var(--text-base);
  font-weight: 600;
}

.transition__summary {
  min-height: 2.6em;
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.transition__sheet {
  position: relative;
  min-height: 4.5rem;
  overflow: hidden;
  border-radius: var(--radius-md);
  background: #202124;
}

.transition__sheet img {
  display: block;
  width: 100%;
  height: auto;
}

.transition__status {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  pointer-events: none;
}

.transition__sheet[data-state='ready'] .transition__status {
  display: none;
}

.transition__failed {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-error);
}

.transition__foot {
  display: flex;
  justify-content: flex-end;
}
</style>
