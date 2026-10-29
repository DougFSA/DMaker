import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  api,
  errorMessage,
  type DubPrepareRequest,
  type DubProjectFile,
  type DubProjectSummary,
  type DubRenderResult,
  type DubSegmentReport,
  type DubStemsResult,
  type VoiceOption,
} from '@/api'
import type { PickedMedia } from '@/components/media/MediaPicker.vue'
import {
  describeStems,
  fitModeOf,
  keepDbFrom,
  parseGlossary,
  rowsChanged,
  rowsFrom,
  sameLanguage,
  segmentEdits,
  speakerModeOf,
  type DubRow,
} from '@/lib/dub'
import type { MediaEntry } from '@/lib/media'
import { createJobRun } from './jobRun'
import { useToastsStore } from './toasts'
import { useWorkspaceStore } from './workspace'

/** O resultado de gerar a dublagem. O `stamp` faz o navegador buscar de novo o vídeo regravado no mesmo endereço. */
export interface DubOutcome extends DubRenderResult {
  stamp: number
}

/**
 * Dublagem: o formulário de preparar, o projeto de falas em edição e o resultado ficam aqui, porque cada trabalho leva
 * minutos e a pessoa pode trocar de tela enquanto ele roda. Só um trabalho pesado corre por vez (`busy`).
 */
export const useDubbingStore = defineStore('dubbing', () => {
  const workspace = useWorkspaceStore()
  const toasts = useToastsStore()

  // o formulário; seletores trabalham com texto, e `speakerModeOf`/`fitModeOf` estreitam na hora de enviar
  const media = ref<PickedMedia | null>(null)
  const sourceLanguage = ref('pt')
  const targetLanguage = ref('en')
  const speakerMode = ref('per_speaker')
  const speakerCount = ref<number | null>(null)
  const voice = ref('')
  const keepDb = ref<number | null>(null)
  const fitMode = ref('voz')
  const glossary = ref('')
  const draft = ref(false)

  const languages = ref<VoiceOption[]>([])
  const savedProjects = ref<DubProjectFile[]>([])
  const savedChoice = ref('')
  const loadError = ref('')

  // o projeto aberto: o que o servidor guardou (`project`) e o que a tabela edita (`rows`)
  const project = ref<DubProjectSummary | null>(null)
  const rows = ref<DubRow[]>([])
  /** De onde veio o arquivo dublado, para "Usar no projeto": a entrada da spec e o projeto dela. */
  const entry = ref<MediaEntry | null>(null)
  const entryProject = ref<string | null>(null)
  const outcome = ref<DubOutcome | null>(null)
  const stemsNote = ref('')
  const actionError = ref('')
  const saving = ref(false)

  const preparation = createJobRun<DubProjectSummary>()
  const retranslation = createJobRun<DubProjectSummary>()
  const generation = createJobRun<DubRenderResult>()
  const stems = createJobRun<DubStemsResult>()

  const busy = computed(
    () => saving.value || preparation.running || retranslation.running || generation.running || stems.running,
  )
  const sameLanguages = computed(() => sameLanguage(sourceLanguage.value, targetLanguage.value))
  const canPrepare = computed(() => !!media.value && !sameLanguages.value && !busy.value)
  const canOpenSaved = computed(() => !!savedChoice.value && !busy.value)
  const canChangeProject = computed(() => !!project.value && !busy.value)

  /** Há algo na tela que o arquivo `.dub.json` ainda não tem (uma tradução, uma trava, um falante ou uma opção). */
  const dirty = computed(() => {
    const current = project.value
    if (!current) return false
    return (
      rowsChanged(current.segments, rows.value) ||
      speakerModeOf(speakerMode.value) !== current.speaker_mode ||
      fitModeOf(fitMode.value) !== (current.fit_mode || 'voz') ||
      (voice.value || null) !== current.voice ||
      keepDbFrom(keepDb.value) !== current.keep_original_db
    )
  })

  /** A situação de cada fala depois de gerar, pelo id da fala. */
  const reports = computed<Record<string, DubSegmentReport>>(() =>
    Object.fromEntries((outcome.value?.report ?? []).map((report) => [report.id, report])),
  )

  /** O projeto de onde veio o arquivo escolhido: o aberto no momento, quando o arquivo é da mídia do projeto. */
  function projectOf(source: PickedMedia): string | null {
    return source.origin === 'project' ? workspace.currentProject : null
  }

  /** Mostra o projeto como o servidor o guardou: a tabela e as opções do formulário passam a refletir o arquivo. */
  function applyProject(next: DubProjectSummary): void {
    project.value = next
    rows.value = rowsFrom(next.segments)
    speakerMode.value = next.speaker_mode
    fitMode.value = next.fit_mode || 'voz'
    voice.value = next.voice ?? ''
    keepDb.value = next.keep_original_db
  }

  async function loadLanguages(): Promise<void> {
    try {
      languages.value = (await api.voice.designOptions()).languages
    } catch (failure) {
      loadError.value = `Não consegui ler os idiomas: ${errorMessage(failure)}`
    }
  }

  async function loadSaved(): Promise<void> {
    try {
      savedProjects.value = await api.dub.projects()
    } catch (failure) {
      loadError.value = `Não consegui ler as dublagens preparadas: ${errorMessage(failure)}`
    }
  }

  /** Transcreve, separa os falantes e traduz (job). No fim a tabela de falas aparece para revisar. */
  async function prepare(): Promise<void> {
    const source = media.value
    if (!source || !canPrepare.value) return
    const request: DubPrepareRequest = {
      path: source.path,
      source_language: sourceLanguage.value,
      target_language: targetLanguage.value,
      speaker_mode: speakerModeOf(speakerMode.value),
      fit_mode: fitModeOf(fitMode.value),
      // a quantidade só faz sentido no modo "uma voz por pessoa"
      num_speakers: speakerModeOf(speakerMode.value) === 'per_speaker' ? speakerCount.value : null,
      voice: voice.value || null,
      keep_original_db: keepDbFrom(keepDb.value),
      glossary: parseGlossary(glossary.value),
    }
    outcome.value = null
    stemsNote.value = ''
    actionError.value = ''
    const result = await preparation.run(() => api.dub.prepare(request))
    if (!result) return
    entry.value = source.entry
    entryProject.value = projectOf(source)
    applyProject(result)
    void loadSaved()
  }

  /** Abre uma dublagem já preparada. A origem dela não é conhecida, então "Usar no projeto" tenta achá-la no projeto aberto. */
  async function openSaved(): Promise<void> {
    const path = savedChoice.value
    if (!path || busy.value) return
    actionError.value = ''
    try {
      const opened = await api.dub.project(path)
      entry.value = null
      entryProject.value = null
      outcome.value = null
      stemsNote.value = ''
      applyProject(opened)
    } catch (failure) {
      actionError.value = errorMessage(failure)
    }
  }

  /** Grava as traduções, as travas, os falantes e as opções. Devolve se deu certo; o erro fica em `actionError`. */
  async function save(): Promise<boolean> {
    const current = project.value
    if (!current) return false
    saving.value = true
    actionError.value = ''
    try {
      applyProject(
        await api.dub.saveProject({
          project: current.project,
          segments: segmentEdits(rows.value),
          keep_original_db: keepDbFrom(keepDb.value),
          speaker_mode: speakerModeOf(speakerMode.value),
          fit_mode: fitModeOf(fitMode.value),
          voice: voice.value || null,
        }),
      )
      return true
    } catch (failure) {
      actionError.value = errorMessage(failure)
      toasts.push({ tone: 'error', title: 'Não consegui salvar as traduções', description: actionError.value })
      return false
    } finally {
      saving.value = false
    }
  }

  async function saveTranslations(): Promise<void> {
    if (!canChangeProject.value) return
    if (await save()) toasts.push({ tone: 'success', title: 'Traduções salvas' })
  }

  /** Traduz de novo só as falas sem trava (job), depois de salvar o que a pessoa já corrigiu. */
  async function retranslate(): Promise<void> {
    if (!canChangeProject.value || !(await save())) return
    const path = project.value?.project
    if (!path) return
    const result = await retranslation.run(() => api.dub.retranslate(path))
    if (result) applyProject(result)
  }

  /** Gera a dublagem (job), depois de salvar. `draft` troca qualidade por velocidade. */
  async function render(): Promise<void> {
    if (!canChangeProject.value || !(await save())) return
    const path = project.value?.project
    if (!path) return
    outcome.value = null
    stemsNote.value = ''
    const result = await generation.run(() => api.dub.render(path, draft.value))
    if (result) outcome.value = { ...result, stamp: Date.now() }
  }

  /** Exporta as trilhas separadas (job) e devolve o endereço do .zip; vazio se falhou ou parou, e o motivo fica no andamento. */
  async function makeStems(): Promise<string> {
    if (!canChangeProject.value || !(await save())) return ''
    const path = project.value?.project
    if (!path) return ''
    stemsNote.value = ''
    const result = await stems.run(() => api.dub.stems(path, draft.value))
    if (!result) return ''
    stemsNote.value = describeStems(result)
    return result.zip_url
  }

  return {
    media,
    sourceLanguage,
    targetLanguage,
    speakerMode,
    speakerCount,
    voice,
    keepDb,
    fitMode,
    glossary,
    draft,
    languages,
    savedProjects,
    savedChoice,
    loadError,
    project,
    rows,
    entry,
    entryProject,
    outcome,
    stemsNote,
    actionError,
    saving,
    preparation,
    retranslation,
    generation,
    stems,
    busy,
    sameLanguages,
    canPrepare,
    canOpenSaved,
    canChangeProject,
    dirty,
    reports,
    loadLanguages,
    loadSaved,
    prepare,
    openSaved,
    saveTranslations,
    retranslate,
    render,
    makeStems,
  }
})
