<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { api, errorMessage, type ProjectListItem } from '@/api'
import PageHeader from '@/components/layout/PageHeader.vue'
import AutoCutDialog from '@/components/projects/AutoCutDialog.vue'
import NewProjectDialog from '@/components/projects/NewProjectDialog.vue'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import AppTable from '@/components/ui/AppTable.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import SearchField from '@/components/ui/SearchField.vue'
import SegmentedControl, { type SegmentOption } from '@/components/ui/SegmentedControl.vue'
import { formatRelative, formatTimestamp } from '@/lib/format'
import { filterProjects } from '@/lib/projects'
import { readStored, writeStored } from '@/lib/storage'
import { useJobsStore } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'
import { useWorkspaceStore } from '@/stores/workspace'

type Layout = 'cards' | 'table'

const LAYOUT_KEY = 'dmaker.projectsLayout'

const router = useRouter()
const jobs = useJobsStore()
const toasts = useToastsStore()
const workspace = useWorkspaceStore()

const projects = ref<ProjectListItem[]>([])
const loading = ref(true)
const failure = ref('')
const query = ref('')
const layout = ref<Layout>(readStored(LAYOUT_KEY) === 'table' ? 'table' : 'cards')
const layoutOptions: SegmentOption<Layout>[] = [
  { value: 'cards', label: 'Cartões', icon: 'grid' },
  { value: 'table', label: 'Tabela', icon: 'list' },
]
watch(layout, (next) => writeStored(LAYOUT_KEY, next))
const creating = ref(false)
const cutting = ref(false)
let mounted = true

// mais recentes primeiro; a cópia evita ordenar a lista original dentro de um computed
const visible = computed(() =>
  [...filterProjects(projects.value, query.value)].sort((a, b) => (b.mtime ?? 0) - (a.mtime ?? 0)),
)

async function load(): Promise<void> {
  loading.value = true
  failure.value = ''
  try {
    projects.value = await api.projects.list()
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    loading.value = false
  }
}

function open(project: ProjectListItem): void {
  workspace.openProject(project.name)
  void router.push({ name: 'project', params: { name: project.name } })
}

function onCreated(name: string): void {
  toasts.push({ tone: 'success', title: 'Projeto criado', description: name })
  workspace.openProject(name)
  void router.push({ name: 'project', params: { name } })
}

function openProject(name: string): void {
  workspace.openProject(name)
  void router.push({ name: 'project', params: { name } })
}

/** O corte roda em segundo plano (a transcrição leva minutos): acompanha pelo job e abre o projeto ao fim.
 * O aviso de job concluído ou com erro já vem do `useJobNotifications`, em qualquer tela. */
function onCutStarted({ jobId, name }: { jobId: string; name: string }): void {
  jobs.track(jobId, { project: name, description: `Cortar pausas e vícios: ${name}` })
  toasts.push({
    tone: 'info',
    title: 'Corte iniciado',
    description: 'A transcrição leva alguns minutos. O andamento aparece na barra superior.',
  })
  const stop = jobs.onJobEnd((job) => {
    if (job.id !== jobId) return
    stop()
    if (job.status === 'done' && mounted) openProject(name)
  })
}

onMounted(load)
onBeforeUnmount(() => {
  mounted = false
})
</script>

<template>
  <div>
    <PageHeader title="Projetos" subtitle="Seus vídeos em andamento. Abra um projeto para validar, conferir a qualidade e renderizar.">
      <AppButton @click="cutting = true">
        <AppIcon name="sparkles" :size="18" />
        Cortar gravação
      </AppButton>
      <AppButton variant="primary" @click="creating = true">
        <AppIcon name="plus" :size="18" />
        Novo projeto
      </AppButton>
    </PageHeader>

    <div class="toolbar">
      <SearchField
        id="project-search"
        v-model="query"
        label="Buscar projetos"
        placeholder="Buscar por nome, formato ou marca"
      />
      <SegmentedControl v-model="layout" :options="layoutOptions" label="Forma de exibição" />
    </div>

    <p v-if="loading" class="status" role="status">Carregando projetos...</p>

    <AppCard v-else-if="failure">
      <EmptyState icon="alert" title="Não foi possível carregar os projetos" :description="failure">
        <AppButton variant="primary" @click="load">Tentar de novo</AppButton>
      </EmptyState>
    </AppCard>

    <AppCard v-else-if="projects.length === 0">
      <EmptyState
        icon="folder"
        title="Nenhum projeto ainda"
        description="Crie o primeiro a partir de um modelo pronto ou escolhendo seus vídeos."
      >
        <AppButton variant="primary" @click="creating = true">Novo projeto</AppButton>
      </EmptyState>
    </AppCard>

    <AppCard v-else-if="visible.length === 0">
      <EmptyState icon="search" title="Nada encontrado" :description="`Nenhum projeto combina com “${query}”.`">
        <AppButton @click="query = ''">Limpar busca</AppButton>
      </EmptyState>
    </AppCard>

    <ul v-else-if="layout === 'cards'" class="grid">
      <li v-for="project in visible" :key="project.name">
        <RouterLink
          :to="{ name: 'project', params: { name: project.name } }"
          class="project"
          @click="workspace.openProject(project.name)"
        >
          <AppCard interactive>
            <div class="project__top">
              <span class="project__icon"><AppIcon name="film" /></span>
              <AppBadge v-if="project.error" tone="error">{{ project.error }}</AppBadge>
              <AppBadge v-else-if="project.preset" tone="accent">{{ project.preset }}</AppBadge>
            </div>
            <h2 class="project__name">{{ project.name }}</h2>
            <dl class="project__meta">
              <div>
                <dt>Marca</dt>
                <dd>{{ project.brand || 'sem marca' }}</dd>
              </div>
              <div>
                <dt>Trechos</dt>
                <dd>{{ project.segments ?? '-' }}</dd>
              </div>
              <div>
                <dt>Alterado</dt>
                <dd :title="project.mtime ? formatTimestamp(project.mtime) : undefined">
                  {{ project.mtime ? formatRelative(project.mtime) : '-' }}
                </dd>
              </div>
            </dl>
          </AppCard>
        </RouterLink>
      </li>
    </ul>

    <AppCard v-else flush>
      <AppTable caption="Lista de projetos">
        <thead>
          <tr>
            <th scope="col">Projeto</th>
            <th scope="col">Formato</th>
            <th scope="col">Marca</th>
            <th scope="col" class="cell-num">Trechos</th>
            <th scope="col">Alterado</th>
            <th scope="col"><span class="visually-hidden">Ações</span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="project in visible" :key="project.name" class="is-clickable" @click="open(project)">
            <td class="cell-name">{{ project.name }}</td>
            <td>
              <AppBadge v-if="project.error" tone="error">{{ project.error }}</AppBadge>
              <AppBadge v-else-if="project.preset" tone="accent">{{ project.preset }}</AppBadge>
            </td>
            <td>{{ project.brand || 'sem marca' }}</td>
            <td class="cell-num">{{ project.segments ?? '-' }}</td>
            <td>{{ project.mtime ? formatRelative(project.mtime) : '-' }}</td>
            <td>
              <AppButton size="sm" :to="{ name: 'project', params: { name: project.name } }" @click.stop>
                Abrir
              </AppButton>
            </td>
          </tr>
        </tbody>
      </AppTable>
    </AppCard>

    <NewProjectDialog v-model:open="creating" @created="onCreated" />
    <AutoCutDialog v-model:open="cutting" @started="onCutStarted" />
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
  grid-template-columns: repeat(auto-fill, minmax(17rem, 1fr));
  gap: var(--space-4);
  margin: 0;
  padding: 0;
  list-style: none;
}

.project {
  display: flex;
  width: 100%;
  height: 100%;
  border-radius: var(--radius-lg);
  color: inherit;
  text-decoration: none;
}

.project:hover {
  text-decoration: none;
}

.project > :deep(.card) {
  flex: 1;
}

.project__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.project__icon {
  display: grid;
  place-items: center;
  width: 2.5rem;
  height: 2.5rem;
  border-radius: var(--radius-sm);
  background: var(--color-accent-bg);
  color: var(--color-accent-text);
}

.project__name {
  font-size: var(--text-lg);
  overflow-wrap: anywhere;
}

.project__meta {
  display: grid;
  grid-template-columns: repeat(3, auto);
  justify-content: space-between;
  gap: var(--space-3);
  margin: var(--space-4) 0 0;
}

.project__meta dt {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.project__meta dd {
  margin: 0;
  font-size: var(--text-sm);
  font-weight: 500;
}

.cell-name {
  font-weight: 600;
}
</style>
