import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { PANEL_DRAG_MIME } from '@/lib/editorLayout'
import { useScreenLayoutStore } from '@/stores/screenLayout'
import EditorWorkbench from './EditorWorkbench.vue'
import { EDITOR_PANELS } from './panels'

const original = new Map(EDITOR_PANELS.map((panel) => [panel.id, panel.load]))

/** Esvazia os encaixes: o teste da grade só quer o aviso dos painéis que não existem, não os painéis de verdade. */
function emptySlots(): void {
  for (const id of ['media', 'player', 'filters', 'timeline'] as const) EDITOR_PANELS.find((panel) => panel.id === id)!.load = null
}

function mountWorkbench() {
  const pinia = createPinia()
  setActivePinia(pinia)
  return mount(EditorWorkbench, { global: { plugins: [pinia] } })
}

const cell = (wrapper: VueWrapper, id: string) => wrapper.find<HTMLElement>(`[data-cell="${id}"]`)
const cells = (wrapper: VueWrapper) => wrapper.findAll('[data-cell]').map((node) => node.attributes('data-cell'))
const place = (wrapper: VueWrapper, id: string) => {
  const style = cell(wrapper, id).element.style
  return `${style.gridColumn}|${style.gridRow}`
}
const grid = (wrapper: VueWrapper) => (wrapper.element as HTMLElement).style

/** O que o navegador entrega num arrastar e soltar de painel. */
function dragData(source: string) {
  return { types: [PANEL_DRAG_MIME], getData: () => source, setData: vi.fn(), effectAllowed: '', dropEffect: '' }
}

beforeEach(() => {
  window.localStorage.clear()
  emptySlots()
})

afterEach(() => {
  for (const panel of EDITOR_PANELS) panel.load = original.get(panel.id) ?? null
})

describe('EditorWorkbench: os encaixes', () => {
  it('mostra os quatro painéis, na ordem do Tab, com um aviso discreto nos que ainda não existem', () => {
    const wrapper = mountWorkbench()
    expect(cells(wrapper)).toEqual(['player', 'filters', 'timeline', 'media'])
    for (const slot of wrapper.findAll('[data-panel]')) expect(slot.text()).toContain('ainda não está disponível')
    expect(wrapper.text()).toContain('Linha do tempo')
  })

  it('cada painel cai no encaixe que o layout Edição manda: player em cima, filtros, linha do tempo e mídia embaixo', () => {
    const wrapper = mountWorkbench()
    expect(place(wrapper, 'player')).toBe('1 / -1|1')
    expect(place(wrapper, 'filters')).toBe('1|3')
    expect(place(wrapper, 'timeline')).toBe('3|3')
    expect(place(wrapper, 'media')).toBe('5|3')
    expect(grid(wrapper).gridTemplateColumns).toBe('240px 6px minmax(0, 1fr) 6px 240px')
    expect(grid(wrapper).gridTemplateRows).toBe('42.0% 6px minmax(0, 1fr)')
  })

  it('um painel registrado ocupa o encaixe no lugar do aviso, sem mexer na tela', async () => {
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

  it('cada moldura tem o título do painel, o botão de ocultar e o de mover', () => {
    const wrapper = mountWorkbench()
    const frame = wrapper.find('[data-frame="player"]')
    expect(frame.find('.frame__title').text()).toBe('Player')
    expect(frame.find('button[aria-label="Ocultar o painel Player"]').exists()).toBe(true)
    expect(frame.find('button[aria-label^="Mover o painel Player"]').exists()).toBe(true)
  })
})

describe('EditorWorkbench: ocultar painéis', () => {
  it('o painel oculto sai da tela e do DOM, e a coluna dele sai junto', async () => {
    const wrapper = mountWorkbench()
    const layout = useScreenLayoutStore()
    layout.setHidden('filters', true)
    await flushPromises()
    expect(cells(wrapper)).toEqual(['player', 'timeline', 'media'])
    expect(grid(wrapper).gridTemplateColumns).toBe('0px 0px minmax(0, 1fr) 6px 240px')
    layout.setHidden('media', true)
    await flushPromises()
    expect(cells(wrapper)).toEqual(['player', 'timeline'])
    expect(grid(wrapper).gridTemplateColumns).toBe('0px 0px minmax(0, 1fr) 0px 0px')
    layout.setHidden('filters', false)
    layout.setHidden('media', false)
    await flushPromises()
    expect(cells(wrapper)).toHaveLength(4)
  })

  it('o botão × da moldura oculta o painel', async () => {
    const wrapper = mountWorkbench()
    await wrapper.find('button[aria-label="Ocultar o painel Mídia"]').trigger('click')
    expect(useScreenLayoutStore().isHidden('media')).toBe(true)
    expect(cells(wrapper)).not.toContain('media')
  })

  it('sem o player, a faixa de baixo ocupa a altura toda e o divisor de linha some', async () => {
    const wrapper = mountWorkbench()
    useScreenLayoutStore().setHidden('player', true)
    await flushPromises()
    expect(grid(wrapper).gridTemplateRows).toBe('0px 0px minmax(0, 1fr)')
    expect(wrapper.find('[aria-label="Altura do player"]').exists()).toBe(false)
  })

  it('com todos os painéis ocultos, oferece restaurar o layout padrão', async () => {
    const wrapper = mountWorkbench()
    const layout = useScreenLayoutStore()
    for (const id of ['player', 'filters', 'media', 'timeline'] as const) layout.setHidden(id, true)
    await flushPromises()
    expect(wrapper.text()).toContain('Todos os painéis estão ocultos')
    await wrapper.findAll('button').find((button) => button.text().includes('Restaurar'))!.trigger('click')
    expect(cells(wrapper)).toHaveLength(4)
    expect(layout.layout.hidden).toEqual(['progress'])
  })
})

describe('EditorWorkbench: layouts', () => {
  it('escolher um layout muda a grade: Efeitos esconde a mídia e alarga a coluna da esquerda', async () => {
    const wrapper = mountWorkbench()
    useScreenLayoutStore().choose('Efeitos')
    await flushPromises()
    expect(cells(wrapper)).not.toContain('media')
    expect(grid(wrapper).gridTemplateColumns).toBe('420px 6px minmax(0, 1fr) 0px 0px')
  })

  it('o layout Player dá 72% da altura à faixa de cima', async () => {
    const wrapper = mountWorkbench()
    useScreenLayoutStore().choose('Player')
    await flushPromises()
    expect(grid(wrapper).gridTemplateRows).toBe('72.0% 6px minmax(0, 1fr)')
  })

  it('trocar dois painéis muda só a posição: o elemento é o mesmo, então o player não é recriado', async () => {
    const wrapper = mountWorkbench()
    const playerBefore = cell(wrapper, 'player').element
    useScreenLayoutStore().swap('player', 'timeline')
    await flushPromises()
    expect(cell(wrapper, 'player').element).toBe(playerBefore)
    expect(place(wrapper, 'player')).toBe('3|3')
    expect(place(wrapper, 'timeline')).toBe('1 / -1|1')
  })
})

describe('EditorWorkbench: arrastar o título', () => {
  it('soltar um painel sobre outro troca os dois de lugar', async () => {
    const wrapper = mountWorkbench()
    const data = dragData('player')
    await wrapper.find('[data-frame="player"] .frame__bar').trigger('dragstart', { dataTransfer: data })
    expect(data.setData).toHaveBeenCalledWith(PANEL_DRAG_MIME, 'player')
    await cell(wrapper, 'media').trigger('dragover', { dataTransfer: data })
    expect(wrapper.find('[data-frame="media"]').classes()).toContain('is-drop-target')
    await cell(wrapper, 'media').trigger('drop', { dataTransfer: data })

    expect(place(wrapper, 'player')).toBe('5|3')
    expect(place(wrapper, 'media')).toBe('1 / -1|1')
    expect(wrapper.find('[data-frame="media"]').classes()).not.toContain('is-drop-target')
  })

  it('soltar o painel sobre ele mesmo, ou soltar outra coisa, não troca nada', async () => {
    const wrapper = mountWorkbench()
    await cell(wrapper, 'player').trigger('drop', { dataTransfer: dragData('player') })
    // uma mídia arrastada para a linha do tempo tem outro tipo e passa sem ser tratada aqui
    const media = { types: ['application/x-dmaker-media'], getData: () => 'x', setData: vi.fn() }
    await cell(wrapper, 'timeline').trigger('dragover', { dataTransfer: media })
    await cell(wrapper, 'timeline').trigger('drop', { dataTransfer: media })
    expect(place(wrapper, 'player')).toBe('1 / -1|1')
    expect(place(wrapper, 'timeline')).toBe('3|3')
  })

  it('terminar o arrasto sem soltar limpa as marcas', async () => {
    const wrapper = mountWorkbench()
    await wrapper.find('[data-frame="player"] .frame__bar').trigger('dragstart', { dataTransfer: dragData('player') })
    expect(wrapper.find('[data-frame="player"]').classes()).toContain('is-dragging')
    await wrapper.find('[data-frame="player"] .frame__bar').trigger('dragend')
    expect(wrapper.find('[data-frame="player"]').classes()).not.toContain('is-dragging')
  })

  it('pelo teclado, as setas no ícone de mover trocam com o vizinho e avisam o leitor de tela', async () => {
    const wrapper = mountWorkbench()
    await wrapper.find('[data-frame="player"] .frame__grip').trigger('keydown', { key: 'ArrowDown' })
    expect(place(wrapper, 'player')).toBe('3|3')
    expect(place(wrapper, 'timeline')).toBe('1 / -1|1')
    expect(wrapper.find('[role="status"]').text()).toBe('Player trocou de lugar com Linha do tempo.')
  })

  it('onde não há vizinho, a seta não troca nada e diz isso', async () => {
    const wrapper = mountWorkbench()
    await wrapper.find('[data-frame="player"] .frame__grip').trigger('keydown', { key: 'ArrowUp' })
    expect(place(wrapper, 'player')).toBe('1 / -1|1')
    expect(wrapper.find('[role="status"]').text()).toBe('Não há painel nessa direção.')
  })
})

describe('EditorWorkbench: divisores', () => {
  function drag(wrapper: VueWrapper, label: string, from: { x?: number; y?: number }, to: { x?: number; y?: number }) {
    const divider = wrapper.find(`[aria-label="${label}"]`)
    return divider.trigger('mousedown', { button: 0, clientX: from.x ?? 0, clientY: from.y ?? 0 }).then(() => {
      window.dispatchEvent(new MouseEvent('mousemove', { clientX: to.x ?? 0, clientY: to.y ?? 0 }))
      window.dispatchEvent(new MouseEvent('mouseup'))
      return flushPromises()
    })
  }

  it('arrastar o divisor da esquerda muda a largura da coluna e guarda no layout', async () => {
    const wrapper = mountWorkbench()
    await drag(wrapper, 'Largura da coluna da esquerda', { x: 240 }, { x: 300 })
    expect(useScreenLayoutStore().layout.sizes['col-left']).toBe(300)
    expect(grid(wrapper).gridTemplateColumns).toBe('300px 6px minmax(0, 1fr) 6px 240px')
  })

  it('o divisor da direita cresce para a esquerda', async () => {
    const wrapper = mountWorkbench()
    await drag(wrapper, 'Largura da coluna da direita', { x: 900 }, { x: 860 })
    expect(useScreenLayoutStore().layout.sizes['col-right']).toBe(280)
  })

  it('o tamanho não passa dos limites', async () => {
    const wrapper = mountWorkbench()
    await drag(wrapper, 'Largura da coluna da esquerda', { x: 240 }, { x: 5000 })
    expect(useScreenLayoutStore().layout.sizes['col-left']).toBe(560)
  })

  it('as setas movem o divisor pelo teclado', async () => {
    const wrapper = mountWorkbench()
    await wrapper.find('[aria-label="Largura da coluna da esquerda"]').trigger('keydown', { key: 'ArrowRight' })
    expect(useScreenLayoutStore().layout.sizes['col-left']).toBe(256)
    await wrapper.find('[aria-label="Altura do player"]').trigger('keydown', { key: 'ArrowDown' })
    expect(useScreenLayoutStore().layout.sizes['row-top']).toBeCloseTo(0.44, 5)
  })

  it('mexer num divisor acorda os painéis com um aviso de redimensionamento', async () => {
    const wrapper = mountWorkbench()
    const resized = vi.fn()
    window.addEventListener('resize', resized)
    await drag(wrapper, 'Largura da coluna da esquerda', { x: 0 }, { x: 10 })
    window.removeEventListener('resize', resized)
    expect(resized).toHaveBeenCalled()
  })
})
