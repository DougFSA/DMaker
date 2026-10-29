/* Quais painéis da bancada do editor estão ocultos (os botões F e M da barra da linha do tempo). Fica guardado no
   navegador: a pessoa que esconde os filtros os quer escondidos na próxima vez que abrir um projeto. */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { EditorPanelId } from '@/components/editor/panels'
import { readStored, writeStored } from '@/lib/storage'

const HIDDEN_KEY = 'dmaker.editor.hiddenPanels'

function storedHidden(): EditorPanelId[] {
  try {
    const parsed: unknown = JSON.parse(readStored(HIDDEN_KEY) ?? '[]')
    return Array.isArray(parsed) ? parsed.filter((id): id is EditorPanelId => typeof id === 'string') : []
  } catch {
    return []
  }
}

export const useEditorPanelsStore = defineStore('editorPanels', () => {
  const hidden = ref<EditorPanelId[]>(storedHidden())

  function isHidden(id: EditorPanelId): boolean {
    return hidden.value.includes(id)
  }

  function setHidden(id: EditorPanelId, value: boolean): void {
    const rest = hidden.value.filter((candidate) => candidate !== id)
    hidden.value = value ? [...rest, id] : rest
    writeStored(HIDDEN_KEY, JSON.stringify(hidden.value))
  }

  function toggle(id: EditorPanelId): void {
    setHidden(id, !isHidden(id))
  }

  return { hidden, isHidden, setHidden, toggle }
})
