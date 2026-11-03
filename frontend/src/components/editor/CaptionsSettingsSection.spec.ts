import { afterEach, describe, expect, it, vi } from 'vitest'
import { projectSpec } from '@/test/editorFixtures'
import { mountEditorPart, openEditor } from '@/test/editorMount'
import CaptionsSettingsSection from './CaptionsSettingsSection.vue'

afterEach(() => vi.unstubAllGlobals())

describe('CaptionsSettingsSection', () => {
  it('sem legendas, só a caixa de ligar', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(CaptionsSettingsSection, opened)
    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(true)
    expect(wrapper.find('select').exists()).toBe(false)
  })

  it('ligar cria a configuração inicial e mostra origem, idioma, modelo e estilo', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(CaptionsSettingsSection, opened)
    await wrapper.find('input[type="checkbox"]').setValue(true)
    expect(opened.store.get('captions')).toEqual({ source: 'auto', language: 'pt', model: 'small' })
    expect(wrapper.text()).toContain('Origem (auto ou caminho .srt)')
    const selects = wrapper.findAll('select')
    expect(selects[0]?.findAll('option').map((o) => o.text())).toEqual(['Tiny', 'Base', 'Small', 'Medium', 'Large v3'])
    expect((selects[0]?.element as HTMLSelectElement).value).toBe('small')
    expect(selects[1]?.findAll('option').map((o) => o.text())).toEqual(['Karaokê', 'Clássico', 'Caixa', 'Caixa arredondada'])
  })

  it('edita os campos do estilo e desliga com null', async () => {
    const spec = { ...projectSpec(), captions: { source: 'auto', language: 'pt', model: 'small', style: { mode: 'karaoke', max_words: 4 } } }
    const opened = await openEditor(spec)
    const wrapper = await mountEditorPart(CaptionsSettingsSection, opened)
    await wrapper.findAll('select')[1]?.setValue('rounded')
    await wrapper.findAll('input[type="number"]')[0]?.setValue('6')
    expect(opened.store.get('captions.style')).toMatchObject({ mode: 'rounded', max_words: 6 })
    await wrapper.find('input[type="checkbox"]').setValue(false)
    expect(opened.store.get('captions')).toBeNull()
  })
})
