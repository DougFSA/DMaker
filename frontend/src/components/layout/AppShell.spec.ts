import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { useScreenLayoutStore } from '@/stores/screenLayout'
import { useWorkspaceStore } from '@/stores/workspace'
import AppShell from './AppShell.vue'

const Blank = { render: () => null }

async function mountShell(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/projetos', component: Blank, meta: { title: 'Projetos' } },
      { path: '/editor/:name?', component: Blank, meta: { title: 'Editor', wide: true } },
    ],
  })
  await router.push(path)
  await router.isReady()
  // a barra lateral e a de cima têm as suas próprias telas de teste; aqui só importa o miolo
  return mount(AppShell, { global: { plugins: [pinia, router], stubs: { SidebarNav: true, TopBar: true } } })
}

let pinia = createPinia()

beforeEach(() => {
  localStorage.clear()
  pinia = createPinia()
  setActivePinia(pinia)
})

describe('AppShell', () => {
  it('o conteúdo tem o limite de leitura nas telas comuns', async () => {
    const shell = await mountShell('/projetos')
    expect(shell.find('#conteudo').classes()).not.toContain('shell__content--wide')
  })

  it('a rota que pede a largura toda (o editor) tira o limite do conteúdo', async () => {
    const shell = await mountShell('/editor/demo')
    expect(shell.find('#conteudo').classes()).toContain('shell__content--wide')
  })

  it('o editor sem projeto (/editor) também usa a largura toda', async () => {
    const shell = await mountShell('/editor')
    expect(shell.find('#conteudo').classes()).toContain('shell__content--wide')
  })

  it('a largura da barra lateral vem do layout de tela, e o divisor dela a muda e guarda', async () => {
    const shell = await mountShell('/projetos')
    expect(shell.attributes('style')).toContain('--sidebar-width: 248px')

    const divider = shell.get('[aria-label="Largura da barra lateral"]')
    await divider.trigger('mousedown', { button: 0, clientX: 248 })
    window.dispatchEvent(new MouseEvent('mousemove', { clientX: 300 }))
    window.dispatchEvent(new MouseEvent('mouseup'))
    await shell.vm.$nextTick()

    expect(useScreenLayoutStore().layout.sizes['col-sidebar']).toBe(300)
    expect(shell.attributes('style')).toContain('--sidebar-width: 300px')
    expect(shell.classes()).not.toContain('shell--resizing')
  })

  it('com a barra lateral recolhida, vale a medida fixa e o divisor some', async () => {
    const shell = await mountShell('/projetos')
    useWorkspaceStore().toggleSidebar()
    await shell.vm.$nextTick()
    expect(shell.attributes('style')).toBeUndefined()
    expect(shell.find('[aria-label="Largura da barra lateral"]').exists()).toBe(false)
  })

  it('um layout com outra largura de barra lateral a aplica (o da clássica guarda 300)', async () => {
    const shell = await mountShell('/projetos')
    useScreenLayoutStore().setSize('col-sidebar', 420)
    await shell.vm.$nextTick()
    expect(shell.attributes('style')).toContain('--sidebar-width: 420px')
  })
})
