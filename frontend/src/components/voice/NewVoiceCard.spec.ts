import { mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { VoiceDesignOptions } from '@/api'
import NewVoiceCard from './NewVoiceCard.vue'

const OPTIONS: VoiceDesignOptions = {
  gender: [{ value: 'female', label: 'feminino' }],
  age: [],
  pitch: [],
  accent: [],
  languages: [{ value: 'pt', label: 'Português' }],
}

let wrapper: VueWrapper | null = null

beforeEach(() => {
  setActivePinia(createPinia())
  wrapper = mount(NewVoiceCard, { props: { options: OPTIONS, brands: [] } })
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

/** O `isVisible` do test-utils lê um estilo calculado velho no jsdom: confere o `display` direto. */
const shown = (selector: string) => !(wrapper!.find(selector).attributes('style') ?? '').includes('display: none')
const modeButton = (label: string) =>
  wrapper!
    .find('[aria-label="Como criar a voz"]')
    .findAll('button')
    .find((node) => node.text() === label)!

describe('NewVoiceCard', () => {
  it('abre em Clonar, com o título e o texto do cartão', () => {
    expect(wrapper!.find('h3').text()).toBe('Nova voz')
    expect(modeButton('Clonar').attributes('aria-pressed')).toBe('true')
    expect(shown('form.clone')).toBe(true)
    expect(shown('form.design')).toBe(false)
  })

  it('Desenhar mostra o outro formulário e Clonar volta ao primeiro', async () => {
    await modeButton('Desenhar').trigger('click')
    expect(shown('form.design')).toBe(true)
    expect(shown('form.clone')).toBe(false)
    await modeButton('Clonar').trigger('click')
    expect(shown('form.clone')).toBe(true)
  })

  it('os dois formulários continuam montados, então trocar de aba não apaga o que foi digitado', async () => {
    await wrapper!.find('form.design input[type="text"]').setValue('Narradora')
    await modeButton('Desenhar').trigger('click')
    await modeButton('Clonar').trigger('click')
    await modeButton('Desenhar').trigger('click')
    expect((wrapper!.find('form.design input[type="text"]').element as HTMLInputElement).value).toBe('Narradora')
  })

  it('passa os idiomas ao Clonar e as opções ao Desenhar', () => {
    expect(wrapper!.find('form.clone select').findAll('option').map((node) => node.text())).toEqual(['Português'])
    expect(wrapper!.find('form.design select').findAll('option').map((node) => node.text())).toEqual([
      'Não definir',
      'feminino',
    ])
  })
})
