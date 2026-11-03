import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { useWorkspaceStore } from './workspace'

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
})

describe('workspace: projeto atual', () => {
  it('guarda o projeto aberto e o devolve ao recarregar', () => {
    useWorkspaceStore().openProject('demo')
    expect(localStorage.getItem('dmaker.currentProject')).toBe('demo')

    setActivePinia(createPinia())
    expect(useWorkspaceStore().currentProject).toBe('demo')
  })
})

describe('workspace: barra lateral em tela larga', () => {
  it('começa alargada, recolhe e alarga guardando a escolha', () => {
    const workspace = useWorkspaceStore()
    expect(workspace.sidebarCollapsed).toBe(false)
    expect(workspace.sidebarCompact).toBe(false)

    workspace.toggleNavigation()
    expect(workspace.sidebarCollapsed).toBe(true)
    expect(workspace.sidebarCompact).toBe(true)
    expect(localStorage.getItem('dmaker.sidebarCollapsed')).toBe('1')

    workspace.toggleNavigation()
    expect(workspace.sidebarCollapsed).toBe(false)
    expect(localStorage.getItem('dmaker.sidebarCollapsed')).toBe('0')
  })

  it('o botão não mexe na gaveta', () => {
    const workspace = useWorkspaceStore()
    workspace.toggleNavigation()
    expect(workspace.drawerOpen).toBe(false)
  })

  it('o recolhido guardado vale ao recarregar', () => {
    localStorage.setItem('dmaker.sidebarCollapsed', '1')
    expect(useWorkspaceStore().sidebarCompact).toBe(true)
  })
})

describe('workspace: gaveta em tela estreita', () => {
  it('nasce fechada, mesmo com o recolhido guardado, e mostra a barra inteira', () => {
    localStorage.setItem('dmaker.sidebarCollapsed', '1')
    const workspace = useWorkspaceStore()
    workspace.setNarrow(true)

    expect(workspace.drawerOpen).toBe(false)
    expect(workspace.sidebarCollapsed).toBe(true)
    expect(workspace.sidebarCompact).toBe(false)
  })

  it('o botão abre e fecha a gaveta e deixa o recolhido guardado em paz', () => {
    const workspace = useWorkspaceStore()
    workspace.setNarrow(true)

    workspace.toggleNavigation()
    expect(workspace.drawerOpen).toBe(true)
    workspace.toggleNavigation()
    expect(workspace.drawerOpen).toBe(false)

    expect(workspace.sidebarCollapsed).toBe(false)
    expect(localStorage.getItem('dmaker.sidebarCollapsed')).toBeNull()
  })

  it('closeDrawer fecha a gaveta aberta', () => {
    const workspace = useWorkspaceStore()
    workspace.setNarrow(true)
    workspace.toggleNavigation()
    workspace.closeDrawer()
    expect(workspace.drawerOpen).toBe(false)
  })

  it('ao cruzar o limite, nos dois sentidos, a gaveta recomeça fechada', () => {
    const workspace = useWorkspaceStore()
    workspace.setNarrow(true)
    workspace.toggleNavigation()
    expect(workspace.drawerOpen).toBe(true)

    workspace.setNarrow(false)
    expect(workspace.drawerOpen).toBe(false)

    workspace.setNarrow(true)
    expect(workspace.drawerOpen).toBe(false)
  })

  it('voltando à tela larga, o recolhido guardado volta a valer', () => {
    localStorage.setItem('dmaker.sidebarCollapsed', '1')
    const workspace = useWorkspaceStore()
    workspace.setNarrow(true)
    workspace.setNarrow(false)
    expect(workspace.sidebarCompact).toBe(true)
  })
})
