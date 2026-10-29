import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { useWorkspaceStore } from '@/stores/workspace'
import { reply, routedFetch } from '@/test/routedFetch'
import EditorProjectPicker from './EditorProjectPicker.vue'

beforeEach(() => window.localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

async function mountPicker(projects: unknown, lastProject?: string) {
  const pinia = createPinia()
  setActivePinia(pinia)
  if (lastProject) useWorkspaceStore().openProject(lastProject)
  routedFetch({ 'GET /api/projects': projects })
  const Blank = { render: () => null }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/editor/:name?', name: 'editor', component: Blank },
      { path: '/projetos', name: 'projects', component: Blank },
    ],
  })
  await router.push('/editor')
  const wrapper = mount(EditorProjectPicker, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return wrapper
}

describe('EditorProjectPicker', () => {
  it('lista os projetos, cada um levando ao editor dele', async () => {
    const wrapper = await mountPicker([
      { name: 'casamento', spec_path: 'x', preset: 'instagram/reels', brand: 'medlycare', segments: 4 },
      { name: 'aviso', spec_path: 'y', preset: 'instagram/stories', brand: null, segments: 1 },
    ])
    const links = wrapper.findAll('a.item')
    expect(links.map((link) => link.attributes('href'))).toEqual(['/editor/casamento', '/editor/aviso'])
    expect(links[0]?.text()).toContain('4 trechos')
    expect(links[1]?.text()).toContain('1 trecho')
    expect(links[1]?.text()).toContain('sem marca')
  })

  it('destaca o último projeto aberto com um botão para continuar', async () => {
    const wrapper = await mountPicker([{ name: 'casamento', spec_path: 'x', segments: 4 }], 'casamento')
    expect(wrapper.find('.resume').text()).toContain('casamento')
    expect(wrapper.find('.resume a').attributes('href')).toBe('/editor/casamento')
  })

  it('projeto com spec ilegível aparece e avisa que abre no editor para consertar', async () => {
    const wrapper = await mountPicker([{ name: 'quebrado', spec_path: 'x', error: 'spec inválida' }])
    expect(wrapper.find('a.item').text()).toContain('abre no editor para consertar')
  })

  it('sem projetos, manda criar um', async () => {
    const wrapper = await mountPicker([])
    expect(wrapper.text()).toContain('Nenhum projeto ainda')
  })

  it('erro de rede aparece no lugar da lista', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    routedFetch({ 'GET /api/projects': reply(500, { detail: 'servidor caiu' }) })
    const wrapper = mount(EditorProjectPicker, { global: { plugins: [pinia], stubs: { RouterLink: true } } })
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toBe('servidor caiu')
  })
})
