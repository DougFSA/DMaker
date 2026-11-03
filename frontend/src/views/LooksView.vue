<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api, errorMessage, type LookCatalog, type LookInfo } from '@/api'
import PageHeader from '@/components/layout/PageHeader.vue'
import LookCard from '@/components/looks/LookCard.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import SearchField from '@/components/ui/SearchField.vue'
import SegmentedControl, { type SegmentOption } from '@/components/ui/SegmentedControl.vue'
import { filterLooks, specSnippet, type LookSourceFilter } from '@/lib/looks'
import { useCatalogStore } from '@/stores/catalog'
import { useToastsStore } from '@/stores/toasts'

const toasts = useToastsStore()
const brands = useCatalogStore()

const catalog = ref<LookCatalog | null>(null)
const loading = ref(true)
const failure = ref('')
const query = ref('')
const source = ref<LookSourceFilter>('all')
// 'default' = sem marca: só os looks padrão; com marca, os do brand.json entram (e valem no lugar dos de mesmo nome)
const brand = ref('default')

const sourceOptions: SegmentOption<LookSourceFilter>[] = [
  { value: 'all', label: 'Todos' },
  { value: 'padrão', label: 'Padrão' },
  { value: 'marca', label: 'Da marca' },
]
const visible = computed(() => filterLooks(catalog.value?.looks ?? [], query.value, source.value))
const overviewUrl = computed(() => api.looks.overviewUrl(brand.value))

async function load(): Promise<void> {
  failure.value = ''
  loading.value = true
  try {
    catalog.value = await api.looks.catalog(brand.value)
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    loading.value = false
  }
}

async function copySnippet(look: LookInfo): Promise<void> {
  const snippet = specSnippet(look.name)
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
  source.value = 'all'
}

watch(brand, load)
onMounted(() => {
  void load()
  // a lista de marcas só alimenta o seletor: se faltar, a galeria continua com os looks padrão
  void brands.load().catch(() => undefined)
})
</script>

<template>
  <div>
    <PageHeader
      title="Looks"
      subtitle="Acabamentos visuais prontos, por nome. Cada prévia mostra a mesma cena de teste sem acabamento e com o look."
    />

    <div class="toolbar">
      <SearchField id="look-search" v-model="query" label="Buscar looks" placeholder="Buscar por nome ou descrição" />
      <SegmentedControl v-model="source" :options="sourceOptions" label="Origem do look" />
      <div v-if="brands.brands.length > 1" class="toolbar__brand">
        <label for="look-brand">Marca</label>
        <select id="look-brand" v-model="brand" class="input">
          <option value="default">Nenhuma (só os padrão)</option>
          <option v-for="item in brands.brands.filter((b) => b.key !== 'default')" :key="item.key" :value="item.key">
            {{ item.name }}
          </option>
        </select>
      </div>
    </div>
    <p class="hint">
      No projeto inteiro: <code>"look": "cinema"</code>. Um trecho com <code>look</code> próprio vence o do projeto,
      <code>"look": "nenhum"</code> desliga, e um trecho com <code>color</code> próprio mantém a cor dele.
    </p>

    <p v-if="loading" class="status" role="status">Carregando looks...</p>

    <AppCard v-else-if="failure">
      <EmptyState icon="alert" title="Não foi possível carregar os looks" :description="failure">
        <AppButton variant="primary" @click="load">Tentar de novo</AppButton>
      </EmptyState>
    </AppCard>

    <template v-else>
      <AppCard class="overview">
        <h2 class="overview__title">Todos lado a lado</h2>
        <a :href="overviewUrl" target="_blank" rel="noopener" title="Abrir em tamanho original">
          <img
            :key="overviewUrl"
            :src="overviewUrl"
            alt="A cena de teste sem acabamento e com cada look, da esquerda para a direita"
            loading="lazy"
          />
        </a>
      </AppCard>

      <AppCard v-if="visible.length === 0">
        <EmptyState
          icon="search"
          title="Nada encontrado"
          description="Nenhum look combina com a busca e a origem escolhidas."
        >
          <AppButton @click="clearFilters">Limpar filtros</AppButton>
        </EmptyState>
      </AppCard>

      <ul v-else class="grid">
        <li v-for="look in visible" :key="`${brand}-${look.name}`">
          <LookCard :look="look" :brand="brand" @copy="copySnippet" />
        </li>
      </ul>
    </template>
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

.toolbar__brand {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-text-soft);
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

.overview {
  margin-bottom: var(--space-5);
}

.overview__title {
  margin-bottom: var(--space-3);
  font-size: var(--text-base);
  font-weight: 600;
}

.overview img {
  display: block;
  width: 100%;
  height: auto;
  border-radius: var(--radius-md);
  background: #202124;
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
