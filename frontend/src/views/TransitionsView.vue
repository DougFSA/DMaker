<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage, type TransitionCatalog, type TransitionCurve, type TransitionInfo } from '@/api'
import PageHeader from '@/components/layout/PageHeader.vue'
import TransitionCard from '@/components/transitions/TransitionCard.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import SearchField from '@/components/ui/SearchField.vue'
import SegmentedControl, { type SegmentOption } from '@/components/ui/SegmentedControl.vue'
import { CURVE_HINTS, CURVE_LABELS, filterTransitions, specSnippet, type TransitionKindFilter } from '@/lib/transitions'
import { useToastsStore } from '@/stores/toasts'

const toasts = useToastsStore()

const catalog = ref<TransitionCatalog | null>(null)
const loading = ref(true)
const failure = ref('')
const query = ref('')
const kind = ref<TransitionKindFilter>('all')
const curve = ref<TransitionCurve>('linear')

const kindOptions: SegmentOption<TransitionKindFilter>[] = [
  { value: 'all', label: 'Todas' },
  { value: 'motion', label: 'Movimento' },
  { value: 'xfade', label: 'xfade' },
]
const curveOptions = computed<SegmentOption<TransitionCurve>[]>(() =>
  (catalog.value?.curves ?? []).map((value) => ({ value, label: CURVE_LABELS[value] })),
)
const visible = computed(() => filterTransitions(catalog.value?.transitions ?? [], query.value, kind.value))

async function load(): Promise<void> {
  failure.value = ''
  loading.value = true
  try {
    catalog.value = await api.transitions.catalog()
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    loading.value = false
  }
}

async function copySnippet(transition: TransitionInfo): Promise<void> {
  const snippet = specSnippet(transition.name, curve.value)
  try {
    await navigator.clipboard.writeText(snippet)
    toasts.push({ tone: 'success', title: 'Trecho copiado', description: snippet })
  } catch {
    // sem permissão de área de transferência: mostra o texto para a pessoa copiar na mão
    toasts.push({ tone: 'info', title: 'Copie o trecho abaixo', description: snippet })
  }
}

function clearFilters(): void {
  query.value = ''
  kind.value = 'all'
}

onMounted(load)
</script>

<template>
  <div>
    <PageHeader
      title="Transições"
      subtitle="Como um trecho entra a partir do anterior. Cada prévia mostra os quadros da troca entre dois clipes de teste."
    />

    <div class="toolbar">
      <SearchField
        id="transition-search"
        v-model="query"
        label="Buscar transições"
        placeholder="Buscar por nome ou descrição"
      />
      <SegmentedControl v-model="kind" :options="kindOptions" label="Tipo de transição" />
      <SegmentedControl v-if="curveOptions.length" v-model="curve" :options="curveOptions" label="Curva de tempo" />
    </div>
    <p class="hint">
      {{ CURVE_HINTS[curve] }} Vale para qualquer transição: <code>"curve": "{{ curve }}"</code>.
    </p>

    <p v-if="loading" class="status" role="status">Carregando transições...</p>

    <AppCard v-else-if="failure">
      <EmptyState icon="alert" title="Não foi possível carregar as transições" :description="failure">
        <AppButton variant="primary" @click="load">Tentar de novo</AppButton>
      </EmptyState>
    </AppCard>

    <AppCard v-else-if="visible.length === 0">
      <EmptyState
        icon="search"
        title="Nada encontrado"
        description="Nenhuma transição combina com a busca e o filtro escolhidos."
      >
        <AppButton @click="clearFilters">Limpar filtros</AppButton>
      </EmptyState>
    </AppCard>

    <ul v-else class="grid">
      <li v-for="transition in visible" :key="transition.name">
        <TransitionCard :transition="transition" :curve="curve" @copy="copySnippet" />
      </li>
    </ul>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.hint {
  margin-bottom: var(--space-5);
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.hint code {
  font-family: ui-monospace, monospace;
}

.status {
  padding: var(--space-6) 0;
  color: var(--color-text-soft);
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 30rem), 1fr));
  gap: var(--space-4);
  margin: 0;
  padding: 0;
  list-style: none;
}

.grid > li {
  display: flex;
}

.grid > li > * {
  flex: 1;
}
</style>
