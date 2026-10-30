import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type SpecDocument } from '@/api'
import { replaceSourceOps, type MediaEntry } from '@/lib/media'
import { useEditorStore } from './editor'

/** "Usar no projeto": troca um arquivo por outro (a fala corrigida, a voz trocada, o vídeo dublado) no projeto e salva. */
export const useSourceReplacementStore = defineStore('sourceReplacement', () => {
  const editor = useEditorStore()
  const busy = ref(false)

  /**
   * Troca `entry` por `newPath` em tudo que o projeto usa (fontes, trechos de vídeo e vídeos sobrepostos) e grava a
   * spec. Devolve em quantos pontos trocou, ou 0 se nada no projeto usa esse arquivo (então nada é salvo). A spec vem
   * do servidor na hora: a que a tela leu ao escolher o arquivo pode ter mudado desde então.
   */
  async function replace(project: string, entry: MediaEntry, newPath: string): Promise<number> {
    busy.value = true
    try {
      if (editor.name === project && editor.status === 'ready' && editor.spec) {
        // o editor é a fonte da verdade enquanto está com o projeto aberto: gravar por fora deixaria a cópia dele
        // velha, e o próximo Salvar desfaria a troca
        const planned = replaceSourceOps(editor.spec, entry, newPath)
        if (planned.length === 0) return 0
        if (!(await editor.applyOps(planned)) || !(await editor.save())) throw new Error(editor.saveError || 'a troca não foi salva')
        return planned.length
      }
      const detail = await api.projects.get(project)
      let spec: SpecDocument = detail.spec
      const operations = replaceSourceOps(spec, entry, newPath)
      for (const operation of operations) spec = (await api.editor.edit(project, spec, operation)).spec
      if (operations.length > 0) await api.editor.saveProject(project, spec)
      return operations.length
    } finally {
      busy.value = false
    }
  }

  return { busy, replace }
})
