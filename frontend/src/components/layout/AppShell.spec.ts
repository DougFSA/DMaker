import { mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { useScreenLayoutStore } from '@/stores/screenLayout'
import { useWorkspaceStore } from '@/stores/workspace'
import { installFakeMatchMedia, type FakeMediaQuery } from '@/test/mediaQuery'
import AppShell from './AppShell.vue'

const Blank = { render: () => null }

/** A barra lateral de verdade tem a sua própria tela de teste; aqui basta um link para a gaveta fechar ao tocar nele. */
const NavWithLink = { template: '<nav><a class="nav-link" href="#projetos">Projetos</a></nav>' }

const mounted: VueWrapper[] = []

async function mountShell(path: string, stubs: Record<string, unknown> = { SidebarNav: true }) {
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
  const shell = mount(AppShell, {
    attachTo: document.body,
    global: { plugins: [pinia, router], stubs: { TopBar: true, ...stubs } },
  })
  mounted.push(shell)
  return shell
}

let pinia = createPinia()

beforeEach(() => {
  localStorage.clear()
  pinia = createPinia()
  setActivePinia(pinia)
  installFakeMatchMedia(false)
})

afterEach(() => {
  for (const shell of mounted.splice(0)) shell.unmount()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
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

describe('AppShell: tela larga (768 px ou mais) continua como sempre', () => {
  it('a barra lateral fica na grade, sem papel de gaveta e sem ficar inerte', async () => {
    const shell = await mountShell('/projetos')
    const sidebar = shell.get('aside')
    expect(shell.classes()).not.toContain('shell--narrow')
    expect(sidebar.attributes('role')).toBeUndefined()
    expect(sidebar.attributes('aria-modal')).toBeUndefined()
    expect(sidebar.attributes('tabindex')).toBeUndefined()
    expect(sidebar.element.hasAttribute('inert')).toBe(false)
    expect(shell.find('.shell__backdrop').exists()).toBe(false)
    expect(shell.find('[aria-label="Largura da barra lateral"]').exists()).toBe(true)
  })

  it('o recolhido guardado vale: a barra é a estreita e passa a ela o aviso de recolhida', async () => {
    localStorage.setItem('dmaker.sidebarCollapsed', '1')
    pinia = createPinia()
    setActivePinia(pinia)
    const shell = await mountShell('/projetos')
    expect(shell.classes()).toContain('shell--collapsed')
    expect(shell.findComponent({ name: 'SidebarNav' }).props('collapsed')).toBe(true)
  })
})

describe('AppShell: tela estreita (abaixo de 768 px) vira gaveta', () => {
  let media: FakeMediaQuery

  beforeEach(() => {
    media = installFakeMatchMedia(true)
  })

  it('começa fechada: fora da grade, inerte, sem fundo e sem o divisor de largura', async () => {
    const shell = await mountShell('/projetos')
    const sidebar = shell.get('aside')
    expect(shell.classes()).toContain('shell--narrow')
    expect(useWorkspaceStore().narrow).toBe(true)
    expect(sidebar.classes()).not.toContain('is-open')
    expect(sidebar.element.hasAttribute('inert')).toBe(true)
    expect(shell.find('.shell__backdrop').exists()).toBe(false)
    expect(shell.find('[aria-label="Largura da barra lateral"]').exists()).toBe(false)
    expect(shell.get('.shell__main').element.hasAttribute('inert')).toBe(false)
    expect(document.documentElement.classList.contains('is-scroll-locked')).toBe(false)
  })

  it('ignora o recolhido guardado e a largura do layout: a gaveta mostra os nomes na medida padrão', async () => {
    localStorage.setItem('dmaker.sidebarCollapsed', '1')
    pinia = createPinia()
    setActivePinia(pinia)
    const shell = await mountShell('/projetos')
    useScreenLayoutStore().setSize('col-sidebar', 420)
    await shell.vm.$nextTick()

    expect(shell.classes()).not.toContain('shell--collapsed')
    expect(shell.findComponent({ name: 'SidebarNav' }).props('collapsed')).toBe(false)
    expect(shell.attributes('style')).toBeUndefined()
  })

  it('aberta pelo botão, vira um diálogo que cobre a tela: o resto fica inerte e a página não rola', async () => {
    const shell = await mountShell('/projetos')
    useWorkspaceStore().toggleNavigation()
    await shell.vm.$nextTick()

    const sidebar = shell.get('aside')
    expect(sidebar.classes()).toContain('is-open')
    expect(sidebar.element.hasAttribute('inert')).toBe(false)
    expect(sidebar.attributes('role')).toBe('dialog')
    expect(sidebar.attributes('aria-modal')).toBe('true')
    expect(sidebar.attributes('aria-label')).toBe('Menu de navegação')
    expect(shell.find('.shell__backdrop').exists()).toBe(true)
    expect(shell.get('.shell__main').element.hasAttribute('inert')).toBe(true)
    expect(shell.get('.shell__skip').element.hasAttribute('inert')).toBe(true)
    expect(document.documentElement.classList.contains('is-scroll-locked')).toBe(true)
  })

  it('o foco vai para a gaveta ao abrir e volta ao botão da barra de cima ao fechar', async () => {
    const toggle = document.createElement('button')
    toggle.id = 'navigation-toggle'
    document.body.append(toggle)
    const shell = await mountShell('/projetos')

    toggle.focus()
    useWorkspaceStore().toggleNavigation()
    await shell.vm.$nextTick()
    expect(document.activeElement).toBe(shell.get('aside').element)

    useWorkspaceStore().toggleNavigation()
    await shell.vm.$nextTick()
    expect(document.activeElement).toBe(toggle)
    expect(document.documentElement.classList.contains('is-scroll-locked')).toBe(false)
  })

  it('Esc fecha a gaveta, e só o Esc', async () => {
    const shell = await mountShell('/projetos')
    useWorkspaceStore().toggleNavigation()
    await shell.vm.$nextTick()

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'a' }))
    await shell.vm.$nextTick()
    expect(useWorkspaceStore().drawerOpen).toBe(true)

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await shell.vm.$nextTick()
    expect(useWorkspaceStore().drawerOpen).toBe(false)
    expect(shell.find('.shell__backdrop').exists()).toBe(false)
  })

  it('um Esc que outro componente já tratou não fecha a gaveta', async () => {
    const shell = await mountShell('/projetos')
    useWorkspaceStore().toggleNavigation()
    await shell.vm.$nextTick()

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', cancelable: true }))
    expect(useWorkspaceStore().drawerOpen).toBe(false)

    useWorkspaceStore().toggleNavigation()
    await shell.vm.$nextTick()
    const handled = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true })
    handled.preventDefault()
    document.dispatchEvent(handled)
    expect(useWorkspaceStore().drawerOpen).toBe(true)
  })

  it('um toque no fundo fecha a gaveta', async () => {
    const shell = await mountShell('/projetos')
    useWorkspaceStore().toggleNavigation()
    await shell.vm.$nextTick()

    await shell.get('.shell__backdrop').trigger('click')
    expect(useWorkspaceStore().drawerOpen).toBe(false)
    expect(shell.get('aside').classes()).not.toContain('is-open')
  })

  it('um toque num link da gaveta a fecha, mesmo na página em que a pessoa já está', async () => {
    const shell = await mountShell('/projetos', { SidebarNav: NavWithLink })
    useWorkspaceStore().toggleNavigation()
    await shell.vm.$nextTick()

    await shell.get('.nav-link').trigger('click')
    expect(useWorkspaceStore().drawerOpen).toBe(false)
  })

  it('navegar por outro caminho (um job remoto abrindo o projeto, por exemplo) também a fecha', async () => {
    const shell = await mountShell('/projetos')
    useWorkspaceStore().toggleNavigation()
    await shell.vm.$nextTick()

    await shell.vm.$router.push('/editor/demo')
    await shell.vm.$nextTick()
    expect(useWorkspaceStore().drawerOpen).toBe(false)
  })

  it('tocar dentro da gaveta, fora de um link, não a fecha', async () => {
    const shell = await mountShell('/projetos', { SidebarNav: NavWithLink })
    useWorkspaceStore().toggleNavigation()
    await shell.vm.$nextTick()

    await shell.get('nav').trigger('click')
    expect(useWorkspaceStore().drawerOpen).toBe(true)
  })

  it('alargar a janela com a gaveta aberta a fecha, solta a rolagem e deixa o foco onde está', async () => {
    const toggle = document.createElement('button')
    toggle.id = 'navigation-toggle'
    document.body.append(toggle)
    const shell = await mountShell('/projetos')
    useWorkspaceStore().toggleNavigation()
    await shell.vm.$nextTick()

    media.set(false)
    await shell.vm.$nextTick()

    expect(useWorkspaceStore().narrow).toBe(false)
    expect(useWorkspaceStore().drawerOpen).toBe(false)
    expect(shell.classes()).not.toContain('shell--narrow')
    expect(document.documentElement.classList.contains('is-scroll-locked')).toBe(false)
    expect(document.activeElement).not.toBe(toggle)
    expect(shell.find('[aria-label="Largura da barra lateral"]').exists()).toBe(true)
  })

  it('estreitar a janela de uma tela larga põe a barra na gaveta, fechada', async () => {
    media.set(false)
    const shell = await mountShell('/projetos')
    expect(shell.classes()).not.toContain('shell--narrow')

    media.set(true)
    await shell.vm.$nextTick()
    expect(shell.classes()).toContain('shell--narrow')
    expect(shell.get('aside').element.hasAttribute('inert')).toBe(true)
  })

  it('ao desmontar com a gaveta aberta, devolve a rolagem da página e para de ouvir a janela', async () => {
    const shell = await mountShell('/projetos')
    useWorkspaceStore().toggleNavigation()
    await shell.vm.$nextTick()
    mounted.splice(mounted.indexOf(shell), 1)
    shell.unmount()

    expect(document.documentElement.classList.contains('is-scroll-locked')).toBe(false)
    expect(media.listenerCount()).toBe(0)
  })
})
