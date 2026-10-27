import { defineStore } from 'pinia'
import { ref } from 'vue'
import { readStored, writeStored } from '@/lib/storage'

const PROJECT_KEY = 'dmaker.currentProject'
const SIDEBAR_KEY = 'dmaker.sidebarCollapsed'

/** Estado de navegação que sobrevive a recarregar: projeto atual (TopBar) e barra lateral recolhida. */
export const useWorkspaceStore = defineStore('workspace', () => {
  const currentProject = ref<string | null>(readStored(PROJECT_KEY))
  const sidebarCollapsed = ref(readStored(SIDEBAR_KEY) === '1')

  function openProject(name: string | null): void {
    currentProject.value = name
    writeStored(PROJECT_KEY, name ?? '')
  }

  function toggleSidebar(): void {
    sidebarCollapsed.value = !sidebarCollapsed.value
    writeStored(SIDEBAR_KEY, sidebarCollapsed.value ? '1' : '0')
  }

  return { currentProject, sidebarCollapsed, openProject, toggleSidebar }
})
