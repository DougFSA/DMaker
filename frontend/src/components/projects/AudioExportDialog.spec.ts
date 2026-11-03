import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AudioExportRequest } from '@/api'
import { useCatalogStore } from '@/stores/catalog'
import { routedFetch } from '@/test/routedFetch'
import AudioExportDialog from './AudioExportDialog.vue'

let wrapper: VueWrapper | null = null
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.unstubAllGlobals()
})

const base = {
  sample_rate: 48000,
  channels: 2,
  quality_range: [0, 9],
  allowed_sample_rates: [],
  notes: '',
  lossless: false,
  quality: null,
  bitrate_k: null,
}
const MP3 = { ...base, id: 'audio/mp3', name: 'MP3', extension: '.mp3', bit_depths: [], bit_depth: null, bitrate_modes: ['cbr', 'vbr', 'abr'], bitrate_mode: 'cbr', bitrate_k: 192, quality: 2, default_label: 'CBR 192 kbps' }
const WAV = { ...base, id: 'audio/wav', name: 'WAV', extension: '.wav', lossless: true, bit_depths: [16, 24, 32], bit_depth: 16, bitrate_modes: [], bitrate_mode: null, default_label: '16 bits' }

const dialog = () => document.body.querySelector('[role="dialog"]') as HTMLElement | null
const labelled = (text: string) =>
  Array.from(dialog()?.querySelectorAll('label') ?? []).find((label) => label.textContent?.trim().startsWith(text))
const control = <T extends HTMLElement>(text: string) => dialog()?.querySelector<T>(`#${labelled(text)?.getAttribute('for')}`) ?? null
const button = (text: string) =>
  Array.from(dialog()?.querySelectorAll('button') ?? []).find((node) => node.textContent?.trim() === text) as HTMLButtonElement | undefined

async function open(currentPreset: string | null = 'audio/mp3') {
  const pinia = createPinia()
  setActivePinia(pinia)
  routedFetch({
    'GET /api/state': {
      presets: [],
      audio_presets: [MP3, WAV],
      loudness_targets: { redes: -14, podcast: -16, broadcast: -23 },
      brands: [],
      projects: [],
    },
    'GET /api/templates': [],
  })
  await useCatalogStore().load()
  const submitted: AudioExportRequest[] = []
  wrapper = mount(AudioExportDialog, {
    props: { projectName: 'ep', currentPreset, open: false, 'onUpdate:open': () => undefined, onSubmit: (r: AudioExportRequest) => submitted.push(r) },
    global: { plugins: [pinia] },
    attachTo: document.body,
  })
  await wrapper.setProps({ open: true })
  await flushPromises()
  return submitted
}

describe('AudioExportDialog', () => {
  it('abre no formato do projeto quando ele já é de áudio, com os modos e os alvos de loudness', async () => {
    await open('audio/wav')
    expect(control<HTMLSelectElement>('Formato do arquivo')?.value).toBe('audio/wav')
    expect(dialog()?.textContent).toContain('Uma região por arquivo')
    expect(Array.from(control<HTMLSelectElement>('Volume de saída')?.options ?? []).map((o) => o.text)).toEqual([
      'Como está no projeto',
      'Redes (-14 LUFS)',
      'Podcast (-16 LUFS)',
      'Broadcast (EBU R128) (-23 LUFS)',
    ])
  })

  it('mostra a profundidade no WAV e a taxa de bits no MP3, e troca ao mudar de formato', async () => {
    await open('audio/mp3')
    expect(labelled('Taxa de bits')).toBeTruthy()
    expect(labelled('Profundidade')).toBeFalsy()
    const select = control<HTMLSelectElement>('Formato do arquivo')
    select!.value = 'audio/wav'
    select!.dispatchEvent(new Event('change'))
    await flushPromises()
    expect(labelled('Profundidade')).toBeTruthy()
    expect(labelled('Taxa de bits')).toBeFalsy()
  })

  it('entrega o pedido do modo escolhido e só com o que vale nele', async () => {
    const submitted = await open('audio/mp3')
    const podcast = control<HTMLSelectElement>('Volume de saída')!
    podcast.value = 'podcast'
    podcast.dispatchEvent(new Event('change'))
    const regions = dialog()!.querySelector<HTMLInputElement>('input[value="regions"]')!
    regions.checked = true
    regions.dispatchEvent(new Event('change'))
    await flushPromises()
    expect(labelled('Só o grupo')).toBeTruthy()
    button('Exportar')!.click()
    await flushPromises()
    expect(submitted).toEqual([{ preset: 'audio/mp3', mode: 'regions', loudness: 'podcast' }])
  })

  it('a seleção sem início não envia e explica', async () => {
    const submitted = await open('audio/mp3')
    const selection = dialog()!.querySelector<HTMLInputElement>('input[value="selection"]')!
    selection.checked = true
    selection.dispatchEvent(new Event('change'))
    await flushPromises()
    button('Exportar')!.click()
    await flushPromises()
    expect(submitted).toEqual([])
    expect(dialog()?.textContent).toContain('Diga onde o trecho começa')
  })
})
