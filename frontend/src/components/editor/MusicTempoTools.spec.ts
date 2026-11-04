import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { projectSpec } from '@/test/editorFixtures'
import { mountEditorPart, openEditor } from '@/test/editorMount'
import { reply } from '@/test/routedFetch'
import MusicTempoTools from './MusicTempoTools.vue'

const detection = { source: 'loop.wav', bpm: 100, beat_offset: 0.12, confidence: 0.98, alternatives: [50, 200], warnings: [] }
const musicSpec = () => ({ ...projectSpec(), audio: { music: { src: 'loop.wav', volume: 0.3 } } })

let wrapper: Awaited<ReturnType<typeof mountEditorPart>> | null = null

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

const find = (label: string) => (wrapper as NonNullable<typeof wrapper>).findAll('button').find((candidate) => candidate.text() === label)

describe('Detectar BPM', () => {
  it('pede o andamento do arquivo e preenche os campos da música com o valor sugerido', async () => {
    const opened = await openEditor(musicSpec(), { 'POST /api/projects/demo/audio-tempo/detect': () => detection })
    wrapper = await mountEditorPart(MusicTempoTools, opened)
    await find('Detectar BPM')?.trigger('click')
    await flushPromises()
    expect(opened.fetch.to('POST /api/projects/demo/audio-tempo/detect')).toHaveLength(1)
    expect(opened.store.get('audio.music.bpm')).toBe(100)
    expect(opened.store.get('audio.music.beat_offset')).toBe(0.12)
    expect(wrapper.find('[data-detect-result]').text()).toContain('100 BPM')
    expect(wrapper.find('[data-detect-result]').text()).toContain('0,98')
  })

  it('a mudança entra no desfazer do editor, como qualquer outra', async () => {
    const opened = await openEditor(musicSpec(), { 'POST /api/projects/demo/audio-tempo/detect': () => detection })
    wrapper = await mountEditorPart(MusicTempoTools, opened)
    await find('Detectar BPM')?.trigger('click')
    await flushPromises()
    expect(opened.store.dirty).toBe(true)
    opened.store.undo()
    expect(opened.store.get('audio.music.bpm')).toBeUndefined()
  })

  it('oferece a metade e o dobro quando o ouvido marca outro tempo, sem mexer no primeiro tempo', async () => {
    const opened = await openEditor(musicSpec(), { 'POST /api/projects/demo/audio-tempo/detect': () => detection })
    wrapper = await mountEditorPart(MusicTempoTools, opened)
    await find('Detectar BPM')?.trigger('click')
    await flushPromises()
    await find('50 BPM')?.trigger('click')
    expect(opened.store.get('audio.music.bpm')).toBe(50)
    expect(opened.store.get('audio.music.beat_offset')).toBe(0.12)
    expect(find('200 BPM')).toBeDefined()
  })

  it('mostra o aviso de confiança baixa que o servidor mandou', async () => {
    const weak = { ...detection, confidence: 0.12, warnings: ['confiança baixa (0.12): confira o valor de ouvido'] }
    const opened = await openEditor(musicSpec(), { 'POST /api/projects/demo/audio-tempo/detect': () => weak })
    wrapper = await mountEditorPart(MusicTempoTools, opened)
    await find('Detectar BPM')?.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('confiança baixa')
  })

  it('o erro do servidor aparece e nada é gravado na spec', async () => {
    const opened = await openEditor(musicSpec(), {
      'POST /api/projects/demo/audio-tempo/detect': () => reply(404, { detail: 'arquivo não encontrado: loop.wav' }),
    })
    wrapper = await mountEditorPart(MusicTempoTools, opened)
    await find('Detectar BPM')?.trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-detect-error]').text()).toContain('arquivo não encontrado')
    expect(opened.store.get('audio.music.bpm')).toBeUndefined()
    expect(opened.store.dirty).toBe(false)
  })
})
