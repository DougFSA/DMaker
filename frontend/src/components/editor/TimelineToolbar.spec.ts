import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { projectSpec, timelineView } from '@/test/editorFixtures'
import { mountEditorPart, openEditor, type OpenedEditor } from '@/test/editorMount'
import { useEditorPanelsStore } from '@/stores/editorPanels'
import { useKeymapStore } from '@/stores/keymap'
import { useTimelineStore } from '@/stores/timeline'
import { useToastsStore } from '@/stores/toasts'
import TimelineToolbar from './TimelineToolbar.vue'

let wrapper: VueWrapper | null = null
let opened: OpenedEditor

async function mountToolbar() {
  const view = timelineView() // dois trechos de 3 s
  opened = await openEditor(projectSpec(), {
    'POST /api/projects/demo/timeline': () => view,
    'POST /api/projects/demo/edit': () => ({ spec: projectSpec(), timeline: view }),
  })
  wrapper = await mountEditorPart(TimelineToolbar, opened)
  return wrapper
}

const button = (label: string) =>
  (wrapper as VueWrapper).findAll('button').find((candidate) => candidate.text() === label || candidate.attributes('aria-label') === label)
const edits = () => opened.fetch.to('POST /api/projects/demo/edit')

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

describe('a barra de ferramentas da linha do tempo', () => {
  it('tem os botões da edição, do encaixe, do zoom, dos painéis e dos atalhos', async () => {
    await mountToolbar()
    for (const label of ['Cortar', 'Remover', 'Lift', 'Duplicar', 'Aparar entrada', 'Aparar saída', 'Snap', 'Ripple: V1', 'Afastar', 'Aproximar', 'Ajustar', 'Filtros', 'Mídia', 'Atalhos de teclado']) {
      expect(button(label), label).toBeDefined()
    }
  })

  it('o balão de cada botão mostra a tecla do atalho, e acompanha a tecla trocada', async () => {
    await mountToolbar()
    expect(button('Cortar')?.attributes('title')).toBe('Cortar o trecho no cursor (S)')
    expect(button('Remover')?.attributes('title')).toBe('Remover e fechar a lacuna (X ou Del)')
    expect(button('Aparar entrada')?.attributes('title')).toBe('Aparar a entrada até o cursor (I)')
    useKeymapStore().setBinding('split', 'b')
    await flushPromises()
    expect(button('Cortar')?.attributes('title')).toBe('Cortar o trecho no cursor (B)')
  })

  it('o texto da barra não usa travessão (regra da marca)', async () => {
    const bar = await mountToolbar()
    expect(bar.text()).not.toMatch(/[—–]/)
    for (const node of bar.findAll('button')) expect(node.attributes('title') ?? '').not.toMatch(/[—–]/)
  })
})

describe('os botões de edição', () => {
  it('Cortar divide o trecho sob o cursor', async () => {
    await mountToolbar()
    opened.store.setPlayhead(4.5)
    await button('Cortar')?.trigger('click')
    await flushPromises()
    expect(edits()[0]?.body).toMatchObject({ op: { type: 'split', index: 1, at: 1.5 } })
  })

  it('Remover, sem nada selecionado, avisa em vez de mandar a operação', async () => {
    await mountToolbar()
    await button('Remover')?.trigger('click')
    await flushPromises()
    expect(edits()).toHaveLength(0)
    expect(useToastsStore().items.map((toast) => toast.title)).toContain('Selecione um trecho ou sobreposição para remover.')
  })

  it('Remover tira o trecho selecionado e a seleção some junto', async () => {
    await mountToolbar()
    opened.store.select(['V1:1'])
    await button('Remover')?.trigger('click')
    await flushPromises()
    expect(edits()[0]?.body).toMatchObject({ op: { type: 'remove', index: 1 } })
    expect(opened.store.selection).toEqual([])
  })

  it('Lift tira o trecho da V1 e explica que a V1 não deixa lacuna', async () => {
    await mountToolbar()
    opened.store.select(['V1:0'])
    await button('Lift')?.trigger('click')
    await flushPromises()
    expect(edits()[0]?.body).toMatchObject({ op: { type: 'remove', index: 0 } })
    expect(useToastsStore().items.map((toast) => toast.title)).toContain('A V1 não tem lacunas: o lift removeu o trecho (ripple).')
  })

  it('Duplicar copia o trecho selecionado', async () => {
    await mountToolbar()
    opened.store.select(['V1:0'])
    await button('Duplicar')?.trigger('click')
    await flushPromises()
    expect(edits()[0]?.body).toMatchObject({ op: { type: 'duplicate', index: 0 } })
  })

  it('Aparar entrada e saída levam a borda até o cursor', async () => {
    await mountToolbar()
    opened.store.select(['V1:1'])
    opened.store.setPlayhead(4)
    await button('Aparar entrada')?.trigger('click')
    await flushPromises()
    expect(edits()[0]?.body).toMatchObject({ op: { type: 'trim', index: 1, side: 'in', delta: 1 } })
    await button('Aparar saída')?.trigger('click')
    await flushPromises()
    expect(edits()[1]?.body).toMatchObject({ op: { type: 'trim', index: 1, side: 'out', delta: -2 } })
  })
})

describe('encaixe, ripple e zoom', () => {
  it('Snap liga e desliga e diz o estado', async () => {
    await mountToolbar()
    expect(button('Snap')?.attributes('aria-pressed')).toBe('true')
    await button('Snap')?.trigger('click')
    expect(useTimelineStore().snapEnabled).toBe(false)
    expect(button('Snap')?.attributes('aria-pressed')).toBe('false')
  })

  it('o botão de ripple só troca o rótulo', async () => {
    await mountToolbar()
    await button('Ripple: V1')?.trigger('click')
    expect(button('Ripple: V1 (sempre)')).toBeDefined()
    expect(edits()).toHaveLength(0)
  })

  it('os botões de zoom mexem no zoom, e Ajustar faz o vídeo caber', async () => {
    await mountToolbar()
    const timeline = useTimelineStore()
    await button('Aproximar')?.trigger('click')
    expect(timeline.pxPerSec).toBeCloseTo(78, 9)
    await button('Afastar')?.trigger('click')
    expect(timeline.pxPerSec).toBeCloseTo(60, 9)
    timeline.setScroll(0, 632)
    await button('Ajustar')?.trigger('click')
    expect(timeline.pxPerSec).toBeCloseTo(500 / 6, 9)
  })
})

describe('painéis e atalhos', () => {
  it('F e M mostram e escondem os painéis Filtros e Mídia, e a escolha fica guardada', async () => {
    await mountToolbar()
    const panels = useEditorPanelsStore()
    expect(button('Filtros')?.attributes('aria-pressed')).toBe('true')
    await button('Filtros')?.trigger('click')
    expect(panels.isHidden('filters')).toBe(true)
    expect(button('Filtros')?.attributes('aria-pressed')).toBe('false')
    await button('Mídia')?.trigger('click')
    expect(JSON.parse(window.localStorage.getItem('dmaker.editor.hiddenPanels') ?? '[]').sort()).toEqual(['filters', 'media'])
    await button('Filtros')?.trigger('click')
    expect(panels.isHidden('filters')).toBe(false)
  })

  it('? abre a janela de atalhos', async () => {
    await mountToolbar()
    await button('Atalhos de teclado')?.trigger('click')
    expect(useKeymapStore().dialogOpen).toBe(true)
  })
})
