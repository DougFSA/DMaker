import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mountEditorPart, openEditor } from '@/test/editorMount'
import PropertiesPanel from './PropertiesPanel.vue'

beforeEach(() => window.localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

const titles = (wrapper: Awaited<ReturnType<typeof mountEditorPart>>) => wrapper.findAll('h3.section__title').map((h) => h.text())

describe('PropertiesPanel', () => {
  it('mostra os seis blocos do formulário, na ordem', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(PropertiesPanel, opened)
    expect(titles(wrapper)).toEqual(['Saída', 'Fontes sincronizadas', 'Trechos', 'Sobreposições', 'Legendas', 'Áudio'])
  })

  it('cada bloco mostra quantos itens tem', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(PropertiesPanel, opened)
    const counts = wrapper.findAll('.section__toggle').map((toggle) => toggle.text())
    expect(counts.find((text) => text.startsWith('Trechos'))).toContain('2')
    expect(counts.find((text) => text.startsWith('Sobreposições'))).toContain('1')
    expect(counts.find((text) => text.startsWith('Fontes'))).toContain('0')
  })

  it('o bloco que a pessoa fecha continua fechado na próxima vez', async () => {
    const opened = await openEditor()
    const first = await mountEditorPart(PropertiesPanel, opened)
    const saida = first.findAll('.section__toggle').find((toggle) => toggle.text().startsWith('Saída'))
    await saida?.trigger('click')
    await flushPromises()
    first.unmount()
    expect(JSON.parse(window.localStorage.getItem('dmaker.editor.sections') ?? '{}')).toMatchObject({ output: false, segments: true })

    const second = await mountEditorPart(PropertiesPanel, opened)
    expect(second.findAll('.section__toggle').find((toggle) => toggle.text().startsWith('Saída'))?.attributes('aria-expanded')).toBe('false')
    expect(second.findAll('.section__toggle').find((toggle) => toggle.text().startsWith('Trechos'))?.attributes('aria-expanded')).toBe('true')
  })

  it('preferência ilegível no navegador deixa todos os blocos abertos', async () => {
    window.localStorage.setItem('dmaker.editor.sections', '{não é json')
    const opened = await openEditor()
    const wrapper = await mountEditorPart(PropertiesPanel, opened)
    expect(wrapper.findAll('.section__toggle').every((toggle) => toggle.attributes('aria-expanded') === 'true')).toBe(true)
  })

  it('uma mudança no formulário aparece em outro bloco que lê o mesmo dado', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(PropertiesPanel, opened)
    // renomear a fonte principal em "Fontes" não existe sem fonte; usa o rótulo do trecho, que o resumo do cartão mostra
    const label = wrapper.findAll('input').find((input) => input.element.closest('.field')?.textContent?.includes('Rótulo (opcional)'))
    await label?.setValue('abertura')
    expect(wrapper.find('.card__summary').text()).toBe('abertura')
  })
})
