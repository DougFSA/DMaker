import { computed, ref, watch, type Ref } from 'vue'
import { api, errorMessage, type ProjectSpec, type TimelineView } from '@/api'
import { collectMediaEntries, hasRelativePaths, projectMediaOptions, type MediaEntry, type MediaOption } from '@/lib/media'

/** A mídia do projeto aberto (fontes, trechos, sobreposições e música), recarregada quando o projeto muda. */
export function useProjectMedia(project: Ref<string | null>) {
  const spec = ref<ProjectSpec | null>(null)
  const entries = ref<MediaEntry[]>([])
  const loading = ref(false)
  const error = ref('')
  // uma resposta atrasada de outro projeto não pode sobrescrever a do projeto atual
  let generation = 0

  const options = computed<MediaOption[]>(() => projectMediaOptions(entries.value))

  async function load(): Promise<void> {
    const name = project.value
    const mine = (generation += 1)
    error.value = ''
    if (!name) {
      spec.value = null
      entries.value = []
      return
    }
    loading.value = true
    try {
      const detail = await api.projects.get(name)
      let found = collectMediaEntries(detail.spec)
      if (hasRelativePaths(found)) {
        // caminho relativo só o servidor sabe resolver; se a vista falhar (fonte ausente), segue com o que a spec diz
        let view: TimelineView | null = null
        try {
          view = await api.editor.timeline(name)
        } catch {
          view = null
        }
        found = collectMediaEntries(detail.spec, view)
      }
      if (mine !== generation) return
      spec.value = detail.spec
      entries.value = found
    } catch (failure) {
      if (mine !== generation) return
      spec.value = null
      entries.value = []
      error.value = errorMessage(failure)
    } finally {
      if (mine === generation) loading.value = false
    }
  }

  watch(project, () => void load(), { immediate: true })

  return { spec, entries, options, loading, error, reload: load }
}
