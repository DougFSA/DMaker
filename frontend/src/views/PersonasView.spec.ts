import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FakeEventSource } from '@/test/fetch'
import { reply, routedFetch, type RoutedFetch } from '@/test/routedFetch'
import { mountRoute } from '@/test/routes'
import { useConfirmStore } from '@/stores/confirm'

const BIA = {
  id: 'bia',
  name: 'Bia',
  kind: '2d',
  voice: null,
  appearance: { skin: '#E8B796', hair_style: 'bun' },
  expressions: [],
  gestures: [],
  builtin: true,
  created: '2026-11-01',
}
const ANA = { ...BIA, id: 'ana', name: 'Ana', builtin: false, voice: 'voz-ana' }
const ENGINES = [
  { kind: '2d', expressions: ['neutral', 'happy'], gestures: ['nod', 'wave'], unavailable: null },
  {
    kind: '3d',
    expressions: ['neutral'],
    gestures: ['nod', 'wave'],
    unavailable: 'O personagem da persona 3D ainda não foi baixado. Baixe com `dmaker models download persona3d-mpfb`.',
  },
]

let http: RoutedFetch
let wrapper: VueWrapper | null = null

beforeEach(() => {
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
  http = routedFetch({
    'GET /api/personas': { personas: [BIA, ANA], engines: ENGINES },
    'GET /api/voices': [{ id: 'voz-ana', name: 'Voz da Ana', kind: 'clone', engine: 'omnivoice', language: 'pt', brand: null }],
    'POST /api/personas': { ...ANA, id: 'caio', name: 'Caio', kind: '3d' },
    'DELETE /api/personas/ana': { removed: 'ana' },
    'POST /api/personas/ana/preview': { job_id: 'j1' },
    'GET /api/projects': [{ name: 'demo' }],
    'POST /api/personas/ana/use': { project: 'demo', placement: 'overlay' },
  })
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

async function open(): Promise<VueWrapper> {
  wrapper = (await mountRoute('/personas')).wrapper
  await flushPromises()
  return wrapper
}

const button = (label: string) => wrapper!.findAll('button').find((node) => node.text() === label)!

describe('PersonasView (/personas)', () => {
  it('separa as prontas (só leitura) das do usuário', async () => {
    await open()
    expect(wrapper!.find('h1').text()).toBe('Personas')
    expect(wrapper!.find('[data-persona="bia"]').text()).toContain('Bia')
    expect(wrapper!.find('[data-persona="bia"]').text()).not.toContain('Apagar')
    expect(wrapper!.find('[data-persona="ana"]').text()).toContain('Voz da Ana')
    expect(wrapper!.find('[data-persona="ana"]').text()).toContain('Apagar')
  })

  it('3D sem o modelo mostra a mensagem do motor e o caminho para a tela de Modelos', async () => {
    await open()
    const select = wrapper!.findAll('select').find((node) => node.attributes('id') && node.element.innerHTML.includes('3D'))!
    await select.setValue('3d')
    expect(wrapper!.text()).toContain('dmaker models download persona3d-mpfb')
    expect(wrapper!.find('a[href="/modelos"]').exists()).toBe(true)
  })

  it('cria uma persona com o nome, o tipo e a aparência do tipo', async () => {
    await open()
    await wrapper!.find('input[type="text"]').setValue('Caio')
    const select = wrapper!.findAll('select').find((node) => node.element.innerHTML.includes('3D'))!
    await select.setValue('3d')
    await wrapper!.find('form.form').trigger('submit')
    await flushPromises()
    const call = http.to('POST /api/personas')[0]!
    expect(call.body).toMatchObject({ name: 'Caio', kind: '3d', voice: null })
    expect((call.body as { appearance: Record<string, string> }).appearance.outfit_color).toBe('#3A4A5E')
  })

  it('apagar pergunta antes e só então chama a API', async () => {
    await open()
    await button('Apagar').trigger('click')
    await flushPromises()
    expect(http.to('DELETE /api/personas/ana')).toHaveLength(0)
    useConfirmStore().answer(true)
    await flushPromises()
    expect(http.to('DELETE /api/personas/ana')).toHaveLength(1)
  })

  it('a prévia inicia o job da persona escolhida', async () => {
    await open()
    await wrapper!.find('[data-persona="ana"] .item__main').trigger('click')
    await wrapper!.find('form.preview input').setValue('Bom dia')
    await wrapper!.find('form.preview').trigger('submit')
    await flushPromises()
    expect(http.to('POST /api/personas/ana/preview')[0]!.body).toEqual({ phrase: 'Bom dia' })
  })

  it('põe a persona num projeto, no canto ou em tela cheia', async () => {
    await open()
    await wrapper!.find('[data-persona="ana"] .item__main').trigger('click')
    const card = wrapper!.findAll('form.preview')[1]!
    const [project, where] = card.findAll('select')
    await project!.setValue('demo')
    await where!.setValue('overlay')
    await card.find('input').setValue('Oi gente')
    await card.trigger('submit')
    await flushPromises()
    expect(http.to('POST /api/personas/ana/use')[0]!.body).toEqual({ project: 'demo', text: 'Oi gente', placement: 'overlay' })
  })

  it('mostra as expressões e os gestos do motor com nome em português e o identificador', async () => {
    await open()
    const caps = wrapper!.find('.personas__caps').text()
    expect(caps).toContain('alegre (happy)')
    expect(caps).toContain('aceno com a mão (wave)')
    expect(caps).toContain('sim com a cabeça (nod)')
  })

  it('mostra o erro do carregamento e tenta de novo', async () => {
    http.set('GET /api/personas', reply(500, { detail: 'servidor parado' }))
    await open()
    expect(wrapper!.text()).toContain('servidor parado')
    http.set('GET /api/personas', { personas: [BIA], engines: ENGINES })
    await button('Tentar de novo').trigger('click')
    await flushPromises()
    expect(wrapper!.text()).not.toContain('servidor parado')
  })
})
