import { afterEach, describe, expect, it, vi } from 'vitest'
import { projectSpec } from '@/test/editorFixtures'
import { mountEditorPart, openEditor } from '@/test/editorMount'
import OutputSection from './OutputSection.vue'

afterEach(() => vi.unstubAllGlobals())

const MP3 = {
  id: 'audio/mp3',
  name: 'MP3',
  extension: '.mp3',
  lossless: false,
  sample_rate: 48000,
  channels: 2,
  bit_depths: [],
  bit_depth: null,
  bitrate_modes: ['cbr', 'vbr', 'abr'],
  bitrate_mode: 'cbr',
  bitrate_k: 192,
  quality: 2,
  quality_range: [0, 9],
  allowed_sample_rates: [],
  default_label: 'CBR 192 kbps',
  notes: '',
}
const WAV = { ...MP3, id: 'audio/wav', name: 'WAV', lossless: true, bit_depths: [16, 24, 32], bit_depth: 16, bitrate_modes: [], bitrate_mode: null, bitrate_k: null, quality: null, default_label: '16 bits' }

const STATE = {
  'GET /api/state': {
    presets: [{ id: 'instagram/reels', platform: 'Instagram', name: 'Reels', width: 1080, height: 1920, fps: 30 }],
    audio_presets: [MP3, WAV],
    loudness_targets: { redes: -14, podcast: -16, broadcast: -23 },
    brands: [],
  },
}

const audioSpec = (preset: string) => ({ ...projectSpec(), output: { preset } })

describe('OutputSection com um formato só de áudio', () => {
  it('lista os formatos de áudio ao lado dos de vídeo', async () => {
    const opened = await openEditor(projectSpec(), STATE)
    const wrapper = await mountEditorPart(OutputSection, opened)
    expect(wrapper.findAll('select')[0]?.findAll('option').map((o) => o.text())).toEqual([
      'Instagram · Reels (instagram/reels)',
      'Áudio · MP3 (audio/mp3)',
      'Áudio · WAV (audio/wav)',
    ])
  })

  it('no vídeo não aparece nada de áudio', async () => {
    const opened = await openEditor(projectSpec(), STATE)
    const wrapper = await mountEditorPart(OutputSection, opened)
    expect(wrapper.text()).not.toContain('Etiquetas do arquivo')
    expect(wrapper.text()).not.toContain('Volume de saída')
  })

  it('com MP3 troca a imagem pela taxa de bits, o volume de saída e as etiquetas', async () => {
    const opened = await openEditor(audioSpec('audio/mp3'), STATE)
    const wrapper = await mountEditorPart(OutputSection, opened)
    const text = wrapper.text()
    expect(text).toContain('Taxa de bits (kbps)')
    expect(text).toContain('Modo da taxa de bits')
    expect(text).toContain('Etiquetas do arquivo')
    expect(text).not.toContain('Encoder')
    expect(text).not.toContain('Profundidade')
    expect(text).not.toContain('guias de zona segura')
  })

  it('com WAV oferece a profundidade e não a taxa de bits', async () => {
    const opened = await openEditor(audioSpec('audio/wav'), STATE)
    const wrapper = await mountEditorPart(OutputSection, opened)
    expect(wrapper.text()).toContain('Profundidade')
    expect(wrapper.text()).not.toContain('Taxa de bits (kbps)')
  })

  it('grava a taxa de bits, uma etiqueta e o alvo de loudness na spec, e apagar o campo apaga a chave', async () => {
    const opened = await openEditor(audioSpec('audio/mp3'), STATE)
    const wrapper = await mountEditorPart(OutputSection, opened)
    const inputs = wrapper.findAll('input[type="text"], input:not([type])')
    const bitrate = inputs.find((input) => input.attributes('placeholder') === '192')
    await bitrate?.setValue('128')
    expect(opened.store.get('output.audio_format.bitrate_k')).toBe(128)
    await bitrate?.setValue('')
    expect(opened.store.get('output.audio_format')).not.toHaveProperty('bitrate_k')

    const artist = wrapper.findAll('label').find((label) => label.text() === 'Artista')
    const artistInput = wrapper.find(`#${artist?.attributes('for')}`)
    await artistInput.setValue('Fulano')
    expect(opened.store.get('output.metadata.artist')).toBe('Fulano')

    const loudness = wrapper.findAll('select').find((select) => select.findAll('option').some((o) => o.text().startsWith('Podcast')))
    await loudness?.setValue('podcast')
    expect(opened.store.get('audio.target_lufs')).toBe(-16)
  })
})
