import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import type { TimelineView } from '@/api'
import { provideEditorFilePicker } from '@/composables/useEditorFilePicker'
import { useEditorShortcuts } from '@/composables/useEditorShortcuts'
import { MEDIA_DND_MIME } from '@/lib/timeline'
import { useKeymapStore } from '@/stores/keymap'
import { useTimelineStore } from '@/stores/timeline'
import { useToastsStore } from '@/stores/toasts'
import { mountEditorPart, openEditor, type OpenedEditor } from '@/test/editorMount'
import { timelineItem, timelineTrack } from '@/test/editorFixtures'
import MediaPanel from './MediaPanel.vue'

beforeEach(() => window.localStorage.clear())
afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

function mediaSpec(): Record<string, unknown> {
  return {
    name: 'demo',
    version: 1,
    output: { preset: 'instagram/reels' },
    sources: { cam1: { src: 'C:/m/cam1.mp4', sync: 0 } },
    timeline: [
      { type: 'clip', src: 'C:/m/a.mp4' },
      { type: 'clip', source: 'cam1' },
      { type: 'image', src: 'C:/m/foto.png' },
      { type: 'clip', src: 'relativo.mp4' },
    ],
    overlays: [
      { type: 'image', src: 'logo' },
      { type: 'video', src: 'C:/m/pip.mp4' },
    ],
    audio: { music: { src: 'C:/m/trilha.mp3', volume: 0.3 } },
  }
}

function mediaView(): TimelineView {
  return {
    total: 12,
    fps: 30,
    width: 1080,
    height: 1920,
    tracks: [
      timelineTrack('V1', [0, 1, 2, 3].map((index) => timelineItem(index, { id: `V1-${index}` }))),
      timelineTrack('V2', [timelineItem(1, { id: 'V2-1', kind: 'video' })]),
    ],
    sources: {},
    warnings: [],
  }
}

const DURATIONS: Record<string, number> = { 'C:/m/cam1.mp4': 83, 'C:/m/a.mp4': 12.34, 'C:/m/pip.mp4': 5, 'C:/m/trilha.mp3': 150 }

interface Mounted {
  opened: OpenedEditor
  wrapper: VueWrapper
  edits: () => Array<{ op: Record<string, unknown> }>
}

/** Abre o projeto de mídia e monta o painel; as rotas de sondagem e de edição respondem como o servidor. */
async function mountMedia(extraRoutes: Record<string, unknown> = {}, attach = true): Promise<Mounted> {
  const opened = await openEditor(mediaSpec(), {
    'POST /api/projects/demo/timeline': () => mediaView(),
    'POST /api/probe': (call: { body: { paths: string[] } }) =>
      call.body.paths.map((path) =>
        path in DURATIONS
          ? { path, url: null, kind: 'video', width: 1920, height: 1080, duration_s: DURATIONS[path], fps: 30, has_audio: true, orientation: 'landscape' }
          : { path, error: 'não encontrado' },
      ),
    'POST /api/projects/demo/edit': () => ({ spec: mediaSpec(), timeline: mediaView() }),
    ...extraRoutes,
  })
  const wrapper = await mountEditorPart(MediaPanel, opened, {}, attach)
  return { opened, wrapper, edits: () => opened.fetch.to('POST /api/projects/demo/edit').map((call) => call.body as { op: Record<string, unknown> }) }
}

const items = (wrapper: VueWrapper) => wrapper.findAll('[data-media-id]')
const names = (wrapper: VueWrapper) => items(wrapper).map((item) => item.find('.item__name').text())
const buttonLabelled = (wrapper: VueWrapper, label: string) => wrapper.findAll('button').find((button) => button.text() === label)!

describe('MediaPanel: a lista', () => {
  it('lista as fontes sincronizadas e os arquivos que o projeto usa, sem repetir e sem o logo da marca', async () => {
    const { wrapper } = await mountMedia()
    expect(names(wrapper)).toEqual(['cam1', 'a.mp4', 'foto.png', 'relativo.mp4', 'pip.mp4', 'trilha.mp3'])
  })

  it('cada item diz se é vídeo, imagem ou áudio e, depois da sondagem, quanto dura', async () => {
    const { wrapper } = await mountMedia()
    const meta = items(wrapper).map((item) => item.find('.item__meta').text())
    expect(meta).toEqual([
      'vídeo · 1:23', // 83 s
      'vídeo · 12,3 s',
      'imagem',
      'vídeo',
      'vídeo · 5,0 s',
      'áudio · 2:30',
    ])
  })

  it('sonda uma vez só os arquivos de vídeo e de áudio de caminho absoluto, e não repete ao remontar', async () => {
    const { opened, wrapper } = await mountMedia()
    const probes = opened.fetch.to('POST /api/probe')
    expect(probes).toHaveLength(1)
    expect(probes[0]?.body).toEqual({ paths: ['C:/m/cam1.mp4', 'C:/m/a.mp4', 'C:/m/pip.mp4', 'C:/m/trilha.mp3'] })
    wrapper.unmount()
    await mountEditorPart(MediaPanel, opened, {}, true)
    expect(opened.fetch.to('POST /api/probe')).toHaveLength(1)
  })

  it('arquivo que o servidor não mede fica sem duração, sem quebrar a lista', async () => {
    const { wrapper } = await mountMedia({ 'POST /api/probe': (call: { body: { paths: string[] } }) => call.body.paths.map((path) => ({ path, error: 'x' })) })
    expect(items(wrapper).map((item) => item.find('.item__meta').text())).toEqual(['vídeo', 'vídeo', 'imagem', 'vídeo', 'vídeo', 'áudio'])
  })

  it('o arquivo que a vista marcou como ausente aparece marcado', async () => {
    const view = mediaView()
    view.tracks[0]!.items[1]!.src = 'C:/m/a.mp4'
    view.tracks[0]!.items[1]!.missing = true
    view.tracks[0]!.items[1]!.path = 'C:/m/a.mp4'
    const { wrapper } = await mountMedia({ 'POST /api/projects/demo/timeline': () => view })
    const a = items(wrapper).find((item) => item.attributes('data-media-id') === 'file:C:/m/a.mp4')!
    expect(a.find('.item__meta').text()).toContain('não encontrado')
    expect(a.classes()).toContain('item--missing')
  })

  it('clicar seleciona um item de cada vez', async () => {
    const { wrapper } = await mountMedia()
    await items(wrapper)[1]!.trigger('click')
    expect(items(wrapper).map((item) => item.attributes('aria-pressed'))).toEqual(['false', 'true', 'false', 'false', 'false', 'false'])
    await items(wrapper)[2]!.trigger('click')
    expect(items(wrapper).filter((item) => item.attributes('aria-pressed') === 'true')).toHaveLength(1)
  })

  it('o item que saiu do projeto deixa de estar selecionado', async () => {
    const { opened, wrapper } = await mountMedia()
    await items(wrapper)[2]!.trigger('click')
    opened.store.mutate((spec) => {
      ;(spec.timeline as unknown[]).splice(2, 1)
    })
    await flushPromises()
    expect(items(wrapper).filter((item) => item.attributes('aria-pressed') === 'true')).toHaveLength(0)
  })

  it('projeto sem mídia mostra a dica dos botões', async () => {
    const opened = await openEditor({ name: 'demo', timeline: [{ type: 'card', title: 'x' }], overlays: [] })
    const wrapper = await mountEditorPart(MediaPanel, opened, {}, true)
    expect(wrapper.text()).toContain('Nenhum arquivo ainda')
  })

  it('sem projeto aberto avisa e não oferece nada', async () => {
    const opened = await openEditor()
    opened.store.close()
    const wrapper = await mountEditorPart(MediaPanel, opened, {}, true)
    expect(wrapper.text()).toContain('Sem projeto aberto')
    expect(wrapper.find('[data-media-id]').exists()).toBe(false)
  })
})

describe('MediaPanel: acrescentar ao fim da V1', () => {
  it('o duplo clique acrescenta o item no fim da V1', async () => {
    const { wrapper, edits } = await mountMedia()
    await items(wrapper)[0]!.trigger('dblclick')
    await flushPromises()
    expect(edits()[0]?.op).toEqual({
      type: 'insert',
      index: 4,
      segment: { type: 'clip', start: 0, speed: 1, volume: 1, mute: false, source: 'cam1' },
    })
  })

  it('imagem entra como trecho de imagem com movimento', async () => {
    const { wrapper, edits } = await mountMedia()
    await items(wrapper)[2]!.trigger('dblclick')
    await flushPromises()
    expect(edits()[0]?.op).toMatchObject({ type: 'insert', segment: { type: 'image', src: 'C:/m/foto.png', duration: 3 } })
  })

  it('áudio não entra na V1: um aviso manda para o botão Música', async () => {
    const { wrapper, edits } = await mountMedia()
    await items(wrapper)[5]!.trigger('dblclick')
    await flushPromises()
    expect(edits()).toHaveLength(0)
    expect(useToastsStore().items.map((toast) => toast.title)).toContain('Arquivos de áudio entram pelo botão "Música", não na V1.')
  })

  it('Enter no item acrescenta; as setas andam pela lista', async () => {
    const { wrapper, edits } = await mountMedia()
    await items(wrapper)[0]!.trigger('keydown', { key: 'ArrowDown' })
    expect(document.activeElement).toBe(items(wrapper)[1]!.element)
    await items(wrapper)[1]!.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(edits()[0]?.op).toMatchObject({ type: 'insert', index: 4 })
    expect(items(wrapper)[1]!.attributes('aria-pressed')).toBe('true')
  })
})

describe('MediaPanel: as teclas A e V', () => {
  it('o painel registra o A e o V enquanto está na tela, e solta ao sair', async () => {
    const { opened, wrapper } = await mountMedia()
    const keymap = useKeymapStore()
    expect(keymap.registered.has('media_append')).toBe(true)
    expect(keymap.registered.has('media_insert')).toBe(true)
    wrapper.unmount()
    expect(keymap.registered.has('media_append')).toBe(false)
    expect(opened.store.name).toBe('demo')
  })

  it('A acrescenta o item selecionado no fim da V1', async () => {
    const { wrapper, edits } = await mountMedia()
    await items(wrapper)[0]!.trigger('click')
    useKeymapStore().registered.get('media_append')!(new KeyboardEvent('keydown', { key: 'a' }))
    await flushPromises()
    expect(edits()[0]?.op).toMatchObject({ type: 'insert', index: 4, segment: { source: 'cam1' } })
  })

  it('V insere o item selecionado na posição do cursor', async () => {
    const { opened, wrapper, edits } = await mountMedia()
    await items(wrapper)[1]!.trigger('click')
    opened.store.setPlayhead(4)
    useKeymapStore().registered.get('media_insert')!(new KeyboardEvent('keydown', { key: 'v' }))
    await flushPromises()
    expect(edits()[0]?.op).toMatchObject({ type: 'insert', index: 2, segment: { src: 'C:/m/a.mp4' } })
  })

  it('com o foco no item da lista, o teclado do editor deixa o A e o V passarem (a lista não é uma listbox que cala as teclas)', async () => {
    const opened = await openEditor(mediaSpec(), {
      'POST /api/projects/demo/timeline': () => mediaView(),
      'POST /api/probe': [],
      'POST /api/projects/demo/edit': () => ({ spec: mediaSpec(), timeline: mediaView() }),
    })
    // a tela do editor liga o teclado uma vez; aqui o anfitrião faz o mesmo, em volta do painel
    const Host = defineComponent({
      setup() {
        useEditorShortcuts()
        return () => h(MediaPanel)
      },
    })
    const wrapper = mount(Host, { global: { plugins: [opened.pinia] }, attachTo: document.body })
    await flushPromises()
    const edits = () => opened.fetch.to('POST /api/projects/demo/edit').map((call) => (call.body as { op: Record<string, unknown> }).op)
    const item = wrapper.findAll('[data-media-id]')[1]!
    await item.trigger('click')
    ;(item.element as HTMLElement).focus()
    item.element.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true, cancelable: true }))
    await flushPromises()
    expect(edits()[0]).toMatchObject({ type: 'insert', index: 4, segment: { src: 'C:/m/a.mp4' } })
    opened.store.setPlayhead(4)
    item.element.dispatchEvent(new KeyboardEvent('keydown', { key: 'v', bubbles: true, cancelable: true }))
    await flushPromises()
    expect(edits()[1]).toMatchObject({ type: 'insert', index: 2, segment: { src: 'C:/m/a.mp4' } })
    wrapper.unmount()
  })

  it('sem item selecionado, A e V pedem para escolher um arquivo no painel', async () => {
    const { wrapper, edits } = await mountMedia()
    expect(wrapper.exists()).toBe(true)
    useKeymapStore().registered.get('media_append')!(new KeyboardEvent('keydown', { key: 'a' }))
    useKeymapStore().registered.get('media_insert')!(new KeyboardEvent('keydown', { key: 'v' }))
    await flushPromises()
    expect(edits()).toHaveLength(0)
    expect(useToastsStore().items.filter((toast) => toast.title === 'Selecione um arquivo no painel de mídia.')).toHaveLength(2)
  })
})

describe('MediaPanel: arrastar e soltar', () => {
  it('arrastar leva a entrada no tipo de dado da linha do tempo', async () => {
    const { wrapper } = await mountMedia()
    const setData = vi.fn()
    const dataTransfer = { setData, effectAllowed: '' }
    await items(wrapper)[0]!.trigger('dragstart', { dataTransfer })
    expect(dataTransfer.effectAllowed).toBe('copy')
    expect(setData).toHaveBeenCalledTimes(1)
    expect(setData.mock.calls[0]?.[0]).toBe(MEDIA_DND_MIME)
    expect(JSON.parse(setData.mock.calls[0]?.[1] as string)).toMatchObject({ id: 'source:cam1', kind: 'clip', source: 'cam1' })
  })

  it('o item é arrastável', async () => {
    const { wrapper } = await mountMedia()
    expect(items(wrapper).every((item) => item.attributes('draggable') === 'true')).toBe(true)
  })

  it('soltar na V1 insere no ponto; o painel é quem trata a soltura da linha do tempo', async () => {
    const { wrapper, edits } = await mountMedia()
    const payload = JSON.stringify({ id: 'file:C:/m/a.mp4', kind: 'clip', label: 'a.mp4', path: 'C:/m/a.mp4', src: 'C:/m/a.mp4' })
    const handler = useTimelineStore().mediaDropHandler
    expect(handler).not.toBeNull()
    handler!(payload, { trackId: 'V1', time: 7 })
    await flushPromises()
    expect(edits()[0]?.op).toMatchObject({ type: 'insert', index: 3, segment: { src: 'C:/m/a.mp4' } })
    expect(wrapper.exists()).toBe(true)
  })

  it('soltar em outra trilha cria um PiP, e uma imagem vira imagem sobreposta', async () => {
    const { wrapper, edits } = await mountMedia()
    const handler = useTimelineStore().mediaDropHandler!
    handler(JSON.stringify({ id: 'source:cam1', kind: 'clip', label: 'cam1', path: 'C:/m/cam1.mp4', source: 'cam1' }), { trackId: 'V2', time: 2 })
    await flushPromises()
    const first = edits()[0]?.op as { type: string; path: string; value: Array<Record<string, unknown>> }
    expect(first).toMatchObject({ type: 'set_field', path: 'overlays' })
    expect(first.value).toHaveLength(3) // o logo e o PiP que o projeto já tinha, mais o novo
    expect(first.value[2]).toMatchObject({ type: 'video', source: 'cam1', start: 2, end: 5 })

    handler(JSON.stringify({ id: 'file:C:/m/foto.png', kind: 'image', label: 'foto.png', path: 'C:/m/foto.png', src: 'C:/m/foto.png' }), { trackId: 'GR', time: 1 })
    await flushPromises()
    const second = edits()[1]?.op as { value: Array<Record<string, unknown>> }
    expect(second.value[2]).toMatchObject({ type: 'image', src: 'C:/m/foto.png', start: 1 })
    expect(wrapper.exists()).toBe(true)
  })

  it('o que não é uma entrada de mídia não faz nada, e soltar fora das trilhas avisa', async () => {
    const { edits } = await mountMedia()
    const handler = useTimelineStore().mediaDropHandler!
    handler('qualquer coisa', { trackId: 'V1', time: 1 })
    handler(JSON.stringify({ id: 'file:C:/m/a.mp4', kind: 'clip', label: 'a', path: 'C:/m/a.mp4', src: 'C:/m/a.mp4' }), { trackId: null, time: 1 })
    await flushPromises()
    expect(edits()).toHaveLength(0)
    expect(useToastsStore().items.map((toast) => toast.title)).toContain('Solte o arquivo sobre uma trilha da linha do tempo.')
  })

  it('ao sair, o painel deixa de tratar a soltura', async () => {
    const { wrapper } = await mountMedia()
    wrapper.unmount()
    expect(useTimelineStore().mediaDropHandler).toBeNull()
  })
})

describe('MediaPanel: os botões', () => {
  it('Texto põe uma linha de texto no cursor', async () => {
    const { opened, wrapper, edits } = await mountMedia()
    opened.store.setPlayhead(2)
    await buttonLabelled(wrapper, 'Texto').trigger('click')
    await flushPromises()
    const op = edits()[0]?.op as { path: string; value: Array<Record<string, unknown>> }
    expect(op.path).toBe('overlays')
    expect(op.value.at(-1)).toEqual({ type: 'text', text: 'Novo texto', role: 'title', start: 2, end: 5 })
  })

  it('Logo põe o logo da marca no cursor', async () => {
    const { wrapper, edits } = await mountMedia()
    await buttonLabelled(wrapper, 'Logo').trigger('click')
    await flushPromises()
    const op = edits()[0]?.op as { value: Array<Record<string, unknown>> }
    expect(op.value.at(-1)).toMatchObject({ type: 'image', src: 'logo', position: 'top-right', start: 0 })
  })

  it('Cartão insere um cartão no fim da V1', async () => {
    const { wrapper, edits } = await mountMedia()
    await buttonLabelled(wrapper, 'Cartão').trigger('click')
    await flushPromises()
    expect(edits()[0]?.op).toMatchObject({ type: 'insert', index: 4, segment: { type: 'card', title: 'Novo cartão' } })
  })

  it('cada botão vale um passo só do desfazer', async () => {
    const { opened, wrapper } = await mountMedia()
    expect(opened.store.canUndo).toBe(false)
    await buttonLabelled(wrapper, 'Cartão').trigger('click')
    await flushPromises()
    expect(opened.store.canUndo).toBe(true)
  })

  it('sem o navegador de arquivos da tela do editor, + Arquivo e Música ficam desligados', async () => {
    const { wrapper } = await mountMedia()
    expect(buttonLabelled(wrapper, '+ Arquivo').attributes('disabled')).toBeDefined()
    expect(buttonLabelled(wrapper, 'Música').attributes('disabled')).toBeDefined()
    expect(buttonLabelled(wrapper, 'Texto').attributes('disabled')).toBeUndefined()
  })
})

describe('MediaPanel: + Arquivo e Música (com o navegador de arquivos da tela)', () => {
  /** Monta o painel dentro de um anfitrião que provê o seletor, e devolve como responder ao diálogo. */
  async function mountWithPicker() {
    const opened = await openEditor(mediaSpec(), {
      'POST /api/projects/demo/timeline': () => mediaView(),
      'POST /api/probe': [],
      'POST /api/projects/demo/edit': () => ({ spec: mediaSpec(), timeline: mediaView() }),
    })
    let answer: (paths: string[]) => void = () => undefined
    const Host = defineComponent({
      setup() {
        const picker = provideEditorFilePicker()
        answer = picker.onSelect
        return () => h(MediaPanel)
      },
    })
    const wrapper = mount(Host, { global: { plugins: [opened.pinia] }, attachTo: document.body })
    await flushPromises()
    const edits = () => opened.fetch.to('POST /api/projects/demo/edit').map((call) => (call.body as { op: Record<string, unknown> }).op)
    return { opened, wrapper, edits, answer: (paths: string[]) => answer(paths) }
  }

  it('um vídeo escolhido entra no fim da V1', async () => {
    const { wrapper, edits, answer } = await mountWithPicker()
    await buttonLabelled(wrapper, '+ Arquivo').trigger('click')
    answer(['C:/novo/video.mov'])
    await flushPromises()
    expect(edits()[0]).toMatchObject({ type: 'insert', index: 4, segment: { type: 'clip', src: 'C:/novo/video.mov' } })
  })

  it('uma imagem escolhida entra como trecho de imagem', async () => {
    const { wrapper, edits, answer } = await mountWithPicker()
    await buttonLabelled(wrapper, '+ Arquivo').trigger('click')
    answer(['C:/novo/foto.jpg'])
    await flushPromises()
    expect(edits()[0]).toMatchObject({ type: 'insert', segment: { type: 'image', src: 'C:/novo/foto.jpg' } })
  })

  it('um áudio escolhido em + Arquivo vira a música, mantendo o volume e os ajustes dela', async () => {
    const { wrapper, edits, answer } = await mountWithPicker()
    await buttonLabelled(wrapper, '+ Arquivo').trigger('click')
    answer(['C:/novo/faixa.wav'])
    await flushPromises()
    expect(edits()[0]).toEqual({ type: 'set_field', path: 'audio.music.src', value: 'C:/novo/faixa.wav' })
  })

  it('Música troca a música do projeto', async () => {
    const { wrapper, edits, answer } = await mountWithPicker()
    await buttonLabelled(wrapper, 'Música').trigger('click')
    answer(['C:/novo/outra.mp3'])
    await flushPromises()
    expect(edits()[0]).toEqual({ type: 'set_field', path: 'audio.music.src', value: 'C:/novo/outra.mp3' })
  })

  it('cancelar o navegador de arquivos não muda nada', async () => {
    const { wrapper, edits, answer } = await mountWithPicker()
    await buttonLabelled(wrapper, '+ Arquivo').trigger('click')
    answer([])
    await flushPromises()
    expect(edits()).toHaveLength(0)
  })
})
