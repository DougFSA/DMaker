import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { provideEditorFilePicker } from '@/composables/useEditorFilePicker'
import type { FieldDef } from '@/lib/editorFields'
import { mountEditorPart, openEditor } from '@/test/editorMount'
import SpecField from './SpecField.vue'

afterEach(() => vi.unstubAllGlobals())

const speed: FieldDef = { key: 'speed', label: 'Velocidade', kind: 'number', def: 'ClipSegment', step: 0.1 }
const end: FieldDef = { key: 'end', label: 'Fim (s, opcional)', kind: 'number', def: 'ClipSegment', optional: true }
const quality: FieldDef = { key: 'quality', label: 'Qualidade', kind: 'select', def: 'Output' }
const variant: FieldDef = { key: 'variant', label: 'Variante', kind: 'select', def: 'CardSegment', emptyLabel: 'Padrão do tema' }
const mute: FieldDef = { key: 'mute', label: 'Mudo', kind: 'check', def: 'ClipSegment' }
const title: FieldDef = { key: 'title', label: 'Título', kind: 'text', def: 'CardSegment' }

describe('SpecField: número', () => {
  it('mostra o valor da spec e os limites do schema', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(SpecField, opened, { field: speed, base: 'timeline.0' })
    const input = wrapper.find('input')
    expect((input.element as HTMLInputElement).value).toBe('1')
    expect(input.attributes('max')).toBe('8')
    expect(input.attributes('min')).toBe('0.1') // maior que zero: o menor valor que o servidor aceita é o passo
    expect(wrapper.find('label').text()).toBe('Velocidade')
  })

  it('escrever no campo muda a spec do store', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(SpecField, opened, { field: speed, base: 'timeline.0' })
    await wrapper.find('input').setValue('2.5')
    expect(opened.store.get('timeline.0.speed')).toBe(2.5)
    expect(opened.store.dirty).toBe(true)
  })

  it('esvaziar um campo opcional apaga a chave, em vez de gravar zero', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(SpecField, opened, { field: end, base: 'timeline.0' })
    expect((wrapper.find('input').element as HTMLInputElement).value).toBe('3')
    await wrapper.find('input').setValue('')
    expect(opened.store.get('timeline.0')).not.toHaveProperty('end')
  })

  it('campo que a spec não tem mostra o padrão do schema, sem gravar nada', async () => {
    const spec = { ...({} as Record<string, unknown>), name: 'demo', timeline: [{ type: 'clip', src: 'a.mp4' }] }
    const opened = await openEditor(spec)
    const wrapper = await mountEditorPart(SpecField, opened, { field: speed, base: 'timeline.0' })
    expect((wrapper.find('input').element as HTMLInputElement).value).toBe('1')
    expect(opened.store.get('timeline.0')).not.toHaveProperty('speed')
    expect(opened.store.dirty).toBe(false)
  })

  it('o campo opcional ausente fica vazio, mesmo havendo padrão no schema', async () => {
    const spec = { name: 'demo', timeline: [{ type: 'clip', src: 'a.mp4' }] }
    const opened = await openEditor(spec)
    const wrapper = await mountEditorPart(SpecField, opened, { field: end, base: 'timeline.0' })
    expect((wrapper.find('input').element as HTMLInputElement).value).toBe('')
  })
})

describe('SpecField: lista', () => {
  it('as opções saem do schema, com o rótulo em português', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(SpecField, opened, { field: quality, base: 'output' })
    const labels = wrapper.findAll('option').map((option) => option.text())
    expect(labels).toEqual(['Máxima (mais lenta)', 'Alta', 'Média', 'Rascunho'])
    expect((wrapper.find('select').element as HTMLSelectElement).value).toBe('high')
  })

  it('escolher uma opção grava o valor', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(SpecField, opened, { field: quality, base: 'output' })
    await wrapper.find('select').setValue('draft')
    expect(opened.store.get('output.quality')).toBe('draft')
  })

  it('valor novo no schema, sem rótulo cadastrado, aparece com o próprio valor', async () => {
    const opened = await openEditor()
    opened.store.schema = {
      $defs: { Output: { properties: { quality: { default: 'high', enum: ['high', 'ultra'], type: 'string' } } } },
    }
    const wrapper = await mountEditorPart(SpecField, opened, { field: quality, base: 'output' })
    expect(wrapper.findAll('option').map((option) => option.text())).toEqual(['Alta', 'ultra'])
  })

  it('lista que aceita "nenhuma" mostra a opção vazia, e escolhê-la apaga o campo', async () => {
    const spec = { name: 'demo', timeline: [{ type: 'card', title: 'x', variant: 'dark' }] }
    const opened = await openEditor(spec)
    const wrapper = await mountEditorPart(SpecField, opened, { field: variant, base: 'timeline.0' })
    expect(wrapper.findAll('option').map((option) => option.text())).toEqual(['Padrão do tema', 'Claro', 'Escuro'])
    expect((wrapper.find('select').element as HTMLSelectElement).value).toBe('dark')
    await wrapper.find('select').setValue('')
    expect(opened.store.get('timeline.0')).not.toHaveProperty('variant')
  })

  it('as opções de fora (transições do catálogo) valem no lugar das do schema', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(SpecField, opened, {
      field: { key: 'transition.type', label: 'Tipo', kind: 'select', def: 'Transition', prop: 'type', fallback: 'cut' },
      base: 'timeline.1',
      choices: [
        { value: 'cut', label: 'Corte seco' },
        { value: 'fade', label: 'Fade' },
      ],
    })
    expect(wrapper.findAll('option').map((option) => option.text())).toEqual(['Corte seco', 'Fade'])
    expect((wrapper.find('select').element as HTMLSelectElement).value).toBe('cut') // sem transição = corte seco
    await wrapper.find('select').setValue('fade')
    expect(opened.store.get('timeline.1.transition.type')).toBe('fade')
  })
})

describe('SpecField: caixa de marcar e texto', () => {
  it('marca e desmarca', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(SpecField, opened, { field: mute, base: 'timeline.0' })
    const box = wrapper.find('input[type="checkbox"]')
    expect((box.element as HTMLInputElement).checked).toBe(false)
    await box.setValue(true)
    expect(opened.store.get('timeline.0.mute')).toBe(true)
  })

  it('o texto vazio apaga o campo', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(SpecField, opened, { field: title, base: 'timeline.1' })
    expect((wrapper.find('input').element as HTMLInputElement).value).toBe('Fim')
    await wrapper.find('input').setValue('Outro')
    expect(opened.store.get('timeline.1.title')).toBe('Outro')
    await wrapper.find('input').setValue('')
    expect(opened.store.get('timeline.1')).not.toHaveProperty('title')
  })
})

describe('SpecField: arquivo', () => {
  const file: FieldDef = { key: 'src', label: 'Arquivo', kind: 'file', def: 'ClipSegment' }

  it('fora da tela do editor o campo é só o texto, sem o botão de escolher', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(SpecField, opened, { field: file, base: 'timeline.0' })
    expect((wrapper.find('input').element as HTMLInputElement).value).toBe('clip0.mp4')
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it('com o seletor da tela, o botão abre a escolha e grava o caminho', async () => {
    const opened = await openEditor()
    let resolveFromDialog: ((paths: string[]) => void) | null = null
    const Host = defineComponent({
      setup() {
        const picker = provideEditorFilePicker()
        resolveFromDialog = picker.onSelect
        return () => h(SpecField, { field: file, base: 'timeline.0' })
      },
    })
    const wrapper = mount(Host, { global: { plugins: [opened.pinia] } })
    await wrapper.find('button').trigger('click')
    expect(resolveFromDialog).not.toBeNull()
    ;(resolveFromDialog as unknown as (paths: string[]) => void)(['C:/midia/novo.mp4'])
    await flushPromises()
    expect(opened.store.get('timeline.0.src')).toBe('C:/midia/novo.mp4')
  })
})
