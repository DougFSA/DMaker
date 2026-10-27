<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  api,
  ApiError,
  errorMessage,
  type ProjectDetail,
  type QaReport,
  type RenderResult,
  type ValidationSummary,
} from '@/api'
import PageHeader from '@/components/layout/PageHeader.vue'
import OutputCard from '@/components/outputs/OutputCard.vue'
import VideoPlayerDialog, { type PlayableVideo } from '@/components/outputs/VideoPlayerDialog.vue'
import JobProgressCard from '@/components/projects/JobProgressCard.vue'
import QaReportCard from '@/components/projects/QaReportCard.vue'
import RenderDialog, { type RenderChoice } from '@/components/projects/RenderDialog.vue'
import ValidationCard from '@/components/projects/ValidationCard.vue'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { CLASSIC_UI_PATH } from '@/navigation'
import { playableFromOutput, playableFromRender } from '@/lib/outputs'
import { useJobsStore } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'
import { useWorkspaceStore } from '@/stores/workspace'

const props = defineProps<{ name: string }>()

const jobs = useJobsStore()
const toasts = useToastsStore()
const workspace = useWorkspaceStore()

const detail = ref<ProjectDetail | null>(null)
const loading = ref(true)
const loadError = ref<{ title: string; message: string } | null>(null)

const summary = ref<ValidationSummary | null>(null)
const report = ref<QaReport | null>(null)
const busy = ref<'validate' | 'qa' | null>(null)

const renderOpen = ref(false)
const starting = ref(false)
const playing = ref<PlayableVideo | null>(null)
const playerOpen = ref(false)

// os três jobs mais recentes deste projeto: o que está rodando e o que acabou de terminar
const projectJobs = computed(() => jobs.forProject(props.name).slice(0, 3))
const segmentsInSpec = computed(() => detail.value?.spec.timeline?.length ?? 0)

async function load(): Promise<void> {
  loading.value = true
  loadError.value = null
  detail.value = null
  summary.value = null
  report.value = null
  try {
    detail.value = await api.projects.get(props.name)
    workspace.openProject(props.name)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      loadError.value = { title: 'Projeto não encontrado', message: `Não existe um projeto chamado “${props.name}”.` }
    } else if (error instanceof ApiError && error.status === 422) {
      loadError.value = {
        title: 'A spec deste projeto não passa na validação',
        message: `${error.message}\n\nCorrija na interface clássica ou direto no arquivo spec.json.`,
      }
    } else {
      loadError.value = { title: 'Não foi possível abrir o projeto', message: errorMessage(error) }
    }
  } finally {
    loading.value = false
  }
}

async function reloadOutputs(): Promise<void> {
  try {
    detail.value = await api.projects.get(props.name)
  } catch {
    // a lista de saídas fica como estava; o próximo render tenta de novo
  }
}

async function validate(): Promise<void> {
  busy.value = 'validate'
  try {
    summary.value = await api.projects.validate(props.name)
  } catch (error) {
    toasts.push({ tone: 'error', title: 'A validação falhou', description: errorMessage(error) })
  } finally {
    busy.value = null
  }
}

async function runQa(): Promise<void> {
  busy.value = 'qa'
  try {
    report.value = await api.projects.qa(props.name)
  } catch (error) {
    toasts.push({ tone: 'error', title: 'A conferência de qualidade falhou', description: errorMessage(error) })
  } finally {
    busy.value = null
  }
}

async function startRender(choice: RenderChoice): Promise<void> {
  starting.value = true
  try {
    let jobId: string
    let description: string
    if (choice.kind === 'export') {
      jobId = (await api.projects.export(props.name, choice.presets)).job_id
      description = `${props.name}: export ${choice.presets.join(', ')}`
    } else if (choice.kind === 'preview') {
      jobId = (await api.projects.render(props.name, { preview: true, segments: choice.segments })).job_id
      description = `${props.name}: preview`
    } else {
      jobId = (await api.projects.render(props.name, { preview: false })).job_id
      description = `${props.name}: render final`
    }
    jobs.track(jobId, { project: props.name, description })
    renderOpen.value = false
    toasts.push({ tone: 'info', title: 'Render iniciado', description: 'Acompanhe o andamento aqui ou na barra superior.' })
  } catch (error) {
    toasts.push({ tone: 'error', title: 'Não foi possível iniciar o render', description: errorMessage(error) })
  } finally {
    starting.value = false
  }
}

function play(output: ProjectDetail['outputs'][number]): void {
  playing.value = playableFromOutput(output)
  playerOpen.value = playing.value !== null
}

function playResult(result: RenderResult): void {
  playing.value = playableFromRender(result)
  playerOpen.value = playing.value !== null
}

// terminou um job deste projeto: a lista de saídas se atualiza sozinha
const stopListening = jobs.onJobEnd((job) => {
  if (job.project === props.name) void reloadOutputs()
})
onBeforeUnmount(stopListening)

watch(() => props.name, load, { immediate: true })
</script>

<template>
  <div>
    <p v-if="loading" class="status" role="status">Carregando projeto...</p>

    <AppCard v-else-if="loadError">
      <EmptyState icon="alert" :title="loadError.title" :description="loadError.message">
        <AppButton to="/projetos" variant="primary">Voltar para Projetos</AppButton>
        <AppButton :href="CLASSIC_UI_PATH">Abrir a interface clássica</AppButton>
      </EmptyState>
    </AppCard>

    <template v-else-if="detail">
      <PageHeader :title="detail.name" :subtitle="`${detail.spec.output?.preset ?? 'sem formato'} · ${detail.spec.brand || 'sem marca'} · ${segmentsInSpec} ${segmentsInSpec === 1 ? 'trecho' : 'trechos'}`">
        <AppButton to="/projetos" variant="ghost">
          <AppIcon name="arrow-left" :size="18" />
          Projetos
        </AppButton>
        <AppButton :loading="busy === 'validate'" :disabled="busy === 'qa'" @click="validate">
          <AppIcon name="check" :size="18" />
          Validar
        </AppButton>
        <AppButton :loading="busy === 'qa'" :disabled="busy === 'validate'" @click="runQa">
          <AppIcon name="sparkles" :size="18" />
          Conferir qualidade
        </AppButton>
        <AppButton :href="`${CLASSIC_UI_PATH}#project=${encodeURIComponent(detail.name)}`">
          <AppIcon name="external" :size="18" />
          Editar na clássica
        </AppButton>
        <AppButton variant="primary" @click="renderOpen = true">
          <AppIcon name="play" :size="18" />
          Renderizar
        </AppButton>
      </PageHeader>

      <div class="stack">
        <JobProgressCard v-for="job in projectJobs" :key="job.id" :job="job" @play="playResult" />

        <ValidationCard v-if="summary" :summary="summary" />
        <QaReportCard v-if="report" :report="report" />

        <AppCard
          title="Saídas deste projeto"
          :subtitle="detail.outputs.length ? `${detail.outputs.length} ${detail.outputs.length === 1 ? 'arquivo gerado' : 'arquivos gerados'}` : undefined"
        >
          <template #actions>
            <AppBadge v-if="!detail.captions_exists" tone="neutral">sem legendas automáticas</AppBadge>
          </template>
          <EmptyState
            v-if="detail.outputs.length === 0"
            icon="video"
            title="Nenhum vídeo gerado ainda"
            description="Valide o projeto, confira a qualidade e gere uma prévia."
          >
            <AppButton variant="primary" @click="renderOpen = true">Renderizar</AppButton>
          </EmptyState>
          <ul v-else class="outputs">
            <li v-for="output in detail.outputs" :key="output.path">
              <OutputCard :output="output" hide-project @play="play" />
            </li>
          </ul>
        </AppCard>
      </div>

      <RenderDialog v-model:open="renderOpen" :project-name="detail.name" :busy="starting" @submit="startRender" />
      <VideoPlayerDialog v-model:open="playerOpen" :video="playing" />
    </template>
  </div>
</template>

<style scoped>
.status {
  padding: var(--space-6) 0;
  color: var(--color-text-soft);
}

.stack {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.outputs {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
  gap: var(--space-4);
  margin: 0;
  padding: 0;
  list-style: none;
}

.outputs > li {
  display: flex;
}

.outputs > li > * {
  flex: 1;
}
</style>
