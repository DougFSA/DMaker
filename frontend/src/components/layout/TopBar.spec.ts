import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { useWorkspaceStore } from '@/stores/workspace'
import TopBar from './TopBar.vue'

let pinia = createPinia()

function mountTopBar() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { render: () => null } },
      { path: '/projetos/:name', name: 'project', component: { render: () => null } },
    ],
  })
  // os menus de jobs e de tema têm as suas próprias telas de teste
  return mount(TopBar, { global: { plugins: [pinia, router], stubs: { JobsMenu: true, ThemeToggle: true } } })
}

beforeEach(() => {
  localStorage.clear()
  pinia = createPinia()
  setActivePinia(pinia)
})

describe('TopBar: botão da navegação em tela larga', () => {
  it('recolhe e alarga a barra lateral, e o nome do botão acompanha', async () => {
    const bar = mountTopBar()
    const button = bar.get('#navigation-toggle')
    expect(button.attributes('aria-label')).toBe('Recolher a barra lateral')
    expect(button.attributes('aria-expanded')).toBeUndefined()
    expect(button.attributes('aria-controls')).toBeUndefined()

    await button.trigger('click')
    expect(useWorkspaceStore().sidebarCollapsed).toBe(true)
    expect(button.attributes('aria-label')).toBe('Expandir a barra lateral')
    expect(useWorkspaceStore().drawerOpen).toBe(false)
  })
})

describe('TopBar: botão da navegação em tela estreita', () => {
  it('abre e fecha a gaveta, e diz isso ao leitor de tela', async () => {
    useWorkspaceStore().setNarrow(true)
    const bar = mountTopBar()
    const button = bar.get('#navigation-toggle')
    expect(button.attributes('aria-label')).toBe('Abrir o menu de navegação')
    expect(button.attributes('aria-expanded')).toBe('false')
    expect(button.attributes('aria-controls')).toBe('barra-lateral')

    await button.trigger('click')
    expect(useWorkspaceStore().drawerOpen).toBe(true)
    expect(button.attributes('aria-label')).toBe('Fechar o menu de navegação')
    expect(button.attributes('aria-expanded')).toBe('true')

    await button.trigger('click')
    expect(useWorkspaceStore().drawerOpen).toBe(false)
  })

  it('não mexe no recolhido guardado da barra larga', async () => {
    useWorkspaceStore().setNarrow(true)
    const bar = mountTopBar()
    await bar.get('#navigation-toggle').trigger('click')
    expect(useWorkspaceStore().sidebarCollapsed).toBe(false)
    expect(localStorage.getItem('dmaker.sidebarCollapsed')).toBeNull()
  })

  it('o projeto atual continua à vista', () => {
    useWorkspaceStore().setNarrow(true)
    useWorkspaceStore().openProject('demo')
    const bar = mountTopBar()
    expect(bar.text()).toContain('demo')
  })
})
