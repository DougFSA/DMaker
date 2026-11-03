import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { EDITING_AREAS } from '@/lib/editorLayout'
import { useConfirmStore } from '@/stores/confirm'
import { useScreenLayoutStore } from '@/stores/screenLayout'
import { routedFetch, type RoutedFetch } from '@/test/routedFetch'
import ScreenLayoutPicker from './ScreenLayoutPicker.vue'

const mine = { version: 1, areas: { ...EDITING_AREAS }, sizes: { 'col-left': 333 }, hidden: ['progress', 'filters'] }

let wrapper: VueWrapper
let router: Router
let server: RoutedFetch

async function mountPicker(): Promise<void> {
  const pinia = createPinia()
  setActivePinia(pinia)
  const blank = { render: () => null }
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/editor/:name?', name: 'editor', component: blank },
      { path: '/voz', name: 'voice', component: blank },
    ],
  })
  await router.push('/editor/demo')
  wrapper = mount(ScreenLayoutPicker, { global: { plugins: [pinia, router] }, attachTo: document.body })
  await flushPromises()
}

beforeEach(() => {
  localStorage.clear()
  server = routedFetch({
    'GET /api/layouts': { layouts: { 'Meu layout': mine } },
    'PUT /api/layouts/Foco': { ok: true },
    'DELETE /api/layouts/Meu%20layout': { ok: true },
  })
})
afterEach(() => {
  wrapper.unmount()
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

const trigger = () => wrapper.get('[aria-label="Layout da tela"]')
const menuItem = (name: string) => document.body.querySelector<HTMLElement>(`[data-layout="${name}"]`)
const button = (label: string) => [...document.body.querySelectorAll('button')].find((node) => node.textContent?.trim() === label)

async function openMenu(): Promise<void> {
  await trigger().trigger('click')
  await flushPromises()
}

describe('ScreenLayoutPicker', () => {
  it('o botão diz o layout em uso, e "alterado" quando a pessoa mexeu depois de escolher', async () => {
    await mountPicker()
    expect(trigger().text()).toBe('Tela: Edição')
    useScreenLayoutStore().swap('player', 'timeline')
    await flushPromises()
    expect(trigger().text()).toBe('Tela: Edição (alterado)')
  })

  it('lista os seis embutidos e os que a pessoa salvou, marcando o atual', async () => {
    await mountPicker()
    await openMenu()
    const names = [...document.body.querySelectorAll('[data-layout]')].map((node) => node.getAttribute('data-layout'))
    expect(names).toEqual(['Edição', 'Efeitos', 'Áudio', 'Player', 'Revisão', 'Voz', 'Meu layout'])
    expect(menuItem('Edição')!.getAttribute('aria-current')).toBe('true')
    expect(menuItem('Efeitos')!.getAttribute('aria-current')).toBeNull()
  })

  it('escolher um layout aplica e fecha o menu', async () => {
    await mountPicker()
    await openMenu()
    menuItem('Efeitos')!.click()
    await flushPromises()
    const layouts = useScreenLayoutStore()
    expect(layouts.name).toBe('Efeitos')
    expect(layouts.isHidden('media')).toBe(true)
    expect(document.body.querySelector('[data-layout]')).toBeNull()
    expect(router.currentRoute.value.name).toBe('editor')
  })

  it('escolher um salvo aplica o que ele guardou', async () => {
    await mountPicker()
    await openMenu()
    menuItem('Meu layout')!.click()
    await flushPromises()
    const layouts = useScreenLayoutStore()
    expect(layouts.layout.sizes['col-left']).toBe(333)
    expect(layouts.isHidden('filters')).toBe(true)
  })

  it('o layout Voz leva ao estúdio de voz, a aba que ele abre', async () => {
    await mountPicker()
    await openMenu()
    menuItem('Voz')!.click()
    await flushPromises()
    expect(useScreenLayoutStore().name).toBe('Voz')
    expect(router.currentRoute.value.name).toBe('voice')
  })

  it('os painéis da tela se mostram e se ocultam por caixas de marcar', async () => {
    await mountPicker()
    await openMenu()
    const boxes = [...document.body.querySelectorAll<HTMLInputElement>('.layout-menu__panels input[type="checkbox"]')]
    expect(boxes).toHaveLength(4)
    expect(boxes.every((box) => box.checked)).toBe(true)
    const mediaBox = boxes.find((box) => box.closest('label')?.textContent?.includes('Mídia'))!
    mediaBox.click()
    await flushPromises()
    expect(useScreenLayoutStore().isHidden('media')).toBe(true)
  })

  it('Salvar layout como pede o nome e grava o layout de agora no servidor', async () => {
    await mountPicker()
    useScreenLayoutStore().setSize('col-right', 300)
    await openMenu()
    button('Salvar layout como...')!.click()
    await flushPromises()

    const input = document.body.querySelector<HTMLInputElement>('#save-layout-form input')!
    expect(input.value).toBe('')
    input.value = 'Foco'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    await flushPromises()
    document.body.querySelector<HTMLFormElement>('#save-layout-form')!.dispatchEvent(new Event('submit', { cancelable: true }))
    await flushPromises()

    const sent = server.to('PUT /api/layouts/Foco')[0]!.body as { sizes: Record<string, number> }
    expect(sent.sizes['col-right']).toBe(300)
    expect(useScreenLayoutStore().name).toBe('Foco')
    expect(document.body.querySelector('#save-layout-form')).toBeNull()
  })

  it('o diálogo de salvar não deixa salvar com o nome em branco', async () => {
    await mountPicker()
    await openMenu()
    button('Salvar layout como...')!.click()
    await flushPromises()
    expect(button('Salvar')!.hasAttribute('disabled')).toBe(true)
  })

  it('Excluir layout atual fica desligado nos embutidos e, nos salvos, pergunta antes', async () => {
    await mountPicker()
    await openMenu()
    expect(button('Excluir layout atual')!.hasAttribute('disabled')).toBe(true)

    menuItem('Meu layout')!.click()
    await flushPromises()
    await openMenu()
    expect(button('Excluir layout atual')!.hasAttribute('disabled')).toBe(false)
    button('Excluir layout atual')!.click()
    await flushPromises()
    expect(useConfirmStore().current?.options.title).toContain('Meu layout')
    server.set('GET /api/layouts', { layouts: {} })
    useConfirmStore().answer(true)
    await flushPromises()
    expect(server.to('DELETE /api/layouts/Meu%20layout')).toHaveLength(1)
    expect(useScreenLayoutStore().name).toBe('Edição')
  })

  it('Restaurar padrão volta ao Edição', async () => {
    await mountPicker()
    const layouts = useScreenLayoutStore()
    layouts.choose('Revisão')
    layouts.swap('player', 'media')
    await openMenu()
    button('Restaurar padrão')!.click()
    await flushPromises()
    expect(layouts.name).toBe('Edição')
    expect(layouts.modified).toBe(false)
  })
})
