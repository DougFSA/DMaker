<script setup lang="ts">
/* Lote: vários vídeos de uma vez, um por linha de uma planilha, sobre um modelo de projeto. A pessoa escolhe o
   modelo e a planilha, vê a validação (nada é renderizado nessa etapa), inicia e acompanha vídeo por vídeo, com
   pausa e retomada, até o relatório final. O servidor guarda o estado de cada linha, então fechar a tela não
   perde nada: o lote aparece de novo em "Lotes salvos". */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  api,
  errorMessage,
  type BatchListItem,
  type BatchReport,
  type BatchRow,
  type BatchValidation,
} from '@/api'
import BatchProgressCard from '@/components/batches/BatchProgressCard.vue'
import BatchValidationCard from '@/components/batches/BatchValidationCard.vue'
import PageHeader from '@/components/layout/PageHeader.vue'
import type { PlayableVideo } from '@/components/outputs/VideoPlayerDialog.vue'
import VideoPlayerDialog from '@/components/outputs/VideoPlayerDialog.vue'
import FileBrowserDialog from '@/components/projects/FileBrowserDialog.vue'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import AppTable from '@/components/ui/AppTable.vue'
import { defaultBatchName, outputUrl, startPlan, statusTone } from '@/lib/batches'
import { baseName } from '@/lib/format'
import { useCatalogStore } from '@/stores/catalog'
import { useJobsStore } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'

const POLL_MS = 1000

const catalog = useCatalogStore()
const jobs = useJobsStore()
const toasts = useToastsStore()

const templateName = ref('')
const sheet = ref('')
const nameColumn = ref('')
const batchName = ref('')
const batchNameTouched = ref(false)
const preview = ref(false)
const browsing = ref(false)

const validation = ref<BatchValidation | null>(null)
const validating = ref(false)
const starting = ref(false)
const failure = ref('')

const current = ref<BatchReport | null>(null)
/** O job que está rodando o lote aberto; vem do pedido de início/retomada ou da consulta do lote. */
const activeJobId = ref<string | null>(null)
const saved = ref<BatchListItem[]>([])
const busy = ref(false)
const pausing = ref(false)
const playing = ref<PlayableVideo | null>(null)
const playerOpen = ref(false)

let pollTimer: ReturnType<typeof setInterval> | null = null
let stopWatchingJobs: (() => void) | null = null

const selectedTemplate = computed(() => catalog.templates.find((item) => item.name === templateName.value))
const plan = computed(() => (validation.value ? startPlan(validation.value) : null))
const liveJob = computed(() => (activeJobId.value ? jobs.jobs[activeJobId.value] : undefined))
// a etapa já traz o percentual do comando em andamento ("montagem final 36%"): o do job é o do lote inteiro
const liveLabel = computed(() => liveJob.value?.progress?.label ?? '')

// o que foi validado deixa de valer quando a pessoa muda o modelo, a planilha ou a coluna do nome
watch([templateName, sheet, nameColumn], () => {
  validation.value = null
})

// o nome do lote acompanha o arquivo da planilha (digitado ou escolhido) até a pessoa escrever o dela
watch(sheet, (path) => {
  if (!batchNameTouched.value) batchName.value = path.trim() ? defaultBatchName(path) : ''
})

function onSheetPicked(paths: string[]): void {
  sheet.value = paths[0] ?? ''
}

async function validate(): Promise<void> {
  failure.value = ''
  if (!templateName.value) {
    failure.value = 'Escolha o modelo do lote.'
    return
  }
  if (!sheet.value.trim()) {
    failure.value = 'Escolha a planilha (CSV, XLSX ou JSON).'
    return
  }
  validating.value = true
  try {
    validation.value = await api.batches.validate({
      template: templateName.value,
      sheet: sheet.value.trim(),
      name_column: nameColumn.value.trim() || null,
    })
  } catch (error) {
    validation.value = null
    failure.value = errorMessage(error)
  } finally {
    validating.value = false
  }
}

async function loadSaved(): Promise<void> {
  try {
    saved.value = (await api.batches.list()).batches
  } catch {
    // a lista é um extra da tela: sem ela o resto continua funcionando
  }
}

function stopPolling(): void {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
}

async function refreshCurrent(): Promise<void> {
  const name = current.value?.name
  if (!name) return
  try {
    const report = await api.batches.get(name)
    if (current.value?.name !== name) return
    current.value = report
    // logo depois de iniciar, o job ainda não pegou a trava do lote: só para de olhar quando o job também acabou
    if (report.status !== 'running' && liveJob.value?.status !== 'running') {
      stopPolling()
      pausing.value = false
      void loadSaved()
    }
  } catch (error) {
    stopPolling()
    failure.value = errorMessage(error)
  }
}

/** Passa a mostrar um lote e, se ele está rodando, a acompanhá-lo (o arquivo do lote a cada segundo e o job pelo SSE). */
function attach(report: BatchReport, jobId?: string): void {
  current.value = report
  activeJobId.value = jobId ?? report.job_id ?? null
  if (activeJobId.value) jobs.track(activeJobId.value, { description: `Lote ${report.name}` })
  stopPolling()
  if (report.status === 'running' || jobId) {
    pollTimer = setInterval(() => void refreshCurrent(), POLL_MS)
  }
}

async function openBatch(name: string, jobId?: string): Promise<void> {
  failure.value = ''
  try {
    attach(await api.batches.get(name), jobId)
  } catch (error) {
    failure.value = errorMessage(error)
  }
}

async function start(skipInvalid: boolean): Promise<void> {
  failure.value = ''
  starting.value = true
  try {
    const started = await api.batches.start({
      template: templateName.value,
      sheet: sheet.value.trim(),
      name_column: nameColumn.value.trim() || null,
      name: batchName.value.trim() || null,
      skip_invalid: skipInvalid,
      preview: preview.value,
    })
    validation.value = null
    await openBatch(started.name, started.job_id)
    void loadSaved()
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    starting.value = false
  }
}

async function pause(): Promise<void> {
  if (!current.value) return
  busy.value = true
  try {
    await api.batches.pause(current.value.name)
    pausing.value = true
    toasts.push({
      tone: 'info',
      title: 'Pausa pedida',
      description: 'O lote para quando o vídeo em andamento terminar. O que já saiu não é refeito.',
    })
  } catch (error) {
    toasts.push({ tone: 'error', title: 'Não foi possível pausar', description: errorMessage(error) })
  } finally {
    busy.value = false
  }
}

async function resume(rows?: number[], force = false): Promise<void> {
  if (!current.value) return
  busy.value = true
  try {
    const { name, job_id: jobId } = await api.batches.resume(current.value.name, { rows, force })
    await openBatch(name, jobId)
  } catch (error) {
    toasts.push({ tone: 'error', title: 'Não foi possível retomar', description: errorMessage(error) })
  } finally {
    busy.value = false
  }
}

function redo(row: BatchRow): void {
  void resume([row.index], true)
}

function play(row: BatchRow): void {
  if (!row.output) return
  playing.value = { url: outputUrl(row.output), name: baseName(row.output), subtitle: row.title }
  playerOpen.value = true
}

onMounted(async () => {
  try {
    await catalog.load()
  } catch (error) {
    failure.value = errorMessage(error)
  }
  templateName.value ||= catalog.templates[0]?.name ?? ''
  await loadSaved()
  // um lote que continua rodando (a tela foi fechada e reaberta) volta a ser acompanhado
  const running = saved.value.find((item) => item.status === 'running')
  if (running) await openBatch(running.name)
  // o fim do job traz o relatório final na hora, sem esperar o próximo segundo
  stopWatchingJobs = jobs.onJobEnd((job) => {
    if (job.id === activeJobId.value) void refreshCurrent()
  })
})

onBeforeUnmount(() => {
  stopPolling()
  stopWatchingJobs?.()
})
</script>

<template>
  <div>
    <PageHeader
      title="Lote"
      subtitle="Vários vídeos de uma vez: uma planilha, um vídeo por linha, sobre um modelo de projeto."
    />

    <AppCard title="Planilha e modelo" subtitle="As colunas casam com os campos do modelo (titulo, imagem, narracao...).">
      <form id="batch-form" class="form" @submit.prevent="validate">
        <div class="form__grid">
          <div class="field">
            <label for="batch-template">Modelo</label>
            <select id="batch-template" v-model="templateName" class="input">
              <option v-for="item in catalog.templates" :key="item.name" :value="item.name">{{ item.name }}</option>
            </select>
            <p v-if="selectedTemplate" class="field-hint">
              {{ selectedTemplate.description }}
              Campos:
              {{ Object.keys(selectedTemplate.params).join(', ') }}.
            </p>
          </div>

          <div class="field">
            <label for="batch-sheet">Planilha</label>
            <div class="picker">
              <input
                id="batch-sheet"
                v-model="sheet"
                class="input"
                type="text"
                autocomplete="off"
                placeholder="Caminho do .csv, .xlsx ou .json"
              />
              <AppButton @click="browsing = true">
                <AppIcon name="folder" :size="18" />
                Escolher
              </AppButton>
            </div>
            <p class="field-hint">Imagens e arquivos com caminho relativo partem da pasta da planilha.</p>
          </div>

          <div class="field">
            <label for="batch-name-column">Coluna do nome do arquivo</label>
            <input
              id="batch-name-column"
              v-model="nameColumn"
              class="input"
              type="text"
              list="batch-columns"
              autocomplete="off"
              placeholder="Automática (nome, titulo...)"
            />
            <datalist id="batch-columns">
              <option v-for="header in validation?.headers ?? []" :key="header" :value="header" />
            </datalist>
            <p class="field-hint">
              Cada vídeo sai como output/&lt;lote&gt;/&lt;texto da coluna&gt;.mp4.
              <template v-if="validation?.name_column">Usando a coluna {{ validation.name_column }}.</template>
            </p>
          </div>

          <div class="field">
            <label for="batch-name">Nome do lote</label>
            <input
              id="batch-name"
              v-model="batchName"
              class="input"
              type="text"
              autocomplete="off"
              placeholder="Pelo nome da planilha"
              @input="batchNameTouched = true"
            />
            <p class="field-hint">Vira a pasta em output/ e o começo do nome de cada projeto.</p>
          </div>
        </div>

        <label class="check"><input v-model="preview" type="checkbox" /> Só prévias rápidas, em baixa resolução</label>
        <p v-if="failure" class="form__error" role="alert">{{ failure }}</p>
      </form>
      <template #footer>
        <AppButton variant="primary" type="submit" form="batch-form" :loading="validating">
          Validar planilha
        </AppButton>
      </template>
    </AppCard>

    <div v-if="validation" class="stack">
      <BatchValidationCard :validation="validation" />

      <AppCard v-if="plan === 'all'" title="Tudo certo">
        <p class="decision">
          Todas as {{ validation.total }} linhas passaram na validação. O lote cria um projeto por linha e renderiza
          os vídeos um depois do outro.
        </p>
        <template #footer>
          <AppButton variant="primary" :loading="starting" @click="start(false)">
            Iniciar lote ({{ validation.valid }} {{ validation.valid === 1 ? 'vídeo' : 'vídeos' }})
          </AppButton>
        </template>
      </AppCard>

      <AppCard v-else-if="plan === 'skip-invalid'" title="Há linhas com problema">
        <p class="decision" role="alert">
          {{ validation.invalid }}
          {{ validation.invalid === 1 ? 'linha tem problema e não será renderizada' : 'linhas têm problema e não serão renderizadas' }}.
          Quer seguir só com as {{ validation.valid }} que passaram? As outras ficam registradas como puladas, com o motivo,
          e você pode corrigir a planilha e criar o lote de novo.
        </p>
        <template #footer>
          <AppButton :loading="validating" @click="validate">Corrigi a planilha, validar de novo</AppButton>
          <AppButton variant="primary" :loading="starting" @click="start(true)">
            Seguir sem as linhas com problema ({{ validation.valid }})
          </AppButton>
        </template>
      </AppCard>

      <AppCard v-else title="Nada para renderizar">
        <p class="decision" role="alert">
          Nenhuma linha pode ser renderizada como está. Corrija a planilha (ou escolha outro modelo) e valide de novo.
        </p>
        <template #footer>
          <AppButton :loading="validating" @click="validate">Validar de novo</AppButton>
        </template>
      </AppCard>
    </div>

    <BatchProgressCard
      v-if="current"
      class="stack"
      :report="current"
      :live-label="liveLabel"
      :busy="busy"
      :pausing="pausing"
      @pause="pause"
      @resume="resume()"
      @redo="redo"
      @play="play"
    />

    <AppCard v-if="saved.length" class="stack" title="Lotes salvos" subtitle="O estado de cada vídeo fica guardado: abra um lote para retomar ou refazer só um vídeo." flush>
      <AppTable caption="Lotes salvos">
        <thead>
          <tr>
            <th scope="col">Lote</th>
            <th scope="col">Modelo</th>
            <th scope="col">Estado</th>
            <th scope="col">Andamento</th>
            <th scope="col"><span class="visually-hidden">Ações</span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in saved" :key="item.name">
            <td class="cell-name">{{ item.name }}</td>
            <td>{{ item.template }}</td>
            <td><AppBadge :tone="statusTone(item.status)" dot>{{ item.status_label }}</AppBadge></td>
            <td>{{ item.summary }}</td>
            <td>
              <AppButton size="sm" @click="openBatch(item.name)">Abrir</AppButton>
            </td>
          </tr>
        </tbody>
      </AppTable>
    </AppCard>

    <FileBrowserDialog
      v-model:open="browsing"
      mode="file"
      kind="sheet"
      title="Escolher a planilha"
      @select="onSheetPicked"
    />
    <VideoPlayerDialog v-model:open="playerOpen" :video="playing" />
  </div>
</template>

<style scoped>
.stack {
  margin-top: var(--space-5);
}

.form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.form__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(19rem, 1fr));
  gap: var(--space-4);
}

.picker {
  display: flex;
  gap: var(--space-2);
  min-width: 0;
}

.picker .input {
  min-width: 0;
}

.form__error {
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-sm);
  background: var(--color-error-bg);
  color: var(--color-error);
  font-size: var(--text-sm);
  white-space: pre-line;
}

.decision {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.cell-name {
  font-weight: 600;
}
</style>
