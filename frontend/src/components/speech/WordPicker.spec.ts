import { mount, type VueWrapper } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { SpeechWord } from '@/api'
import type { WordSelection } from '@/lib/speech'
import WordPicker from './WordPicker.vue'

const WORDS: SpeechWord[] = [
  { start: 1.0, end: 1.4, text: 'Hoje' },
  { start: 1.4, end: 1.9, text: 'é' },
  { start: 2.5, end: 3.0, text: 'o' },
  { start: 3.0, end: 3.6, text: 'casamento' },
  { start: 5.0, end: 5.4, text: 'Depois' },
]

/** Monta com `v-model` de verdade: o que o componente emite volta como `modelValue`. */
function mountPicker(): { wrapper: VueWrapper; picked: () => WordSelection | null } {
  const wrapper = mount(WordPicker, {
    props: {
      words: WORDS,
      modelValue: null,
      'onUpdate:modelValue': (value: WordSelection | null) => wrapper.setProps({ modelValue: value }),
    },
  })
  return { wrapper, picked: () => wrapper.props('modelValue') as WordSelection | null }
}

const word = (wrapper: VueWrapper, text: string) => wrapper.findAll('button.word').find((node) => node.text() === text)!

describe('WordPicker', () => {
  it('agrupa as palavras por fôlego, cada linha com o tempo da primeira', () => {
    const { wrapper } = mountPicker()
    const lines = wrapper.findAll('.picker__line')
    expect(lines.map((line) => line.find('.picker__time').text())).toEqual(['1,0 s', '2,5 s', '5,0 s'])
    expect(lines.map((line) => line.findAll('button').map((node) => node.text()))).toEqual([
      ['Hoje', 'é'],
      ['o', 'casamento'],
      ['Depois'],
    ])
  })

  it('cada palavra diz o seu tempo exato', () => {
    const { wrapper } = mountPicker()
    expect(word(wrapper, 'casamento').attributes('title')).toBe('3,00 a 3,60 s')
  })

  it('usa a pausa que o servidor mandou', () => {
    const wrapper = mount(WordPicker, { props: { words: WORDS, pauseSeconds: 1, modelValue: null } })
    expect(wrapper.findAll('.picker__line')).toHaveLength(2)
  })

  it('o primeiro clique marca a palavra e pede a última', async () => {
    const { wrapper, picked } = mountPicker()
    expect(wrapper.find('[role="status"]').text()).toBe('Nenhum trecho escolhido.')
    await word(wrapper, 'o').trigger('click')
    expect(wrapper.find('[role="status"]').text()).toBe('Agora clique na última palavra do trecho.')
    expect(word(wrapper, 'o').classes()).toContain('is-anchor')
    expect(picked()).toBeNull()
  })

  it('o segundo clique escolhe o trecho todo e o deixa visível', async () => {
    const { wrapper, picked } = mountPicker()
    await word(wrapper, 'o').trigger('click')
    await word(wrapper, 'casamento').trigger('click')
    expect(picked()).toEqual({ first: 2, last: 3, start: 2.5, end: 3.6, text: 'o casamento' })
    expect(wrapper.find('[role="status"]').text()).toBe('Trecho escolhido: "o casamento" (2,50 a 3,60 s)')
    expect(word(wrapper, 'o').classes()).toContain('is-selected')
    expect(word(wrapper, 'casamento').classes()).toContain('is-selected')
    expect(word(wrapper, 'Hoje').classes()).not.toContain('is-selected')
    expect(word(wrapper, 'casamento').attributes('aria-pressed')).toBe('true')
  })

  it('a última antes da primeira também funciona', async () => {
    const { wrapper, picked } = mountPicker()
    await word(wrapper, 'casamento').trigger('click')
    await word(wrapper, 'Hoje').trigger('click')
    expect(picked()).toMatchObject({ first: 0, last: 3, text: 'Hoje é o casamento' })
  })

  it('clicar duas vezes na mesma palavra escolhe só ela', async () => {
    const { wrapper, picked } = mountPicker()
    await word(wrapper, 'Depois').trigger('click')
    await word(wrapper, 'Depois').trigger('click')
    expect(picked()).toMatchObject({ first: 4, last: 4, text: 'Depois' })
  })

  it('um clique depois de escolher recomeça o trecho', async () => {
    const { wrapper, picked } = mountPicker()
    await word(wrapper, 'o').trigger('click')
    await word(wrapper, 'casamento').trigger('click')
    await word(wrapper, 'Hoje').trigger('click')
    expect(picked()).toBeNull()
    expect(word(wrapper, 'Hoje').classes()).toContain('is-anchor')
    expect(word(wrapper, 'casamento').classes()).not.toContain('is-selected')
  })

  it('uma transcrição nova esquece o clique que ficou pela metade', async () => {
    const { wrapper } = mountPicker()
    await word(wrapper, 'o').trigger('click')
    await wrapper.setProps({ words: [{ start: 0, end: 1, text: 'Outra' }] })
    expect(wrapper.find('[role="status"]').text()).toBe('Nenhum trecho escolhido.')
  })
})
