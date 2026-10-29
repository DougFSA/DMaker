<script setup lang="ts">
/* Escolha da mídia que as telas de áudio vão tratar (isolar voz, corrigir fala, trocar voz, dublar): um arquivo
   do projeto aberto (vídeos e áudios que a spec usa) ou um arquivo enviado do computador. */
import { computed, ref, watch } from 'vue'
import { api, errorMessage } from '@/api'
import AppSelect, { type SelectOption } from '@/components/ui/AppSelect.vue'
import FileUpload from '@/components/ui/FileUpload.vue'
import { useProjectMedia } from '@/composables/useProjectMedia'
import type { MediaEntry } from '@/lib/media'
import { useToastsStore } from '@/stores/toasts'
import { useWorkspaceStore } from '@/stores/workspace'

/** O que a tela recebe ao escolher: o caminho para as rotas de áudio e, se veio do projeto, a entrada da spec. */
export interface PickedMedia {
  /** Caminho no disco do servidor, pronto para as rotas de áudio. */
  path: string
  name: string
  origin: 'project' | 'upload'
  /** A entrada da spec (só de mídia do projeto): "Usar no projeto" precisa dela para saber o que trocar. */
  entry: MediaEntry | null
}

const props = withDefaults(
  defineProps<{
    label?: string
    /** Projeto de onde tirar a mídia; sem valor vale o aberto no momento, e `null` desliga a lista do projeto. */
    project?: string | null
    id?: string
  }>(),
  { label: 'Arquivo' },
)

const picked = defineModel<PickedMedia | null>({ default: null })
// vídeo e áudio por tipo e por extensão: alguns navegadores deixam o tipo MIME de .mkv e .flac em branco
const ACCEPT = 'video/*,audio/*,.mp4,.mov,.mkv,.webm,.avi,.m4v,.wav,.mp3,.m4a,.ogg,.flac'
const UPLOAD_CHOICE = 'upload'
const UPLOADED_CHOICE = 'uploaded'

const workspace = useWorkspaceStore()
const toasts = useToastsStore()
const projectName = computed(() => (props.project === undefined ? workspace.currentProject : props.project))
const { options, loading, error: loadError } = useProjectMedia(projectName)

const uploaded = ref<{ path: string; name: string } | null>(null)
const files = ref<File[]>([])
const uploading = ref(false)
const choice = ref('')

const selectOptions = computed<SelectOption[]>(() => {
  const list: SelectOption[] = options.value.map((option) => ({ value: option.value, label: option.label }))
  if (uploaded.value) list.push({ value: UPLOADED_CHOICE, label: `Enviado: ${uploaded.value.name}` })
  list.push({ value: UPLOAD_CHOICE, label: 'Enviar um arquivo...' })
  return list
})

const hint = computed(() => {
  if (loadError.value) return `Não consegui ler a mídia do projeto: ${loadError.value}`
  if (loading.value) return 'Lendo a mídia do projeto...'
  if (!projectName.value) return 'Abra um projeto para escolher a mídia dele, ou envie um arquivo.'
  if (options.value.length === 0) return `O projeto ${projectName.value} não tem vídeo nem áudio. Envie um arquivo.`
  return `Mídia do projeto ${projectName.value}, ou um arquivo enviado.`
})

// a lista do projeto chega depois da primeira renderização: enquanto a pessoa não escolheu, ela vale mais que o envio
let chosenByUser = false

function choose(value: string): void {
  chosenByUser = true
  choice.value = value
}

/** Mantém a escolha enquanto ela existir; senão cai na primeira mídia do projeto ou no envio. */
watch(
  selectOptions,
  (list) => {
    const stillThere = list.some((option) => option.value === choice.value)
    const projectArrived = !chosenByUser && choice.value === UPLOAD_CHOICE && list.length > 1
    if (stillThere && !projectArrived) return
    choice.value = list[0]?.value ?? UPLOAD_CHOICE
  },
  { immediate: true },
)

watch(
  [choice, options, uploaded],
  () => {
    if (choice.value === UPLOADED_CHOICE && uploaded.value) {
      picked.value = { path: uploaded.value.path, name: uploaded.value.name, origin: 'upload', entry: null }
      return
    }
    const option = options.value.find((candidate) => candidate.value === choice.value)
    picked.value = option ? { path: option.path, name: option.label, origin: 'project', entry: option.entry } : null
  },
  { immediate: true },
)

async function upload(selected: File[]): Promise<void> {
  const file = selected[0]
  if (!file) return
  uploading.value = true
  try {
    const sent = await api.speech.upload(file)
    uploaded.value = { path: sent.path, name: file.name }
    choice.value = UPLOADED_CHOICE
  } catch (failure) {
    toasts.push({ tone: 'error', title: 'Não consegui enviar o arquivo', description: errorMessage(failure) })
  } finally {
    uploading.value = false
    files.value = []
  }
}
</script>

<template>
  <div class="picker">
    <AppSelect
      :model-value="choice"
      :label="label"
      :options="selectOptions"
      :hint="hint"
      :id="id"
      @update:model-value="choose"
    />
    <FileUpload
      v-if="choice === UPLOAD_CHOICE"
      v-model="files"
      label="Enviar vídeo ou áudio"
      :accept="ACCEPT"
      :busy="uploading"
      @select="upload"
    />
  </div>
</template>

<style scoped>
.picker {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-width: 0;
}
</style>
