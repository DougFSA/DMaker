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
const REAL = {
  ...BIA,
  id: 'rosto',
  name: 'Rosto',
  kind: 'realistic',
  builtin: false,
  appearance: { photo: 'foto.jpg', steps: '15' },
  expressions: ['neutral'],
  gestures: [],
  photo_url: '/api/personas/rosto/photo',
}
const ENGINES = [
  { kind: '2d', expressions: ['neutral', 'happy'], gestures: ['nod', 'wave'], unavailable: null },
  { kind: 'realistic', expressions: ['neutral'], gestures: [], unavailable: null },
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
    'GET /api/personas': { personas: [BIA, ANA, REAL], engines: ENGINES },
    'GET /api/personas/rosto/preview/estimate': {
      seconds: 660,
      frames: 113,
      device: 'gpu',
      device_label: 'GPU integrada',
      speech_seconds: 4.1,
    },
    'POST /api/personas/realistic': { ...REAL, id: 'novo', name: 'Novo' },
    'POST /api/personas/rosto/use': { project: 'demo', placement: 'segment' },
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

  it('a realista aparece na lista com a miniatura da foto', async () => {
    await open()
    const item = wrapper!.find('[data-persona="rosto"]')
    expect(item.find('img').attributes('src')).toBe('/api/personas/rosto/photo')
    expect(item.text()).toContain('Realista (uma foto que fala)')
  })

  it('cria a realista enviando a foto, com o aviso de direito de imagem e sem expressões nem gestos', async () => {
    await open()
    await wrapper!.find('input[type="text"]').setValue('Novo')
    const select = wrapper!.findAll('select').find((node) => node.element.innerHTML.includes('3D'))!
    await select.setValue('realistic')
    expect(wrapper!.text()).toContain('Use só foto sua ou de quem autorizou o uso da imagem.')
    expect(wrapper!.find('.personas__caps').text()).toBe('Só a expressão da foto; sem gestos.')
    expect(wrapper!.text()).not.toContain('Aparência') // não há cor nem cabelo para escolher: a aparência é a foto
    const submit = () => wrapper!.findAll('button').find((node) => node.text() === 'Criar persona')!
    expect(submit().attributes('disabled')).toBeDefined() // sem a foto não dá para criar

    const input = wrapper!.find('input[type="file"]')
    const photo = new File(['jpg'], 'eu.jpg', { type: 'image/jpeg' })
    Object.defineProperty(input.element, 'files', { value: [photo], configurable: true })
    await input.trigger('change')
    await flushPromises()
    await wrapper!.find('form.form').trigger('submit')
    await flushPromises()

    const call = http.to('POST /api/personas/realistic')[0]!
    expect(call.form?.get('name')).toBe('Novo')
    expect((call.form?.get('photo') as File).name).toBe('eu.jpg')
    expect(http.to('POST /api/personas')).toHaveLength(0)
  })

  it('mostra a estimativa antes da prévia, ao lado do botão, e a foto no detalhe', async () => {
    await open()
    await wrapper!.find('[data-persona="rosto"] .item__main').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 400))
    await flushPromises()
    expect(http.to('GET /api/personas/rosto/preview/estimate')).toHaveLength(1)
    expect(wrapper!.find('[data-estimate]').text()).toBe('A prévia leva uns 11 min neste computador (GPU integrada), com ele livre.')
    expect(wrapper!.find('.detail__photo').attributes('src')).toBe('/api/personas/rosto/photo')
    expect(wrapper!.text()).toContain('Só a expressão da foto; sem gestos.')
    expect(http.to('POST /api/personas/rosto/preview')).toHaveLength(0) // a estimativa vem antes de qualquer job
  })

  it('os motores rápidos não mostram estimativa', async () => {
    http.set('GET /api/personas/ana/preview/estimate', { seconds: null })
    await open()
    await wrapper!.find('[data-persona="ana"] .item__main').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 400))
    await flushPromises()
    expect(wrapper!.find('[data-estimate]').exists()).toBe(false)
  })

  it('põe a realista num projeto em tela cheia', async () => {
    await open()
    await wrapper!.find('[data-persona="rosto"] .item__main').trigger('click')
    const card = wrapper!.findAll('form.preview')[1]!
    await card.findAll('select')[0]!.setValue('demo')
    await card.find('input').setValue('Oi')
    await card.trigger('submit')
    await flushPromises()
    expect(http.to('POST /api/personas/rosto/use')[0]!.body).toEqual({ project: 'demo', text: 'Oi', placement: 'segment' })
  })
})
