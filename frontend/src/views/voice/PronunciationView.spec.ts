import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { createMemoryHistory, RouterView } from 'vue-router'
import type { PronunciationEntry } from '@/api'
import ConfirmHost from '@/components/ui/ConfirmHost.vue'
import { createAppRouter } from '@/router'
import { FakeEventSource } from '@/test/fetch'
import { buttonLabelled, callsTo, press, type ServerCall } from '@/test/speechServer'
import { NARRATION_RESULT, stubVoiceServer, type VoiceServer } from '@/test/voiceServer'

const DMAKER: PronunciationEntry = { term: 'DMaker', spoken: 'Di-mêiker', scope: 'global', language: 'pt' }
const API: PronunciationEntry = { term: 'API', spoken: 'ei-pi-ai', scope: 'medlycare', language: 'en' }

let server: VoiceServer
let calls: ServerCall[]
let wrapper: VueWrapper | null = null

beforeEach(() => {
  localStorage.clear()
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
  server = stubVoiceServer({ pronunciation: [DMAKER, API] })
  calls = server.calls
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

/** A tela na rota de verdade, com o diálogo de confirmação que a casca do app monta (Remover pergunta antes). */
async function openPronunciation(): Promise<VueWrapper> {
  setActivePinia(createPinia())
  const router = createAppRouter(createMemoryHistory())
  await router.push('/voz/pronuncia')
  await router.isReady()
  const Host = defineComponent({ render: () => [h(RouterView), h(ConfirmHost)] })
  wrapper = mount(Host, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

/** O campo ligado ao rótulo (o `for` do rótulo aponta o `id` do campo). */
function field(label: string) {
  const owner = wrapper!.findAll('label').find((node) => node.text().startsWith(label))
  if (!owner) throw new Error(`campo "${label}" não encontrado`)
  return wrapper!.find(`#${owner.attributes('for')}`)
}

const row = (term: string) => wrapper!.find(`[data-term="${term}"]`)
const rowButton = (term: string, label: string) => row(term).findAll('button').find((node) => node.text() === label)!

describe('PronunciationView (/voz/pronuncia)', () => {
  it('lista os termos com o idioma e onde valem, sob o título e as abas da Voz', async () => {
    await openPronunciation()
    expect(wrapper!.find('h1').text()).toBe('Voz')
    expect(wrapper!.find('nav[aria-label="Seções da Voz"] a.is-active').text()).toBe('Pronúncia')
    expect(wrapper!.text()).not.toContain('em construção')

    expect(row('DMaker').text()).toContain('DMaker')
    expect(row('DMaker').text()).toContain('Di-mêiker')
    expect(row('DMaker').text()).toContain('Idioma: Português · Vale em: Todas as marcas')
    expect(row('API').text()).toContain('Idioma: Inglês · Vale em: MedlyCare')
  })

  it('o dicionário abre no global e muda para o de uma marca', async () => {
    await openPronunciation()
    const select = field('Dicionário').element as HTMLSelectElement
    expect([...select.options].map((option) => option.text)).toEqual(['Global (todas as marcas)', 'Padrão', 'MedlyCare'])
    expect(calls.some((call) => call.url === '/api/voices/pronunciation')).toBe(true)

    await field('Dicionário').setValue('medlycare')
    await flushPromises()
    expect(calls.at(-1)!.url).toBe('/api/voices/pronunciation?brand=medlycare')
  })

  it('sem termos, mostra o convite para adicionar o primeiro', async () => {
    server = stubVoiceServer({ pronunciation: [] })
    await openPronunciation()
    expect(wrapper!.text()).toContain('Nenhum termo ainda')
  })

  it('a falha ao ler o dicionário aparece como alerta, com como tentar de novo', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'léxico ilegível' }), { status: 500 })))
    await openPronunciation()
    expect(wrapper!.find('[role="alert"]').text()).toContain('léxico ilegível')
    expect(buttonLabelled(wrapper!, 'Tentar de novo')).toBeTruthy()
  })

  describe('adicionar', () => {
    it('o botão só liga com o termo e como falá-lo', async () => {
      await openPronunciation()
      expect(buttonLabelled(wrapper!, 'Adicionar').attributes('disabled')).toBeDefined()
      await field('Termo').setValue('Pix')
      expect(buttonLabelled(wrapper!, 'Adicionar').attributes('disabled')).toBeDefined()
      await field('Falar como').setValue('piques')
      expect(buttonLabelled(wrapper!, 'Adicionar').attributes('disabled')).toBeUndefined()
    })

    it('manda o termo no dicionário aberto e o mostra na lista, com o formulário limpo', async () => {
      await openPronunciation()
      await field('Dicionário').setValue('medlycare')
      await flushPromises()
      await field('Termo').setValue('Pix')
      await field('Falar como').setValue('piques')
      await field('Idioma da fala').setValue('en')
      await press(wrapper!, 'Adicionar')
      await flushPromises()

      expect(callsTo(calls, 'POST', '/api/voices/pronunciation')[0]!.body).toEqual({
        term: 'Pix',
        spoken: 'piques',
        brand: 'medlycare',
        language: 'en',
      })
      expect(row('Pix').exists()).toBe(true)
      expect((field('Termo').element as HTMLInputElement).value).toBe('')
      expect((field('Falar como').element as HTMLInputElement).value).toBe('')
    })
  })

  describe('remover', () => {
    const confirmDialog = () => document.body.querySelector('[role="alertdialog"]') as HTMLElement | null
    const answer = async (label: string) => {
      const button = [...confirmDialog()!.querySelectorAll('button')].find((node) => node.textContent?.trim() === label)!
      button.click()
      await flushPromises()
    }

    it('pergunta antes e só tira o termo se a pessoa confirmar', async () => {
      await openPronunciation()
      await rowButton('DMaker', 'Remover').trigger('click')
      await flushPromises()
      expect(confirmDialog()?.textContent).toContain('Tirar "DMaker" do dicionário?')
      expect(confirmDialog()?.textContent).toContain('Idioma: Português')

      await answer('Cancelar')
      expect(callsTo(calls, 'DELETE', '/api/voices/pronunciation?term=DMaker&language=pt')).toHaveLength(0)
      expect(row('DMaker').exists()).toBe(true)

      await rowButton('DMaker', 'Remover').trigger('click')
      await flushPromises()
      await answer('Tirar')
      expect(callsTo(calls, 'DELETE', '/api/voices/pronunciation?term=DMaker&language=pt')).toHaveLength(1)
      expect(row('DMaker').exists()).toBe(false)
      expect(row('API').exists()).toBe(true)
    })
  })

  describe('ouvir', () => {
    it('gera a frase do termo com a voz da Narração, troca o botão por "Gerando..." e toca o resultado', async () => {
      const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue()
      localStorage.setItem('dmaker.voice.lastVoice', 'dora')
      await openPronunciation()

      await rowButton('DMaker', 'Ouvir').trigger('click')
      await flushPromises()
      expect(callsTo(calls, 'POST', '/api/voices/speak')[0]!.body).toEqual({
        text: 'Eu falo DMaker. Repito: DMaker.',
        voice: 'dora',
        language: 'pt',
        brand: null,
        seed: 1,
      })
      expect(rowButton('DMaker', 'Gerando...').attributes('disabled')).toBeDefined()
      expect(wrapper!.text()).toContain('Ouvir gera uma frase curta com Dora (feminina)')

      FakeEventSource.latest().emit({ kind: 'end', t: 5, status: 'done', error: null, result: NARRATION_RESULT })
      await flushPromises()
      expect(wrapper!.find('audio').attributes('src')).toContain(NARRATION_RESULT.audio_url)
      expect(wrapper!.find('audio').attributes('aria-label')).toBe('Como a voz fala DMaker')
      expect(play).toHaveBeenCalled()
      expect(rowButton('DMaker', 'Ouvir').attributes('disabled')).toBeUndefined()
    })

    it('usa o dicionário da marca aberta ao gerar a frase', async () => {
      await openPronunciation()
      await field('Dicionário').setValue('medlycare')
      await flushPromises()
      await rowButton('API', 'Ouvir').trigger('click')
      await flushPromises()
      expect(callsTo(calls, 'POST', '/api/voices/speak')[0]!.body).toMatchObject({
        text: 'I say API. Again: API.',
        language: 'en',
        brand: 'medlycare',
      })
    })
  })
})
