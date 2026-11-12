import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'
import {
  api,
  errorMessage,
  type Persona,
  type PersonaChanges,
  type PersonaDraft,
  type PersonaEngineInfo,
  type PersonaPreviewResult,
  type PersonaUse,
} from '@/api'
import { useConfirmStore } from './confirm'
import { createJobRun, type JobRun } from './jobRun'
import { useToastsStore } from './toasts'

/**
 * As personas: o cadastro (as prontas, só leitura, e as do usuário), o que cada tipo aceita e a prévia da persona
 * falando, que é um job por persona e sobrevive a trocar de tela.
 */
export const usePersonasStore = defineStore('personas', () => {
  const toasts = useToastsStore()
  const confirmations = useConfirmStore()

  const personas = ref<Persona[]>([])
  const engines = ref<PersonaEngineInfo[]>([])
  const loading = ref(false)
  const failure = ref('')
  const saving = ref(false)
  const previews = reactive<Record<string, JobRun<PersonaPreviewResult>>>({})
  const previewResults = ref<Record<string, PersonaPreviewResult>>({})

  const builtin = computed(() => personas.value.filter((persona) => persona.builtin))
  const mine = computed(() => personas.value.filter((persona) => !persona.builtin))

  function engineOf(kind: string): PersonaEngineInfo | undefined {
    return engines.value.find((engine) => engine.kind === kind)
  }

  async function load(): Promise<void> {
    loading.value = true
    failure.value = ''
    try {
      const catalog = await api.personas.list()
      personas.value = catalog.personas
      engines.value = catalog.engines
    } catch (error) {
      failure.value = errorMessage(error)
    } finally {
      loading.value = false
    }
  }

  /** Cria a persona; devolve-a, ou `null` com o motivo num aviso (aparência inválida, nome repetido...). */
  async function create(draft: PersonaDraft): Promise<Persona | null> {
    saving.value = true
    try {
      const created = await api.personas.create(draft)
      toasts.push({ tone: 'success', title: 'Persona criada', description: created.name })
      await load()
      return created
    } catch (error) {
      toasts.push({ tone: 'error', title: 'Não consegui criar a persona', description: errorMessage(error) })
      return null
    } finally {
      saving.value = false
    }
  }

  async function update(id: string, changes: PersonaChanges): Promise<Persona | null> {
    saving.value = true
    try {
      const updated = await api.personas.update(id, changes)
      toasts.push({ tone: 'success', title: 'Persona salva', description: updated.name })
      await load()
      return updated
    } catch (error) {
      toasts.push({ tone: 'error', title: 'Não consegui salvar a persona', description: errorMessage(error) })
      return null
    } finally {
      saving.value = false
    }
  }

  /** Pergunta antes de apagar (não tem volta); devolve se apagou. */
  async function remove(persona: Persona): Promise<boolean> {
    const accepted = await confirmations.ask({
      title: `Apagar ${persona.name}?`,
      description: 'A persona some do cadastro. Projetos que a usam deixam de renderizar até você trocá-la.',
      confirmLabel: 'Apagar',
      tone: 'danger',
    })
    if (!accepted) return false
    try {
      await api.personas.remove(persona.id)
      delete previews[persona.id]
      toasts.push({ tone: 'success', title: 'Persona apagada', description: persona.name })
      await load()
      return true
    } catch (error) {
      toasts.push({ tone: 'error', title: 'Não consegui apagar a persona', description: errorMessage(error) })
      return false
    }
  }

  /** Põe a persona num projeto e avisa onde ela entrou; devolve se deu certo. */
  async function use(persona: Persona, request: PersonaUse): Promise<boolean> {
    try {
      await api.personas.use(persona.id, request)
      const where = request.placement === 'overlay' ? 'no canto' : 'em tela cheia'
      toasts.push({ tone: 'success', title: 'Persona no projeto', description: `${persona.name} fala ${where} em ${request.project}.` })
      return true
    } catch (error) {
      toasts.push({ tone: 'error', title: 'Não consegui pôr a persona no projeto', description: errorMessage(error) })
      return false
    }
  }

  /** Renderiza a prévia da persona falando a frase e guarda o vídeo quando o job acaba. */
  async function preview(persona: Persona, phrase: string): Promise<void> {
    const run = (previews[persona.id] ??= createJobRun<PersonaPreviewResult>())
    const result = await run.run(() => api.personas.preview(persona.id, phrase))
    if (result) previewResults.value = { ...previewResults.value, [persona.id]: result }
  }

  return {
    personas,
    engines,
    loading,
    failure,
    saving,
    previews,
    previewResults,
    builtin,
    mine,
    engineOf,
    load,
    create,
    update,
    remove,
    use,
    preview,
  }
})
