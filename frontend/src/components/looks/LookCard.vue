<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, type LookInfo } from '@/api'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { effectChips } from '@/lib/looks'

const props = defineProps<{ look: LookInfo; brand?: string }>()
defineEmits<{ copy: [look: LookInfo] }>()

type SheetState = 'loading' | 'ready' | 'failed'
const state = ref<SheetState>('loading')
// o servidor gera a folha na primeira vez que alguém pede; `attempt` força o navegador a pedir de novo
const attempt = ref(0)

const sheetUrl = computed(() => {
  const url = api.looks.sheetUrl(props.look.name, props.brand)
  if (!attempt.value) return url
  return `${url}${url.includes('?') ? '&' : '?'}tentativa=${attempt.value}`
})
const chips = computed(() => effectChips(props.look))
const description = computed(() => `Cena de teste sem acabamento (esquerda) e com o look ${props.look.name} (direita)`)

watch(
  () => props.brand,
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
  <article class="look">
    <header class="look__head">
      <h3 class="look__name">{{ look.name }}</h3>
      <AppBadge :tone="look.source === 'marca' ? 'accent' : 'neutral'">{{ look.source }}</AppBadge>
    </header>
    <p class="look__summary">{{ look.summary || 'Look da marca, sem descrição.' }}</p>

    <ul v-if="chips.length" class="look__effects" aria-label="Efeitos de acabamento">
      <li v-for="chip in chips" :key="chip.name">{{ chip.label }} {{ chip.amount }}</li>
    </ul>
    <p v-else class="look__effects look__effects--none">Só ajuste de cor, sem efeitos de acabamento.</p>

    <div class="look__sheet" :data-state="state">
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
      <p v-if="state === 'loading'" class="look__status" role="status">Gerando a prévia...</p>
      <div v-if="state === 'failed'" class="look__failed" role="alert">
        <AppIcon name="alert" :size="18" />
        <span>Não foi possível gerar a prévia.</span>
        <AppButton size="sm" @click="retry">Tentar de novo</AppButton>
      </div>
    </div>

    <footer class="look__foot">
      <AppButton size="sm" @click="$emit('copy', look)">Copiar trecho da spec</AppButton>
    </footer>
  </article>
</template>

<style scoped>
.look {
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

.look:hover {
  border-color: var(--color-accent-soft);
  box-shadow: var(--glow-accent);
}

.look__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.look__name {
  font-family: ui-monospace, monospace;
  font-size: var(--text-base);
  font-weight: 600;
}

.look__summary {
  min-height: 2.6em;
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.look__effects {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: var(--text-xs);
  color: var(--color-text-soft);
}

.look__effects li {
  padding: 0.15rem var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-pill);
}

.look__effects--none {
  color: var(--color-text-muted);
}

.look__sheet {
  position: relative;
  min-height: 4.5rem;
  overflow: hidden;
  border-radius: var(--radius-md);
  background: #202124;
}

.look__sheet img {
  display: block;
  width: 100%;
  height: auto;
}

.look__status {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  pointer-events: none;
}

.look__sheet[data-state='ready'] .look__status {
  display: none;
}

.look__failed {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-error);
}

.look__foot {
  display: flex;
  justify-content: flex-end;
}
</style>
