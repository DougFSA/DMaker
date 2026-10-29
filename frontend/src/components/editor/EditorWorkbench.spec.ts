import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { defineComponent, h } from 'vue'
import EditorWorkbench from './EditorWorkbench.vue'
import { EDITOR_PANELS } from './panels'

const original = new Map(EDITOR_PANELS.map((panel) => [panel.id, panel.load]))

afterEach(() => {
  for (const panel of EDITOR_PANELS) panel.load = original.get(panel.id) ?? null
})

describe('EditorWorkbench', () => {
  it('mostra os quatro encaixes, com um aviso discreto nos que ainda não existem', () => {
    // o player já existe; para este teste só importa o aviso dos outros, então o dele sai do caminho
    EDITOR_PANELS.find((panel) => panel.id === 'player')!.load = null
    const wrapper = mount(EditorWorkbench)
    const slots = wrapper.findAll('[data-panel]')
    expect(slots.map((slot) => slot.attributes('data-panel'))).toEqual(['media', 'player', 'filters', 'timeline'])
    for (const slot of slots) expect(slot.text()).toContain('ainda não está disponível')
    expect(wrapper.text()).toContain('Linha do tempo')
  })

  it('cada encaixe é uma área da grade, para o painel novo só precisar se registrar', () => {
    EDITOR_PANELS.find((panel) => panel.id === 'player')!.load = null
    const wrapper = mount(EditorWorkbench)
    const areas = wrapper.findAll('[data-panel]').map((slot) => (slot.element as HTMLElement).style.gridArea)
    expect(areas).toEqual(['media', 'player', 'filters', 'timeline'])
  })

  it('um painel registrado ocupa o encaixe no lugar do aviso, sem mexer na tela', async () => {
    const Player = defineComponent({ render: () => h('div', { class: 'player-stub' }, 'Palco do vídeo') })
    // o que `import('./PlayerPanel.vue')` devolve: um módulo cujo `default` é o componente
    const moduleOfPlayer = { __esModule: true as const, default: Player }
    EDITOR_PANELS.find((panel) => panel.id === 'player')!.load = () => Promise.resolve(moduleOfPlayer)
    const wrapper = mount(EditorWorkbench)
    await flushPromises()
    const player = wrapper.find('[data-panel="player"]')
    expect(player.find('.player-stub').text()).toBe('Palco do vídeo')
    expect(player.text()).not.toContain('ainda não está disponível')
    expect(wrapper.find('[data-panel="timeline"]').text()).toContain('ainda não está disponível')
  })
})
