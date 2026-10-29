import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MediaEntry } from '@/lib/media'
import { useToastsStore } from '@/stores/toasts'
import UseInProject from './UseInProject.vue'

const entry: MediaEntry = { id: 'file:D:/m/a.mp4', kind: 'clip', label: 'a.mp4', path: 'D:/m/a.mp4', src: 'D:/m/a.mp4' }
const spec = { name: 'demo', timeline: [{ type: 'clip', src: 'D:/m/a.mp4' }] }

type Reply = { body: unknown; status?: number }

function stubServer(routes: { get?: Reply; edit?: Reply; put?: Reply } = {}): string[] {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET'
      calls.push(`${method} ${url}`)
      const pick = (reply: Reply | undefined, fallback: unknown) =>
        Promise.resolve(new Response(JSON.stringify(reply?.body ?? fallback), { status: reply?.status ?? 200 }))
      if (method === 'GET') return pick(routes.get, { name: 'demo', spec_path: 'p', spec, captions_exists: false, outputs: [], cuts: null })
      if (url.endsWith('/edit')) return pick(routes.edit, { spec: { ...spec, timeline: [{ type: 'clip', src: 'novo.mp4' }] }, timeline: {} })
      return pick(routes.put, { ok: true, spec_path: 'p' })
    }),
  )
  return calls
}

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

const props = { project: 'demo', entry, newPath: 'novo.mp4', what: 'arquivo corrigido' }

describe('UseInProject', () => {
  it('troca o arquivo no projeto, salva e conta em quantos pontos', async () => {
    const calls = stubServer()
    const toasts = useToastsStore()
    const wrapper = mount(UseInProject, { props })

    await wrapper.find('button').trigger('click')
    await flushPromises()

    expect(calls).toEqual(['GET /api/projects/demo', 'POST /api/projects/demo/edit', 'PUT /api/projects/demo'])
    expect(wrapper.text()).toContain('Projeto demo atualizado: arquivo corrigido em 1 ponto(s).')
    expect(wrapper.emitted('used')).toEqual([[1]])
    expect(toasts.items[0]).toMatchObject({ tone: 'success', title: 'Projeto atualizado' })
  })

  it('depois de usar o botão desliga, e um resultado novo o liga de novo', async () => {
    stubServer()
    const wrapper = mount(UseInProject, { props })

    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(wrapper.find('button').attributes('disabled')).toBeDefined()

    await wrapper.setProps({ newPath: 'outro.mp4' })
    expect(wrapper.find('button').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('.use__note').exists()).toBe(false)
  })

  it('sem projeto ou sem entrada (arquivo enviado) o botão fica desligado e explica', () => {
    const upload = mount(UseInProject, { props: { ...props, project: null, entry: null } })
    expect(upload.find('button').attributes('disabled')).toBeDefined()
    expect(upload.text()).toContain('escolha um arquivo do projeto aberto')
  })

  it('o motivo que a tela passa (trecho, não o arquivo inteiro) tem prioridade', () => {
    const wrapper = mount(UseInProject, { props: { ...props, blockedReason: 'Só o arquivo inteiro pode entrar no projeto.' } })
    expect(wrapper.find('button').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('Só o arquivo inteiro pode entrar no projeto.')
  })

  it('projeto que não usa o arquivo avisa e não salva', async () => {
    const calls = stubServer({ get: { body: { name: 'demo', spec_path: 'p', spec: { name: 'demo', timeline: [] }, captions_exists: false, outputs: [], cuts: null } } })
    const toasts = useToastsStore()
    const wrapper = mount(UseInProject, { props })

    await wrapper.find('button').trigger('click')
    await flushPromises()

    expect(calls).toEqual(['GET /api/projects/demo'])
    expect(wrapper.text()).toContain('Nenhum trecho do projeto usa este arquivo.')
    expect(wrapper.emitted('used')).toBeUndefined()
    expect(toasts.items[0]).toMatchObject({ tone: 'error' })
  })

  it('spec que o servidor recusa vira aviso de erro e o botão volta a funcionar', async () => {
    stubServer({ put: { body: { detail: 'Spec inválida.' }, status: 422 } })
    const toasts = useToastsStore()
    const wrapper = mount(UseInProject, { props })

    await wrapper.find('button').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Não consegui usar no projeto: Spec inválida.')
    expect(toasts.items[0]).toMatchObject({ tone: 'error', description: 'Spec inválida.' })
    expect(wrapper.find('button').attributes('disabled')).toBeUndefined()
    expect(wrapper.emitted('used')).toBeUndefined()
  })
})
