import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { defineComponent, h } from 'vue'
import { useEditorPanelsStore } from '@/stores/editorPanels'
import EditorWorkbench from './EditorWorkbench.vue'
import { EDITOR_PANELS } from './panels'

const original = new Map(EDITOR_PANELS.map((panel) => [panel.id, panel.load]))

/** Tira do caminho os painéis que já existem: o teste do encaixe só quer o aviso dos que ainda não existem. */
function emptySlots(): void {
  for (const id of ['player', 'timeline'] as const) EDITOR_PANELS.find((panel) => panel.id === id)!.load = null
}

function mountWorkbench() {
  const pinia = createPinia()
  setActivePinia(pinia)
  return mount(EditorWorkbench, { global: { plugins: [pinia] } })
}

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  for (const panel of EDITOR_PANELS) panel.load = original.get(panel.id) ?? null
})

describe('EditorWorkbench', () => {
  it('mostra os quatro encaixes, com um aviso discreto nos que ainda não existem', () => {
    emptySlots()
    const wrapper = mountWorkbench()
    const slots = wrapper.findAll('[data-panel]')
    expect(slots.map((slot) => slot.attributes('data-panel'))).toEqual(['media', 'player', 'filters', 'timeline'])
    for (const slot of slots) expect(slot.text()).toContain('ainda não está disponível')
    expect(wrapper.text()).toContain('Linha do tempo')
  })

  it('cada encaixe é uma área da grade, para o painel novo só precisar se registrar', () => {
    emptySlots()
    const wrapper = mountWorkbench()
    const areas = wrapper.findAll('[data-panel]').map((slot) => (slot.element as HTMLElement).style.gridArea)
    expect(areas).toEqual(['media', 'player', 'filters', 'timeline'])
  })

  it('um painel registrado ocupa o encaixe no lugar do aviso, sem mexer na tela', async () => {
    emptySlots()
    const Timeline = defineComponent({ render: () => h('div', { class: 'timeline-stub' }, 'Trilhas do vídeo') })
    // o que `import('./TimelinePanel.vue')` devolve: um módulo cujo `default` é o componente
    const moduleOfTimeline = { __esModule: true as const, default: Timeline }
    EDITOR_PANELS.find((panel) => panel.id === 'timeline')!.load = () => Promise.resolve(moduleOfTimeline)
    const wrapper = mountWorkbench()
    await flushPromises()
    const timeline = wrapper.find('[data-panel="timeline"]')
    expect(timeline.find('.timeline-stub').text()).toBe('Trilhas do vídeo')
    expect(timeline.text()).not.toContain('ainda não está disponível')
    expect(wrapper.find('[data-panel="player"]').text()).toContain('ainda não está disponível')
  })

  it('os painéis escondidos pela pessoa saem da grade, e a coluna deles sai junto', async () => {
    emptySlots()
    const wrapper = mountWorkbench()
    const panels = useEditorPanelsStore()
    panels.setHidden('filters', true)
    await flushPromises()
    expect(wrapper.findAll('[data-panel]').map((slot) => slot.attributes('data-panel'))).toEqual(['media', 'player', 'timeline'])
    expect(wrapper.classes()).toContain('workbench--no-filters')
    panels.setHidden('media', true)
    await flushPromises()
    expect(wrapper.findAll('[data-panel]').map((slot) => slot.attributes('data-panel'))).toEqual(['player', 'timeline'])
    expect(wrapper.classes()).toEqual(expect.arrayContaining(['workbench--no-filters', 'workbench--no-media']))
    panels.setHidden('filters', false)
    panels.setHidden('media', false)
    await flushPromises()
    expect(wrapper.findAll('[data-panel]')).toHaveLength(4)
  })

  it('o que a pessoa escondeu fica guardado para a próxima vez', () => {
    setActivePinia(createPinia())
    useEditorPanelsStore().setHidden('media', true)
    expect(window.localStorage.getItem('dmaker.editor.hiddenPanels')).toBe('["media"]')
    setActivePinia(createPinia())
    expect(useEditorPanelsStore().isHidden('media')).toBe(true)
    expect(useEditorPanelsStore().isHidden('filters')).toBe(false)
  })

  it('o que está guardado e não é uma lista de painéis é ignorado', () => {
    window.localStorage.setItem('dmaker.editor.hiddenPanels', '{"a":1}')
    setActivePinia(createPinia())
    expect(useEditorPanelsStore().hidden).toEqual([])
    window.localStorage.setItem('dmaker.editor.hiddenPanels', 'não é json')
    setActivePinia(createPinia())
    expect(useEditorPanelsStore().hidden).toEqual([])
  })
})
