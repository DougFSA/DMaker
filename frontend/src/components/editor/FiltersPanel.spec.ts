import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { TimelineView } from '@/api'
import { mountEditorPart, openEditor, type OpenedEditor } from '@/test/editorMount'
import { timelineItem, timelineTrack } from '@/test/editorFixtures'
import { filterSchema } from '@/test/filterFixtures'
import FiltersPanel from './FiltersPanel.vue'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})
beforeEach(() => window.localStorage.clear())

function filterSpec(): Record<string, unknown> {
  return {
    name: 'demo',
    version: 1,
    output: { preset: 'instagram/reels', encoder: 'x264', quality: 'high', guides: false },
    sources: {},
    timeline: [
      {
        type: 'clip',
        src: 'a.mp4',
        start: 0,
        speed: 2,
        volume: 1,
        mute: false,
        fade_in: 0,
        fade_out: 0,
        reframe: { mode: 'crop', focus: [0.5, 0.5], zoom: 1, margin: 0.05, radius: 0.018 },
      },
      { type: 'card', title: 'Fim', duration: 3, logo: true, motion: 'zoom-in', motion_amount: 0.04 },
    ],
    overlays: [
      { type: 'text', text: 'Olá', role: 'title', start: 0 },
      { type: 'video', src: 'pip.mp4', start: 1, position: 'bottom-right' },
    ],
    audio: {
      voice_gain: 1,
      normalize: 'two-pass',
      mute_clips: false,
      music: { src: 'musica.mp3', volume: 0.18, loop: true },
      tracks: [{ source: 'x', volume: 1 }],
    },
  }
}

/** A vista com uma trilha de cada tipo, cada item com o id `<trilha>-<índice>` que a linha do tempo usa. */
function filterView(): TimelineView {
  const item = (id: string, index: number, kind: string) => timelineItem(index, { id, kind })
  return {
    total: 9,
    fps: 30,
    width: 1080,
    height: 1920,
    tracks: [
      timelineTrack('V1', [item('V1-0', 0, 'clip'), item('V1-1', 1, 'card')]),
      timelineTrack('TX', [item('TX-0', 0, 'text')], { kind: 'text' }),
      timelineTrack('V2', [item('V2-1', 1, 'video')]),
      timelineTrack('A1', [item('A1-0', 0, 'audio')], { kind: 'audio' }),
      timelineTrack('A2', [item('A2-0', 0, 'audio')], { kind: 'audio' }),
      timelineTrack('MUS', [item('MUS-0', 0, 'music')], { kind: 'audio' }),
    ],
    sources: {},
    warnings: [],
  }
}

async function mountFilters(): Promise<{ opened: OpenedEditor; wrapper: VueWrapper }> {
  const opened = await openEditor(filterSpec(), {
    'GET /api/schema': filterSchema(),
    'POST /api/projects/demo/timeline': () => filterView(),
  })
  const wrapper = await mountEditorPart(FiltersPanel, opened, {}, true)
  return { opened, wrapper }
}

async function choose(opened: OpenedEditor, ...ids: string[]): Promise<void> {
  opened.store.select(ids)
  await flushPromises()
}

const titles = (wrapper: VueWrapper) => wrapper.findAll('.group__title').map((title) => title.text())
const group = (wrapper: VueWrapper, id: string) => wrapper.find(`[data-group-id="${id}"]`)
const inputIn = (wrapper: VueWrapper, groupId: string, label: string) =>
  group(wrapper, groupId)
    .findAll('.field')
    .find((field) => field.text().includes(label))
    ?.find('input, select')

async function openMenu(wrapper: VueWrapper): Promise<string[]> {
  await wrapper.find('[aria-label="Adicionar filtro"]').trigger('click')
  await flushPromises()
  return [...document.body.querySelectorAll('[data-add-group]')].map((button) => button.textContent?.trim() ?? '')
}

describe('FiltersPanel: sem nada selecionado', () => {
  it('mostra os filtros do projeto, e só os que saem do padrão', async () => {
    const { wrapper } = await mountFilters()
    expect(wrapper.text()).toContain('Projeto (nada selecionado)')
    expect(titles(wrapper)).toEqual([])
    expect(wrapper.text()).toContain('Nenhum filtro aplicado')
  })

  it('o "+" lista os grupos do projeto e adiciona o escolhido, com os padrões do schema', async () => {
    const { wrapper } = await mountFilters()
    expect(await openMenu(wrapper)).toEqual(['Saída', 'Áudio geral'])
    ;(document.body.querySelector('[data-add-group="project-output"]') as HTMLElement).click()
    await flushPromises()
    expect(titles(wrapper)).toEqual(['Saída'])
    expect((inputIn(wrapper, 'project-output', 'Qualidade')!.element as HTMLSelectElement).value).toBe('high')
    // o grupo adicionado sai da lista do "+"
    expect(await openMenu(wrapper)).toEqual(['Áudio geral'])
  })

  it('um campo do projeto fora do padrão mostra o grupo sozinho', async () => {
    const opened = await openEditor(
      { ...filterSpec(), audio: { voice_gain: 2, normalize: 'two-pass', mute_clips: false } },
      { 'GET /api/schema': filterSchema(), 'POST /api/projects/demo/timeline': () => filterView() },
    )
    const wrapper = await mountEditorPart(FiltersPanel, opened, {}, true)
    expect(titles(wrapper)).toEqual(['Áudio geral'])
    expect((inputIn(wrapper, 'project-audio', 'Ganho da voz')!.element as HTMLInputElement).value).toBe('2')
  })

  it('o campo Formato lista os formatos do servidor', async () => {
    const { wrapper } = await mountFilters()
    await openMenu(wrapper)
    ;(document.body.querySelector('[data-add-group="project-output"]') as HTMLElement).click()
    await flushPromises()
    const preset = inputIn(wrapper, 'project-output', 'Formato')!.element as HTMLSelectElement
    expect([...preset.options].map((option) => option.text)).toEqual([
      'Instagram · Reels (instagram/reels)',
      'YouTube · Vídeo (youtube/video)',
    ])
    expect(preset.value).toBe('instagram/reels')
  })
})

describe('FiltersPanel: com um item selecionado', () => {
  it('o clipe mostra só os grupos aplicados (velocidade e reenquadramento)', async () => {
    const { opened, wrapper } = await mountFilters()
    await choose(opened, 'V1-0')
    expect(wrapper.text()).toContain('Clipe')
    expect(titles(wrapper)).toEqual(['Reenquadrar', 'Velocidade'])
    expect((inputIn(wrapper, 'speed', 'Velocidade')!.element as HTMLInputElement).value).toBe('2')
    expect((inputIn(wrapper, 'reframe', 'Modo')!.element as HTMLSelectElement).value).toBe('crop')
  })

  it('o "+" lista os outros grupos do clipe e abre o escolhido', async () => {
    const { opened, wrapper } = await mountFilters()
    await choose(opened, 'V1-0')
    expect(await openMenu(wrapper)).toEqual(['Cor', 'Áudio', 'Fade', 'Transição de entrada', 'Rótulo'])
    ;(document.body.querySelector('[data-add-group="color"]') as HTMLElement).click()
    await flushPromises()
    expect(titles(wrapper)).toEqual(['Reenquadrar', 'Cor', 'Velocidade'])
    expect((inputIn(wrapper, 'color', 'Contraste')!.element as HTMLInputElement).value).toBe('1')
  })

  it('o grupo aberto pelo "+" não passa para o item seguinte', async () => {
    const { opened, wrapper } = await mountFilters()
    await choose(opened, 'V1-0')
    await openMenu(wrapper)
    ;(document.body.querySelector('[data-add-group="color"]') as HTMLElement).click()
    await flushPromises()
    await choose(opened, 'V1-1')
    expect(wrapper.text()).toContain('Cartão')
    // o cartão só mostra o que é dele: o título "Fim" sai do padrão, e o Cor do clipe não veio junto
    expect(titles(wrapper)).toEqual(['Texto'])
    await choose(opened, 'V1-0')
    expect(titles(wrapper)).toEqual(['Reenquadrar', 'Velocidade'])
  })

  it('a faixa A1 edita o clipe da V1 de mesmo índice', async () => {
    const { opened, wrapper } = await mountFilters()
    await choose(opened, 'A1-0')
    expect(wrapper.text()).toContain('Clipe')
    expect(titles(wrapper)).toEqual(['Reenquadrar', 'Velocidade'])
  })

  it('cada tipo de item tem os seus grupos: cartão, texto, PiP, faixa e música', async () => {
    const { opened, wrapper } = await mountFilters()
    await choose(opened, 'V1-1')
    expect(titles(wrapper)).toEqual(['Texto'])
    expect(await openMenu(wrapper)).toEqual(['Fade', 'Transição de entrada', 'Rótulo', 'Movimento', 'Duração', 'Estilo'])
    document.body.innerHTML = ''
    await choose(opened, 'TX-0')
    expect(titles(wrapper)).toEqual(['Texto'])
    await choose(opened, 'V2-1')
    expect(wrapper.text()).toContain('Vídeo (PiP)')
    await choose(opened, 'A2-0')
    expect(wrapper.text()).toContain('Faixa de áudio')
    await choose(opened, 'MUS-0')
    expect(titles(wrapper)).toEqual(['Música'])
  })

  it('a seleção de vários itens mostra os filtros do último escolhido', async () => {
    const { opened, wrapper } = await mountFilters()
    await choose(opened, 'V1-0', 'V1-1')
    expect(wrapper.text()).toContain('Cartão')
  })

  it('a transição lista as do catálogo do servidor, com o corte seco primeiro', async () => {
    const { opened, wrapper } = await mountFilters()
    await choose(opened, 'V1-1')
    await openMenu(wrapper)
    ;(document.body.querySelector('[data-add-group="transition"]') as HTMLElement).click()
    await flushPromises()
    const type = inputIn(wrapper, 'transition', 'Tipo')!.element as HTMLSelectElement
    expect([...type.options].map((option) => option.value)).toEqual(['cut', 'fade', 'dissolve', 'wipeleft'])
    expect(type.value).toBe('fade') // o padrão do schema, o que o servidor assume ao criar a transição
  })
})

describe('FiltersPanel: editar', () => {
  it('lista e caixa de marcar gravam na hora', async () => {
    const { opened, wrapper } = await mountFilters()
    await choose(opened, 'V1-0')
    await inputIn(wrapper, 'reframe', 'Modo')!.setValue('blur')
    expect(opened.store.get('timeline.0.reframe.mode')).toBe('blur')
    await openMenu(wrapper)
    ;(document.body.querySelector('[data-add-group="clip-audio"]') as HTMLElement).click()
    await flushPromises()
    await group(wrapper, 'clip-audio').find('input[type="checkbox"]').setValue(true)
    expect(opened.store.get('timeline.0.mute')).toBe(true)
  })

  it('texto e número esperam 300 ms de silêncio', async () => {
    const { opened, wrapper } = await mountFilters()
    await choose(opened, 'V1-0')
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    await inputIn(wrapper, 'speed', 'Velocidade')!.setValue('3')
    await vi.advanceTimersByTimeAsync(299)
    expect(opened.store.get('timeline.0.speed')).toBe(2)
    await vi.advanceTimersByTimeAsync(1)
    expect(opened.store.get('timeline.0.speed')).toBe(3)
  })

  it('o campo aninhado cria o contêiner que faltava (a transição) sem tocar no resto', async () => {
    const { opened, wrapper } = await mountFilters()
    await choose(opened, 'V1-1')
    await openMenu(wrapper)
    ;(document.body.querySelector('[data-add-group="transition"]') as HTMLElement).click()
    await flushPromises()
    await inputIn(wrapper, 'transition', 'Tipo')!.setValue('dissolve')
    expect(opened.store.get('timeline.1.transition')).toEqual({ type: 'dissolve' })
    expect(opened.store.get('timeline.1.title')).toBe('Fim')
  })

  it('voltar um campo ao padrão não faz o grupo sumir debaixo de quem digita', async () => {
    const { opened, wrapper } = await mountFilters()
    await choose(opened, 'V1-0')
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    await inputIn(wrapper, 'speed', 'Velocidade')!.setValue('1')
    await vi.advanceTimersByTimeAsync(300)
    expect(opened.store.get('timeline.0.speed')).toBe(1)
    expect(titles(wrapper)).toContain('Velocidade')
  })

  it('a edição muda o "não salvo" e a linha do tempo do store, como na aba Propriedades', async () => {
    const { opened, wrapper } = await mountFilters()
    await choose(opened, 'V1-0')
    expect(opened.store.dirty).toBe(false)
    await inputIn(wrapper, 'reframe', 'Modo')!.setValue('pad')
    expect(opened.store.dirty).toBe(true)
  })
})

describe('FiltersPanel: o "×" de um grupo', () => {
  it('apaga os campos do grupo e ele some; desfazer traz tudo de volta', async () => {
    const { opened, wrapper } = await mountFilters()
    await choose(opened, 'V1-0')
    await group(wrapper, 'reframe').find('button[aria-label="Remover Reenquadrar"]').trigger('click')
    await flushPromises()
    expect(opened.store.get('timeline.0')).not.toHaveProperty('reframe')
    expect(titles(wrapper)).toEqual(['Velocidade'])
    expect(opened.store.canUndo).toBe(true)
    opened.store.undo()
    await flushPromises()
    expect(opened.store.get('timeline.0.reframe.mode')).toBe('crop')
    expect(titles(wrapper)).toEqual(['Reenquadrar', 'Velocidade'])
  })

  it('o grupo do fade zera os dois campos', async () => {
    const opened = await openEditor(
      { ...filterSpec(), timeline: [{ type: 'clip', src: 'a.mp4', start: 0, speed: 1, fade_in: 1, fade_out: 2 }] },
      { 'GET /api/schema': filterSchema(), 'POST /api/projects/demo/timeline': () => filterView() },
    )
    const wrapper = await mountEditorPart(FiltersPanel, opened, {}, true)
    await choose(opened, 'V1-0')
    expect(titles(wrapper)).toEqual(['Fade'])
    await wrapper.find('button[aria-label="Remover Fade"]').trigger('click')
    await flushPromises()
    expect(opened.store.get('timeline.0')).not.toHaveProperty('fade_in')
    expect(opened.store.get('timeline.0')).not.toHaveProperty('fade_out')
    expect(wrapper.text()).toContain('Nenhum filtro aplicado')
  })

  it('o grupo que o item não vale sem (o texto, o arquivo da música) não tem "×"', async () => {
    const { opened, wrapper } = await mountFilters()
    await choose(opened, 'TX-0')
    expect(group(wrapper, 'text-content').exists()).toBe(true)
    expect(group(wrapper, 'text-content').find('button').exists()).toBe(false)
    await choose(opened, 'MUS-0')
    expect(group(wrapper, 'music-main').find('button[aria-label^="Remover"]').exists()).toBe(false)
  })

  it('tirar o grupo da música devolve o resto ao padrão e mantém o arquivo', async () => {
    const opened = await openEditor(
      {
        ...filterSpec(),
        audio: { voice_gain: 1, normalize: 'two-pass', mute_clips: false, music: { src: 'musica.mp3', volume: 0.5, fade_in: 3, fade_out: 4 } },
      },
      { 'GET /api/schema': filterSchema(), 'POST /api/projects/demo/timeline': () => filterView() },
    )
    const wrapper = await mountEditorPart(FiltersPanel, opened, {}, true)
    await choose(opened, 'MUS-0')
    expect(titles(wrapper)).toEqual(['Música', 'Fade'])
    await wrapper.find('button[aria-label="Remover Fade"]').trigger('click')
    await flushPromises()
    expect(opened.store.get('audio.music')).toEqual({ src: 'musica.mp3', volume: 0.5 })
  })

  it('o "×" grava antes o que ainda esperava ser digitado', async () => {
    const { opened, wrapper } = await mountFilters()
    await choose(opened, 'V1-0')
    await inputIn(wrapper, 'speed', 'Velocidade')!.setValue('5')
    await wrapper.find('button[aria-label="Remover Velocidade"]').trigger('click')
    await flushPromises()
    expect(opened.store.get('timeline.0')).not.toHaveProperty('speed')
    expect(titles(wrapper)).toEqual(['Reenquadrar'])
  })
})

describe('FiltersPanel: sem projeto', () => {
  it('fora de um projeto aberto avisa e não oferece filtros', async () => {
    const opened = await openEditor(filterSpec(), { 'GET /api/schema': filterSchema() })
    opened.store.close()
    const wrapper = await mountEditorPart(FiltersPanel, opened, {}, true)
    expect(wrapper.text()).toContain('Sem projeto aberto')
    expect(wrapper.find('[aria-label="Adicionar filtro"]').attributes('disabled')).toBeDefined()
  })
})
