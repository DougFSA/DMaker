import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { readStored, writeStored } from '@/lib/storage'

const PROJECT_KEY = 'dmaker.currentProject'
const SIDEBAR_KEY = 'dmaker.sidebarCollapsed'

/**
 * Estado de navegação: projeto atual (TopBar), barra lateral recolhida (sobrevive a recarregar) e, em tela estreita,
 * a gaveta da navegação (não sobrevive: ela sempre nasce fechada).
 */
export const useWorkspaceStore = defineStore('workspace', () => {
  const currentProject = ref<string | null>(readStored(PROJECT_KEY))
  const sidebarCollapsed = ref(readStored(SIDEBAR_KEY) === '1')
  /** Tela estreita (abaixo de 768 px): a barra lateral sai da grade e vira gaveta. Quem mede é o AppShell. */
  const narrow = ref(false)
  const drawerOpen = ref(false)

  /** A barra lateral está mesmo recolhida na tela: em tela estreita o recolhido salvo não vale, a gaveta mostra os nomes. */
  const sidebarCompact = computed(() => sidebarCollapsed.value && !narrow.value)

  function openProject(name: string | null): void {
    currentProject.value = name
    writeStored(PROJECT_KEY, name ?? '')
  }

  function toggleSidebar(): void {
    sidebarCollapsed.value = !sidebarCollapsed.value
    writeStored(SIDEBAR_KEY, sidebarCollapsed.value ? '1' : '0')
  }

  /** Cada vez que a tela passa para estreita (ou volta a ser larga) a gaveta recomeça fechada. */
  function setNarrow(value: boolean): void {
    narrow.value = value
    drawerOpen.value = false
  }

  function closeDrawer(): void {
    drawerOpen.value = false
  }

  /** O botão da barra de cima: abre e fecha a gaveta em tela estreita; nas outras, recolhe e alarga a barra lateral. */
  function toggleNavigation(): void {
    if (narrow.value) drawerOpen.value = !drawerOpen.value
    else toggleSidebar()
  }

  return {
    currentProject,
    sidebarCollapsed,
    sidebarCompact,
    narrow,
    drawerOpen,
    openProject,
    toggleSidebar,
    setNarrow,
    closeDrawer,
    toggleNavigation,
  }
})
