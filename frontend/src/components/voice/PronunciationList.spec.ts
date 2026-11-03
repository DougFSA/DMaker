import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { PronunciationEntry } from '@/api'
import PronunciationList from './PronunciationList.vue'

const LANGUAGES = [
  { value: 'pt', label: 'Português' },
  { value: 'en', label: 'Inglês' },
]
const BRANDS = [{ value: 'medlycare', label: 'MedlyCare' }]
const DMAKER: PronunciationEntry = { term: 'DMaker', spoken: 'Di-mêiker', scope: 'global', language: 'pt' }
const API: PronunciationEntry = { term: 'API', spoken: 'ei-pi-ai', scope: 'medlycare', language: 'en' }

function mountList(listening: Record<string, true> = {}) {
  return mount(PronunciationList, { props: { entries: [DMAKER, API], languages: LANGUAGES, brands: BRANDS, listening } })
}

describe('PronunciationList', () => {
  it('cada termo mostra como se fala, o idioma e onde vale', () => {
    const items = mountList().findAll('li')
    expect(items).toHaveLength(2)
    expect(items[0]!.text()).toContain('DMaker')
    expect(items[0]!.text()).toContain('Di-mêiker')
    expect(items[0]!.text()).toContain('Idioma: Português · Vale em: Todas as marcas')
    expect(items[1]!.text()).toContain('Idioma: Inglês · Vale em: MedlyCare')
  })

  it('o leitor de tela ouve "se fala" no lugar da seta', () => {
    const first = mountList().find('li')
    expect(first.find('[aria-hidden="true"]').text()).toBe('→')
    expect(first.find('.visually-hidden').text()).toBe('se fala')
  })

  it('Ouvir e Remover avisam qual termo é', async () => {
    const wrapper = mountList()
    const second = wrapper.findAll('li')[1]!
    await second.find('button[aria-label="Ouvir como se fala API"]').trigger('click')
    await second.find('button[aria-label="Remover API"]').trigger('click')
    expect(wrapper.emitted('listen')).toEqual([[API]])
    expect(wrapper.emitted('remove')).toEqual([[API]])
  })

  it('enquanto a frase de um termo é gerada, o botão dele diz "Gerando..." e fica parado', () => {
    const wrapper = mountList({ 'pt:DMaker': true })
    const [dmaker, api] = wrapper.findAll('li')
    expect(dmaker!.find('button').text()).toBe('Gerando...')
    expect(dmaker!.find('button').attributes('disabled')).toBeDefined()
    expect(api!.find('button').text()).toBe('Ouvir')
    expect(api!.find('button').attributes('disabled')).toBeUndefined()
  })
})
