import { afterEach, describe, expect, it, vi } from 'vitest'
import { mountEditorPart, openEditor } from '@/test/editorMount'
import OutputSection from './OutputSection.vue'

afterEach(() => vi.unstubAllGlobals())

describe('OutputSection', () => {
  it('lista os formatos e as marcas do servidor e mostra os valores da spec', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(OutputSection, opened)
    const selects = wrapper.findAll('select')
    // formato, qualidade, encoder, marca
    expect(selects).toHaveLength(4)
    expect(selects[0]?.findAll('option').map((o) => o.text())).toEqual([
      'Instagram · Reels (instagram/reels)',
      'YouTube · Vídeo (youtube/video)',
    ])
    expect((selects[1]?.element as HTMLSelectElement).value).toBe('high')
    expect((selects[2]?.element as HTMLSelectElement).value).toBe('x264')
    expect(selects[3]?.findAll('option').map((o) => o.text())).toEqual(['Nenhuma', 'MedlyCare'])
    expect((selects[3]?.element as HTMLSelectElement).value).toBe('medlycare')
  })

  it('qualidade e encoder trazem as opções que o schema tem, inclusive as que a interface antiga não tinha', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(OutputSection, opened)
    const selects = wrapper.findAll('select')
    expect(selects[1]?.findAll('option').map((o) => o.text())).toContain('Máxima (mais lenta)')
    expect(selects[2]?.findAll('option').map((o) => o.text())).toContain('Automático (placa de vídeo, se houver)')
  })

  it('muda formato, qualidade, FPS, marca e guias na spec', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(OutputSection, opened)
    const selects = wrapper.findAll('select')
    await selects[0]?.setValue('youtube/video')
    await selects[1]?.setValue('draft')
    await selects[2]?.setValue('nvenc')
    await selects[3]?.setValue('')
    await wrapper.find('input[type="number"]').setValue('24')
    await wrapper.find('input[type="checkbox"]').setValue(true)
    expect(opened.store.get('output')).toMatchObject({ preset: 'youtube/video', quality: 'draft', encoder: 'nvenc', fps: 24, guides: true })
    expect(opened.store.spec).not.toHaveProperty('brand')
  })

  it('o FPS é opcional: vazio apaga a chave', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(OutputSection, opened)
    const fps = wrapper.find('input[type="number"]')
    await fps.setValue('30')
    expect(opened.store.get('output.fps')).toBe(30)
    await fps.setValue('')
    expect(opened.store.get('output')).not.toHaveProperty('fps')
  })

  it('o bloco recolhe e abre', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(OutputSection, opened)
    await wrapper.find('.section__toggle').trigger('click')
    expect(wrapper.find('select').exists()).toBe(false)
  })
})
