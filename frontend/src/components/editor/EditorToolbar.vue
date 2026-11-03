<script setup lang="ts">
/* A barra do editor: salvar, desfazer e refazer, validar e os renders (prévia, final e exportar). Validar e renderizar
   salvam antes, porque o servidor lê a spec do disco. "Só os trechos" fica no diálogo da prévia. */
import { ref } from 'vue'
import { api, errorMessage } from '@/api'
import RenderDialog, { type RenderChoice } from '@/components/projects/RenderDialog.vue'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { useEditorStore } from '@/stores/editor'
import { useJobsStore } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'
import ScreenLayoutPicker from './ScreenLayoutPicker.vue'

const editor = useEditorStore()
const jobs = useJobsStore()
const toasts = useToastsStore()

const validating = ref(false)
const starting = ref(false)
const renderOpen = ref(false)
const renderMode = ref<RenderChoice['kind']>('preview')

/** Grava antes de seguir quando há o que gravar; devolve false se o servidor recusou a spec. */
async function saveFirst(): Promise<boolean> {
  if (!editor.dirty && editor.specErrors.length === 0) return true
  return editor.save()
}

async function validate(): Promise<void> {
  const name = editor.name
  if (!name || !(await saveFirst())) return
  validating.value = true
  try {
    editor.setValidation(await api.projects.validate(name))
  } catch (error) {
    toasts.push({ tone: 'error', title: 'A validação falhou', description: errorMessage(error) })
  } finally {
    validating.value = false
  }
}

function openRender(mode: RenderChoice['kind']): void {
  renderMode.value = mode
  renderOpen.value = true
}

async function startRender(choice: RenderChoice): Promise<void> {
  const name = editor.name
  if (!name) return
  starting.value = true
  try {
    if (!(await saveFirst())) {
      renderOpen.value = false
      return
    }
    let jobId: string
    let description: string
    if (choice.kind === 'export') {
      jobId = (await api.projects.export(name, choice.presets)).job_id
      description = `${name}: export ${choice.presets.join(', ')}`
    } else if (choice.kind === 'preview') {
      jobId = (await api.projects.render(name, { preview: true, segments: choice.segments })).job_id
      description = `${name}: preview`
    } else {
      jobId = (await api.projects.render(name, { preview: false })).job_id
      description = `${name}: render final`
    }
    jobs.track(jobId, { project: name, description })
    renderOpen.value = false
    toasts.push({ tone: 'info', title: 'Render iniciado', description: 'O andamento aparece logo abaixo.' })
  } catch (error) {
    toasts.push({ tone: 'error', title: 'Não foi possível iniciar o render', description: errorMessage(error) })
  } finally {
    starting.value = false
  }
}
</script>

<template>
  <div class="toolbar" role="toolbar" aria-label="Ações do projeto">
    <div class="toolbar__group">
      <AppButton
        :variant="editor.dirty || editor.specErrors.length ? 'primary' : 'secondary'"
        :loading="editor.saving"
        title="Salvar (Ctrl+S)"
        @click="editor.save()"
      >
        Salvar
      </AppButton>
      <AppButton variant="ghost" icon-only aria-label="Desfazer" title="Desfazer" :disabled="!editor.canUndo" @click="editor.undo()">
        <AppIcon name="arrow-left" :size="18" />
      </AppButton>
      <AppButton variant="ghost" icon-only aria-label="Refazer" title="Refazer" :disabled="!editor.canRedo" @click="editor.redo()">
        <AppIcon name="arrow-left" :size="18" class="toolbar__flip" />
      </AppButton>
      <AppBadge v-if="editor.dirty" tone="warning" dot>Não salvo</AppBadge>
      <AppBadge v-else-if="editor.specErrors.length" tone="error" dot>Spec inválida</AppBadge>
      <span v-else class="toolbar__saved">Salvo</span>
    </div>

    <div class="toolbar__group">
      <AppButton :loading="validating" @click="validate">
        <AppIcon name="check" :size="18" />
        Validar
      </AppButton>
      <AppButton @click="openRender('preview')">
        <AppIcon name="play" :size="18" />
        Prévia
      </AppButton>
      <AppButton @click="openRender('final')">Render final</AppButton>
      <AppButton @click="openRender('export')">Exportar</AppButton>
    </div>

    <div class="toolbar__group">
      <ScreenLayoutPicker />
    </div>

    <RenderDialog
      v-model:open="renderOpen"
      :project-name="editor.name ?? ''"
      :busy="starting"
      :initial-mode="renderMode"
      @submit="startRender"
    />
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3) var(--space-5);
}

.toolbar__group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

.toolbar__flip {
  transform: scaleX(-1);
}

.toolbar__saved {
  padding: 0 var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}
</style>
