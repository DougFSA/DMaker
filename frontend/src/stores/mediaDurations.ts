/* A duração dos arquivos do painel Mídia, medida pelo servidor (POST /api/probe) uma vez por arquivo. Fica fora do
   painel para esconder o painel e mostrá-lo de novo não repetir a medição. */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api'

export const useMediaDurationsStore = defineStore('mediaDurations', () => {
  /** Segundos de cada caminho absoluto; `null` quando o servidor não conseguiu medir (arquivo ausente, sem trilha). */
  const seconds = ref<Record<string, number | null>>({})
  // o que já foi pedido (e está a caminho) não é pedido de novo a cada mudança da spec
  const asked = new Set<string>()

  /** Mede os caminhos que ainda não foram medidos, num pedido só. */
  async function ensure(paths: readonly string[]): Promise<void> {
    const wanted = [...new Set(paths)].filter((path) => path && !asked.has(path))
    if (wanted.length === 0) return
    for (const path of wanted) asked.add(path)
    try {
      const results = await api.editor.probe(wanted)
      const next = { ...seconds.value }
      for (const path of wanted) next[path] = null
      for (const result of results) next[result.path] = result.error === undefined ? result.duration_s : null
      seconds.value = next
    } catch {
      // sem resposta: a próxima mudança da lista tenta de novo, em vez de dar o arquivo por impossível de medir
      for (const path of wanted) asked.delete(path)
    }
  }

  return { seconds, ensure }
})
