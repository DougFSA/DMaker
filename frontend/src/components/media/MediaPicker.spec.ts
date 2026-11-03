import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ProjectDetail } from '@/api'
import { useToastsStore } from '@/stores/toasts'
import { useWorkspaceStore } from '@/stores/workspace'
import MediaPicker, { type PickedMedia } from './MediaPicker.vue'

function detail(spec: Record<string, unknown>): ProjectDetail {
  return {
    name: 'demo',
    spec_path: 'X:/p/demo/spec.json',
    spec: { name: 'demo', ...spec },
    captions_exists: false,
    outputs: [],
    cuts: null,
  }
}

const absoluteSpec = {
  timeline: [
    { type: 'clip', src: 'D:/m/entrevista.mp4' },
    { type: 'image', src: 'D:/m/foto.png' },
  ],
  audio: { music: { src: 'D:/m/fundo.mp3' } },
}

interface Routes {
  project?: ProjectDetail | { detail: string }
  timeline?: unknown
  upload?: unknown
}

/** Responde a cada rota que o seletor usa e guarda o que foi chamado. */
function stubApi(routes: Routes): string[] {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string, init: RequestInit = {}) => {
      calls.push(`${init.method ?? 'GET'} ${url}`)
      const answer = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }))
      if (url.startsWith('/api/projects/') && url.endsWith('/timeline')) return answer(routes.timeline ?? { detail: 'sem fonte' }, routes.timeline ? 200 : 500)
      if (url.startsWith('/api/projects/')) {
        const project = routes.project ?? { detail: 'não existe' }
        return answer(project, 'detail' in project && typeof project.detail === 'string' ? 404 : 200)
      }
      if (url === '/api/speech/upload') return answer(routes.upload ?? { path: 'cache/uploads/abc-voz.wav', name: 'abc-voz.wav' })
      return answer({ detail: 'nada' }, 404)
    }),
  )
  return calls
}

let wrapper: VueWrapper
const picks = (): Array<PickedMedia | null> =>
  (wrapper.emitted('update:modelValue') ?? []).map(([value]) => value as PickedMedia | null)

function mountPicker(props: Record<string, unknown> = {}) {
  wrapper = mount(MediaPicker, { props: { modelValue: null, ...props } })
  return wrapper
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
})
afterEach(() => vi.unstubAllGlobals())

describe('MediaPicker', () => {
  it('lista os vídeos e áudios do projeto aberto (sem imagem) e já escolhe o primeiro', async () => {
    stubApi({ project: detail(absoluteSpec) })
    mountPicker({ project: 'demo' })
    await flushPromises()
    expect(wrapper.findAll('option').map((option) => option.text())).toEqual(['entrevista.mp4', 'fundo.mp3', 'Enviar um arquivo...'])
    expect(picks().at(-1)).toMatchObject({ path: 'D:/m/entrevista.mp4', name: 'entrevista.mp4', origin: 'project' })
    expect(picks().at(-1)?.entry).toMatchObject({ id: 'file:D:/m/entrevista.mp4', kind: 'clip' })
  })

  it('usa o projeto aberto no momento quando não recebe um', async () => {
    const calls = stubApi({ project: detail(absoluteSpec) })
    useWorkspaceStore().openProject('demo')
    mountPicker()
    await flushPromises()
    expect(calls).toContain('GET /api/projects/demo')
    expect(wrapper.text()).toContain('Mídia do projeto demo')
  })

  it('trocar a opção avisa o arquivo novo', async () => {
    stubApi({ project: detail(absoluteSpec) })
    mountPicker({ project: 'demo' })
    await flushPromises()
    await wrapper.find('select').setValue('project:1')
    expect(picks().at(-1)).toMatchObject({ path: 'D:/m/fundo.mp3', origin: 'project' })
  })

  it('não pede a vista quando todos os caminhos já são absolutos', async () => {
    const calls = stubApi({ project: detail(absoluteSpec) })
    mountPicker({ project: 'demo' })
    await flushPromises()
    expect(calls.some((call) => call.endsWith('/timeline'))).toBe(false)
  })

  it('caminho relativo é resolvido pela vista do servidor', async () => {
    const calls = stubApi({
      project: detail({ timeline: [{ type: 'clip', src: 'cap1.mp4' }] }),
      timeline: {
        total: 5,
        fps: 30,
        width: 1080,
        height: 1920,
        warnings: [],
        sources: {},
        tracks: [
          {
            id: 'V1',
            kind: 'video',
            label: 'V1',
            muted: false,
            hidden: false,
            locked: false,
            items: [{ id: 'V1-0', kind: 'clip', index: 0, label: 'cap1', start: 0, end: 5, in_point: 0, out_point: null, src: 'cap1.mp4', source: null, transition: null, muted: false, extra: {}, path: 'X:/projetos/demo/cap1.mp4' }],
          },
        ],
      },
    })
    mountPicker({ project: 'demo' })
    await flushPromises()
    expect(calls).toContain('POST /api/projects/demo/timeline')
    expect(picks().at(-1)).toMatchObject({ path: 'X:/projetos/demo/cap1.mp4', name: 'cap1.mp4' })
  })

  it('se a vista falha (fonte ausente), segue com o caminho da spec', async () => {
    stubApi({ project: detail({ timeline: [{ type: 'clip', src: 'cap1.mp4' }] }) })
    mountPicker({ project: 'demo' })
    await flushPromises()
    expect(picks().at(-1)).toMatchObject({ path: 'cap1.mp4' })
  })

  it('sem projeto, só oferece o envio e explica', async () => {
    stubApi({})
    mountPicker({ project: null })
    await flushPromises()
    expect(wrapper.findAll('option').map((option) => option.text())).toEqual(['Enviar um arquivo...'])
    expect(wrapper.text()).toContain('Abra um projeto')
    expect(wrapper.find('input[type="file"]').exists()).toBe(true)
    expect(picks().at(-1) ?? null).toBeNull()
  })

  it('projeto sem vídeo nem áudio diz isso e oferece o envio', async () => {
    stubApi({ project: detail({ timeline: [{ type: 'card' }] }) })
    mountPicker({ project: 'demo' })
    await flushPromises()
    expect(wrapper.text()).toContain('não tem vídeo nem áudio')
    expect(wrapper.find('input[type="file"]').exists()).toBe(true)
  })

  it('erro ao ler o projeto aparece na dica, sem derrubar o seletor', async () => {
    stubApi({ project: { detail: 'Projeto não encontrado' } })
    mountPicker({ project: 'sumiu' })
    await flushPromises()
    expect(wrapper.text()).toContain('Não consegui ler a mídia do projeto: Projeto não encontrado')
    expect(wrapper.findAll('option').map((option) => option.text())).toEqual(['Enviar um arquivo...'])
  })

  it('envia o arquivo, escolhe o enviado e avisa o caminho do servidor', async () => {
    const calls = stubApi({ project: detail(absoluteSpec) })
    mountPicker({ project: 'demo' })
    await flushPromises()
    await wrapper.find('select').setValue('upload')

    const input = wrapper.find('input[type="file"]')
    const file = new File(['abc'], 'voz.wav', { type: 'audio/wav' })
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()

    expect(calls).toContain('POST /api/speech/upload')
    expect(wrapper.findAll('option').map((option) => option.text())).toContain('Enviado: voz.wav')
    expect(picks().at(-1)).toEqual({ path: 'cache/uploads/abc-voz.wav', name: 'voz.wav', origin: 'upload', entry: null })
    expect((wrapper.find('select').element as HTMLSelectElement).value).toBe('uploaded')
    expect(wrapper.find('input[type="file"]').exists()).toBe(false)
  })

  it('recusa no envio o que não é áudio nem vídeo', async () => {
    const calls = stubApi({})
    mountPicker({ project: null })
    await flushPromises()
    const input = wrapper.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [new File(['x'], 'nota.pdf', { type: 'application/pdf' })], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(calls).not.toContain('POST /api/speech/upload')
    expect(wrapper.find('[role="alert"]').text()).toContain('nota.pdf')
  })

  it('falha no envio vira aviso e o seletor continua usável', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"detail":"Arquivo grande demais."}', { status: 413 })))
    const toasts = useToastsStore()
    mountPicker({ project: null })
    await flushPromises()
    const input = wrapper.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [new File(['x'], 'a.wav', { type: 'audio/wav' })], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(toasts.items[0]).toMatchObject({ tone: 'error', description: 'Arquivo grande demais.' })
    expect(picks().at(-1) ?? null).toBeNull()
    expect(wrapper.find('input[type="file"]').exists()).toBe(true)
  })

  describe('ao remontar (voltar à aba), devolve a escolha que a tela guardou', () => {
    it('um arquivo do projeto continua escolhido, sem avisar uma troca nem cair no primeiro', async () => {
      stubApi({ project: detail(absoluteSpec) })
      mountPicker({ project: 'demo' })
      await flushPromises()
      await wrapper.find('select').setValue('project:1')
      const kept = picks().at(-1)
      expect(kept).toMatchObject({ path: 'D:/m/fundo.mp3' })
      wrapper.unmount()

      mountPicker({ project: 'demo', modelValue: kept })
      await flushPromises()
      expect((wrapper.find('select').element as HTMLSelectElement).value).toBe('project:1')
      // nada mudou de verdade: a tela continua com o mesmo objeto
      expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    })

    it('enquanto a lista do projeto chega, não apaga a escolha guardada', async () => {
      stubApi({ project: detail(absoluteSpec) })
      mountPicker({ project: 'demo' })
      await flushPromises()
      await wrapper.find('select').setValue('project:1')
      const kept = picks().at(-1)
      wrapper.unmount()

      mountPicker({ project: 'demo', modelValue: kept })
      expect(picks()).toEqual([])
      await flushPromises()
      expect(picks()).toEqual([])
    })

    it('um arquivo enviado continua escolhido, com o nome e sem pedir o envio de novo', async () => {
      const calls = stubApi({})
      const sent: PickedMedia = { path: 'cache/uploads/abc-voz.wav', name: 'voz.wav', origin: 'upload', entry: null }
      mountPicker({ project: null, modelValue: sent })
      await flushPromises()
      expect(wrapper.findAll('option').map((option) => option.text())).toEqual(['Enviado: voz.wav', 'Enviar um arquivo...'])
      expect((wrapper.find('select').element as HTMLSelectElement).value).toBe('uploaded')
      expect(wrapper.find('input[type="file"]').exists()).toBe(false)
      expect(wrapper.emitted('update:modelValue')).toBeUndefined()
      expect(calls).toEqual([])
    })

    it('um arquivo que o projeto não usa mais cai na primeira mídia', async () => {
      stubApi({ project: detail(absoluteSpec) })
      const gone: PickedMedia = {
        path: 'D:/m/sumiu.mp4',
        name: 'sumiu.mp4',
        origin: 'project',
        entry: { id: 'file:D:/m/sumiu.mp4', kind: 'clip', label: 'sumiu.mp4', path: 'D:/m/sumiu.mp4', src: 'D:/m/sumiu.mp4' },
      }
      mountPicker({ project: 'demo', modelValue: gone })
      await flushPromises()
      expect((wrapper.find('select').element as HTMLSelectElement).value).toBe('project:0')
      expect(picks().at(-1)).toMatchObject({ path: 'D:/m/entrevista.mp4' })
    })

    it('sem projeto aberto, uma escolha do projeto vira "nenhuma" e oferece o envio', async () => {
      stubApi({})
      const old: PickedMedia = {
        path: 'D:/m/entrevista.mp4',
        name: 'entrevista.mp4',
        origin: 'project',
        entry: { id: 'file:D:/m/entrevista.mp4', kind: 'clip', label: 'entrevista.mp4', path: 'D:/m/entrevista.mp4', src: 'D:/m/entrevista.mp4' },
      }
      mountPicker({ project: null, modelValue: old })
      await flushPromises()
      expect(picks().at(-1) ?? null).toBeNull()
      expect(wrapper.find('input[type="file"]').exists()).toBe(true)
    })

    it('a escolha de uma fonte sincronizada sobrevive a trocar o arquivo dela (mesmo id)', async () => {
      stubApi({ project: detail({ sources: { cam1: { src: 'D:/m/cam1.mp4' } }, timeline: [{ type: 'clip', src: 'D:/m/outro.mp4' }] }) })
      mountPicker({ project: 'demo' })
      await flushPromises()
      await wrapper.find('select').setValue('project:0')
      const kept = picks().at(-1)
      expect(kept?.entry?.id).toBe('source:cam1')
      wrapper.unmount()

      stubApi({ project: detail({ sources: { cam1: { src: 'D:/m/cam1.en.mp4' } }, timeline: [{ type: 'clip', src: 'D:/m/outro.mp4' }] }) })
      mountPicker({ project: 'demo', modelValue: kept })
      await flushPromises()
      expect((wrapper.find('select').element as HTMLSelectElement).value).toBe('project:0')
      expect(picks().at(-1)).toMatchObject({ path: 'D:/m/cam1.en.mp4' })
    })
  })

  it('usa o rótulo pedido', async () => {
    stubApi({})
    mountPicker({ project: null, label: 'Arquivo para isolar' })
    await flushPromises()
    expect(wrapper.find('label').text()).toBe('Arquivo para isolar')
  })
})
