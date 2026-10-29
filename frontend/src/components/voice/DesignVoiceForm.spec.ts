import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { VoiceDesignOptions } from '@/api'
import { useToastsStore } from '@/stores/toasts'
import { useVoiceStore } from '@/stores/voice'
import DesignVoiceForm from './DesignVoiceForm.vue'

const OPTIONS: VoiceDesignOptions = {
  gender: [
    { value: 'female', label: 'feminino' },
    { value: 'male', label: 'masculino' },
  ],
  age: [{ value: 'middle-aged', label: 'meia-idade' }],
  pitch: [{ value: 'low pitch', label: 'grave' }],
  accent: [{ value: 'british accent', label: 'britânico' }],
  languages: [
    { value: 'pt', label: 'Português' },
    { value: 'en', label: 'Inglês' },
  ],
}
const BRANDS = [{ value: 'medlycare', label: 'MedlyCare' }]

interface Call {
  method: string
  url: string
  body: Record<string, unknown> | undefined
}

let calls: Call[]
let designReply: () => Response
let wrapper: VueWrapper | null = null

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  calls = []
  designReply = () => new Response(JSON.stringify({ id: 'narradora', name: 'Narradora', kind: 'design' }))
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string, init: RequestInit = {}) => {
      calls.push({
        method: init.method ?? 'GET',
        url,
        body: init.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : undefined,
      })
      return Promise.resolve(url === '/api/voices/design' ? designReply() : new Response('[]'))
    }),
  )
  wrapper = mount(DesignVoiceForm, { props: { options: OPTIONS, brands: BRANDS } })
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.unstubAllGlobals()
})

const select = (label: string) =>
  wrapper!.findAll('select').find((node) => wrapper!.find(`label[for="${node.attributes('id')}"]`).text() === label)!
const posted = () => calls.find((call) => call.url === '/api/voices/design')

describe('DesignVoiceForm', () => {
  it('tem os campos de desenho, mais a voz sussurrada e a descrição livre', () => {
    const labels = wrapper!.findAll('label').map((node) => node.text().replace(' *', ''))
    expect(labels).toEqual([
      'Nome da voz',
      'Gênero',
      'Faixa etária',
      'Tom',
      'Sotaque',
      'Idioma',
      'Marca',
      'Voz sussurrada',
      'Descrição livre (opcional)',
    ])
  })

  it('os selects trazem as opções do servidor, com "Não definir" na frente', () => {
    expect(select('Gênero').findAll('option').map((node) => node.text())).toEqual([
      'Não definir',
      'feminino',
      'masculino',
    ])
    expect(select('Idioma').findAll('option').map((node) => node.text())).toEqual(['Português', 'Inglês'])
    expect(select('Marca').findAll('option').map((node) => node.text())).toEqual([
      'Sem marca (serve para qualquer uma)',
      'MedlyCare',
    ])
  })

  it('sem nome pede o nome no campo e não chama o servidor', async () => {
    await wrapper!.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper!.find('[role="alert"]').text()).toBe('Dê um nome para a voz.')
    expect(posted()).toBeUndefined()
  })

  it('cria a voz com o que foi escolhido, escolhe a nova e limpa só o nome', async () => {
    await wrapper!.find('input[type="text"]').setValue('  Narradora  ')
    await select('Gênero').setValue('female')
    await select('Faixa etária').setValue('middle-aged')
    await select('Tom').setValue('low pitch')
    await select('Sotaque').setValue('british accent')
    await select('Idioma').setValue('en')
    await select('Marca').setValue('medlycare')
    await wrapper!.find('input[type="checkbox"]').setValue(true)
    await wrapper!.findAll('input[type="text"]')[1]!.setValue('warm voice')
    await wrapper!.find('form').trigger('submit')
    await flushPromises()

    expect(posted()?.body).toEqual({
      name: 'Narradora',
      gender: 'female',
      age: 'middle-aged',
      pitch: 'low pitch',
      accent: 'british accent',
      whisper: true,
      instruct: 'warm voice',
      brand: 'medlycare',
      language: 'en',
    })
    expect(useVoiceStore().selectedVoiceId).toBe('narradora')
    expect(useToastsStore().items[0]).toMatchObject({ tone: 'success', title: 'Voz "Narradora" criada' })
    expect((wrapper!.find('input[type="text"]').element as HTMLInputElement).value).toBe('')
    expect((select('Gênero').element as HTMLSelectElement).value).toBe('female')
  })

  it('campos que ficaram em "Não definir" vão como nulos', async () => {
    await wrapper!.find('input[type="text"]').setValue('Simples')
    await wrapper!.find('form').trigger('submit')
    await flushPromises()
    expect(posted()?.body).toMatchObject({
      gender: null,
      age: null,
      pitch: null,
      accent: null,
      instruct: null,
      brand: null,
      whisper: false,
      language: 'pt',
    })
  })

  it('a descrição livre explica que vale no lugar dos outros campos', async () => {
    expect(wrapper!.text()).not.toContain('vale no lugar')
    await wrapper!.findAll('input[type="text"]')[1]!.setValue('female, low pitch')
    expect(wrapper!.text()).toContain('ela vale no lugar de gênero, idade, tom e sotaque')
  })

  it('uma recusa do servidor vira aviso de erro e o nome fica para corrigir', async () => {
    designReply = () => new Response('{"detail":"Já existe uma voz com esse nome."}', { status: 400 })
    await wrapper!.find('input[type="text"]').setValue('Narradora')
    await wrapper!.find('form').trigger('submit')
    await flushPromises()
    expect(useToastsStore().items[0]).toMatchObject({
      tone: 'error',
      title: 'Não consegui criar a voz',
      description: 'Já existe uma voz com esse nome.',
    })
    expect((wrapper!.find('input[type="text"]').element as HTMLInputElement).value).toBe('Narradora')
    expect(useVoiceStore().selectedVoiceId).toBe('')
  })
})
