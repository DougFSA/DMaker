import { afterEach, describe, expect, it, vi } from 'vitest'
import { projectSpec } from '@/test/editorFixtures'
import { mountEditorPart, openEditor } from '@/test/editorMount'
import AudioSection from './AudioSection.vue'

afterEach(() => vi.unstubAllGlobals())

type Mounted = Awaited<ReturnType<typeof mountEditorPart>>
const button = (wrapper: Mounted, label: string) =>
  wrapper.findAll('button').find((candidate) => candidate.attributes('aria-label') === label || candidate.text() === label)
const check = (wrapper: Mounted, label: string) =>
  wrapper.findAll('label').find((candidate) => candidate.text() === label)?.find('input')

describe('AudioSection', () => {
  it('liga a música com valores iniciais e mostra os campos dela', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(AudioSection, opened)
    expect(wrapper.text()).not.toContain('Arquivo de música')
    await check(wrapper, 'Usar música de fundo')?.setValue(true)
    expect(opened.store.get('audio.music')).toEqual({ src: '' })
    expect(wrapper.text()).toContain('Arquivo de música')
    // os padrões do schema aparecem sem gravar nada
    expect(wrapper.text()).toContain('Abaixar sob a voz')
  })

  it('desligar a música guarda null (a spec aceita)', async () => {
    const spec = { ...projectSpec(), audio: { music: { src: 'a.mp3', volume: 0.3 } } }
    const opened = await openEditor(spec)
    const wrapper = await mountEditorPart(AudioSection, opened)
    expect((wrapper.findAll('input[type="number"]')[0]?.element as HTMLInputElement).value).toBe('0.3')
    await check(wrapper, 'Usar música de fundo')?.setValue(false)
    expect(opened.store.get('audio.music')).toBeNull()
    expect(wrapper.text()).not.toContain('Arquivo de música')
  })

  it('ganho da voz, normalização e silenciar clipes', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(AudioSection, opened)
    const gain = wrapper.findAll('input[type="number"]').find((input) => input.element.closest('.field')?.textContent?.includes('Ganho da voz'))
    await gain?.setValue('1.5')
    await wrapper.find('select').setValue('off')
    await check(wrapper, 'Silenciar áudio original dos clipes')?.setValue(true)
    expect(opened.store.get('audio')).toMatchObject({ voice_gain: 1.5, normalize: 'off', mute_clips: true })
    expect(wrapper.find('select').findAll('option').map((o) => o.text())).toEqual(['Duas passadas', 'Rápida', 'Desligada'])
  })

  it('a faixa externa precisa de uma fonte sincronizada', async () => {
    const opened = await openEditor()
    const wrapper = await mountEditorPart(AudioSection, opened)
    expect(wrapper.text()).toContain('Cadastre uma fonte sincronizada')
    expect(button(wrapper, 'Adicionar faixa')?.attributes('disabled')).toBeDefined()
  })

  it('adiciona, ajusta e remove faixas externas', async () => {
    const spec = { ...projectSpec(), sources: { palco: { src: 'a.mp4' }, mesa: { src: 'b.wav' } } }
    const opened = await openEditor(spec)
    const wrapper = await mountEditorPart(AudioSection, opened)
    await button(wrapper, 'Adicionar faixa')?.trigger('click')
    expect(opened.store.get('audio.tracks')).toEqual([{ source: 'palco', volume: 1 }])
    const track = wrapper.find('li.track')
    expect(track.find('select').findAll('option').map((o) => o.text())).toEqual(['palco', 'mesa'])
    await track.find('select').setValue('mesa')
    await track.find('input[type="number"]').setValue('0.6')
    expect(opened.store.get('audio.tracks.0')).toEqual({ source: 'mesa', volume: 0.6 })
    await button(wrapper, 'Remover a faixa 1')?.trigger('click')
    expect(opened.store.get('audio.tracks')).toEqual([])
  })
})
