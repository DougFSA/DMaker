<script setup lang="ts">
/* O editor de um projeto (/editor/:name). A tela só monta as peças: a barra de ações, a bancada com os encaixes do
   player, da linha do tempo, dos filtros e da mídia, e as abas do inspetor. Todo o estado mora no store do editor. */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import type { RenderResult } from '@/api'
import EditorInspector from '@/components/editor/EditorInspector.vue'
import EditorProjectPicker from '@/components/editor/EditorProjectPicker.vue'
import EditorToolbar from '@/components/editor/EditorToolbar.vue'
import EditorWorkbench from '@/components/editor/EditorWorkbench.vue'
import PageHeader from '@/components/layout/PageHeader.vue'
import FileBrowserDialog from '@/components/projects/FileBrowserDialog.vue'
import JobProgressCard from '@/components/projects/JobProgressCard.vue'
import ValidationCard from '@/components/projects/ValidationCard.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { provideEditorFilePicker } from '@/composables/useEditorFilePicker'
import { useConfirm } from '@/composables/useConfirm'
import { renderResultsFromJob } from '@/lib/outputs'
import { readStored, writeStored } from '@/lib/storage'
import { CLASSIC_UI_PATH } from '@/navigation'
import { useEditorStore } from '@/stores/editor'
import { useJobsStore } from '@/stores/jobs'

/** O projeto aberto no editor (`/editor/:name`); o menu lateral leva a `/editor`, sem nome, e mostra a lista de projetos. */
const props = defineProps<{ name?: string }>()

const TAB_KEY = 'dmaker.editor.tab'

const editor = useEditorStore()
const jobs = useJobsStore()
const confirm = useConfirm()
const picker = provideEditorFilePicker()

const tab = ref(readStored(TAB_KEY) || 'properties')
const projectJobs = computed(() => (editor.name ? jobs.forProject(editor.name).slice(0, 3) : []))
const subtitle = computed(() => (props.name ? `Projeto ${props.name}` : 'Escolha um projeto para editar.'))

/** A aba escolhida pela pessoa fica guardada; as trocas automáticas (spec inválida, render pronto) não. */
function chooseTab(next: string): void {
  tab.value = next
  writeStored(TAB_KEY, next)
}

// abrir (ou trocar) o projeto: o store cuida de carregar, e a spec inválida abre direto na aba JSON para consertar
watch(
  () => props.name,
  async (name) => {
    if (!name) return
    await editor.open(name)
    if (editor.name === name && editor.status === 'ready' && editor.specErrors.length > 0) tab.value = 'json'
  },
  { immediate: true },
)

/** Quem tem mudança não salva e vai embora confirma antes; descartar também descarta a edição guardada no store. */
async function confirmLeave(): Promise<boolean> {
  if (!editor.dirty) return true
  const leave = await confirm({
    title: 'Descartar as mudanças não salvas?',
    description: `O projeto ${editor.name} tem mudanças que ainda não foram salvas.`,
    confirmLabel: 'Descartar',
    tone: 'danger',
  })
  if (leave) editor.close()
  return leave
}

onBeforeRouteLeave(confirmLeave)
onBeforeRouteUpdate((to, from) => (to.params.name === from.params.name ? true : confirmLeave()))

function warnBeforeUnload(event: BeforeUnloadEvent): void {
  if (!editor.dirty) return
  event.preventDefault()
  event.returnValue = ''
}

// Ctrl+S salva o projeto; os demais atalhos do editor chegam com a linha do tempo
function onKeydown(event: KeyboardEvent): void {
  if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 's') return
  event.preventDefault()
  if (editor.status === 'ready') void editor.save()
}

// um render deste projeto terminou: as saídas se atualizam e, se saiu vídeo, a aba Preview abre nele
const stopListening = jobs.onJobEnd(async (job) => {
  if (!editor.name || job.project !== editor.name) return
  await editor.reloadDetails()
  if (job.status === 'done' && renderResultsFromJob(job.result).length > 0) tab.value = 'preview'
})

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('beforeunload', warnBeforeUnload)
})

onBeforeUnmount(() => {
  stopListening()
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('beforeunload', warnBeforeUnload)
})

function showRendered(_result: RenderResult): void {
  tab.value = 'preview'
}
</script>

<template>
  <div class="editor">
    <PageHeader title="Editor" :subtitle="subtitle">
      <AppButton v-if="name" to="/editor" variant="ghost">
        <AppIcon name="arrow-left" :size="18" />
        Outros projetos
      </AppButton>
      <AppButton v-if="name && editor.status === 'ready'" :to="{ name: 'project', params: { name } }">
        Página do projeto
      </AppButton>
    </PageHeader>

    <EditorProjectPicker v-if="!name" />

    <p v-else-if="editor.status === 'loading' || editor.status === 'idle'" class="status" role="status">
      Carregando projeto...
    </p>

    <AppCard v-else-if="editor.status === 'missing' || editor.status === 'failed'">
      <EmptyState
        icon="alert"
        :title="editor.status === 'missing' ? 'Projeto não encontrado' : 'Não foi possível abrir o projeto'"
        :description="editor.loadError"
      >
        <AppButton to="/editor" variant="primary">Escolher outro projeto</AppButton>
        <AppButton :href="`${CLASSIC_UI_PATH}#project=${encodeURIComponent(name)}`">Abrir na interface clássica</AppButton>
      </EmptyState>
    </AppCard>

    <div v-else :key="editor.name ?? ''" class="editor__stack">
      <EditorToolbar />

      <p v-if="editor.saveError" class="notice notice--error" role="alert">
        <AppIcon name="alert" :size="18" />
        <span>Não foi possível salvar: {{ editor.saveError }}</span>
      </p>
      <p v-if="editor.viewError" class="notice notice--warning" role="status">
        <AppIcon name="info" :size="18" />
        <span>A linha do tempo não foi atualizada com a última mudança: {{ editor.viewError }}</span>
      </p>

      <ValidationCard v-if="editor.validation" :summary="editor.validation" />
      <JobProgressCard v-for="job in projectJobs" :key="job.id" :job="job" @play="showRendered" />

      <EditorWorkbench />
      <EditorInspector :model-value="tab" @update:model-value="chooseTab" />
    </div>

    <FileBrowserDialog
      v-model:open="picker.open.value"
      mode="file"
      title="Escolher arquivo"
      @select="picker.onSelect"
    />
  </div>
</template>

<style scoped>
.status {
  padding: var(--space-6) 0;
  color: var(--color-text-soft);
}

.editor__stack {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.notice {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  overflow-wrap: anywhere;
}

.notice--error {
  background: var(--color-error-bg);
  color: var(--color-error);
}

.notice--warning {
  background: var(--color-warning-bg);
  color: var(--color-warning);
}
</style>
