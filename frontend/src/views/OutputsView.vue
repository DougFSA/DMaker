<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, errorMessage, type OutputFile } from '@/api'
import PageHeader from '@/components/layout/PageHeader.vue'
import OutputCard from '@/components/outputs/OutputCard.vue'
import VideoPlayerDialog, { type PlayableVideo } from '@/components/outputs/VideoPlayerDialog.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import SearchField from '@/components/ui/SearchField.vue'
import SegmentedControl, { type SegmentOption } from '@/components/ui/SegmentedControl.vue'
import { filterOutputs, playableFromOutput, type OutputKindFilter } from '@/lib/outputs'
import { useJobsStore } from '@/stores/jobs'

const jobs = useJobsStore()

const outputs = ref<OutputFile[]>([])
const loading = ref(true)
const failure = ref('')
const query = ref('')
const kind = ref<OutputKindFilter>('all')
const playing = ref<PlayableVideo | null>(null)
const playerOpen = ref(false)

const visible = computed(() => filterOutputs(outputs.value, query.value, kind.value))

const kindOptions: SegmentOption<OutputKindFilter>[] = [
  { value: 'all', label: 'Todas' },
  { value: 'final', label: 'Finais' },
  { value: 'preview', label: 'Prévias' },
]

async function load(): Promise<void> {
  failure.value = ''
  try {
    outputs.value = await api.outputs.list()
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    loading.value = false
  }
}

function play(output: OutputFile): void {
  playing.value = playableFromOutput(output)
  playerOpen.value = playing.value !== null
}

function clearFilters(): void {
  query.value = ''
  kind.value = 'all'
}

// um render que termina com esta tela aberta já aparece na lista
const stopListening = jobs.onJobEnd(() => void load())
onMounted(load)
onBeforeUnmount(stopListening)
</script>

<template>
  <div>
    <PageHeader title="Saídas" subtitle="Os vídeos que o DMaker já gerou. Assista aqui ou baixe o arquivo.">
      <AppButton @click="load">Atualizar</AppButton>
    </PageHeader>

    <div class="toolbar">
      <SearchField
        id="output-search"
        v-model="query"
        label="Buscar saídas"
        placeholder="Buscar por nome, projeto ou formato"
      />
      <SegmentedControl v-model="kind" :options="kindOptions" label="Tipo de saída" />
    </div>

    <p v-if="loading" class="status" role="status">Carregando saídas...</p>

    <AppCard v-else-if="failure">
      <EmptyState icon="alert" title="Não foi possível carregar as saídas" :description="failure">
        <AppButton variant="primary" @click="load">Tentar de novo</AppButton>
      </EmptyState>
    </AppCard>

    <AppCard v-else-if="outputs.length === 0">
      <EmptyState
        icon="video"
        title="Nenhum vídeo gerado ainda"
        description="Renderize uma prévia ou a versão final de um projeto e ela aparece aqui."
      >
        <AppButton to="/projetos" variant="primary">Ir para Projetos</AppButton>
      </EmptyState>
    </AppCard>

    <AppCard v-else-if="visible.length === 0">
      <EmptyState
        icon="search"
        title="Nada encontrado"
        description="Nenhuma saída combina com a busca e o filtro escolhidos."
      >
        <AppButton @click="clearFilters">Limpar filtros</AppButton>
      </EmptyState>
    </AppCard>

    <ul v-else class="grid">
      <li v-for="output in visible" :key="output.path">
        <OutputCard :output="output" @play="play" />
      </li>
    </ul>

    <VideoPlayerDialog v-model:open="playerOpen" :video="playing" />
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-5);
}

.status {
  padding: var(--space-6) 0;
  color: var(--color-text-soft);
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
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
