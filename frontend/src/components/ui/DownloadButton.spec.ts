import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useToastsStore } from '@/stores/toasts'
import DownloadButton from './DownloadButton.vue'

let clicked: Array<{ href: string; download: string }>

beforeEach(() => {
  setActivePinia(createPinia())
  clicked = []
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    clicked.push({ href: this.getAttribute('href') ?? '', download: this.download })
  })
})
afterEach(() => vi.restoreAllMocks())

describe('DownloadButton', () => {
  it('com endereço conhecido, baixa na hora por um link programático', async () => {
    const wrapper = mount(DownloadButton, {
      props: { url: '/api/voices/audio?path=a.wav&download=true', filename: 'voz.wav', label: 'Baixar voz' },
    })
    expect(wrapper.find('button').text()).toBe('Baixar voz')
    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(clicked).toEqual([{ href: '/api/voices/audio?path=a.wav&download=true', download: 'voz.wav' }])
    expect(wrapper.emitted('downloaded')).toEqual([['/api/voices/audio?path=a.wav&download=true']])
  })

  it('o rótulo padrão é Baixar', () => {
    expect(mount(DownloadButton, { props: { url: '/x' } }).text()).toContain('Baixar')
  })

  it('com resolve, espera o endereço (um job, por exemplo) e então baixa o .zip', async () => {
    let release: (url: string) => void = () => {}
    const resolve = vi.fn(() => new Promise<string>((done) => (release = done)))
    const wrapper = mount(DownloadButton, { props: { resolve, label: 'Baixar trilhas', filename: 'trilhas.zip' } })

    await wrapper.find('button').trigger('click')
    expect(wrapper.find('button').attributes('aria-busy')).toBe('true')
    expect(clicked).toEqual([])

    release('/api/dub/file?path=t.zip&download=true')
    await flushPromises()
    expect(clicked).toEqual([{ href: '/api/dub/file?path=t.zip&download=true', download: 'trilhas.zip' }])
    expect(wrapper.find('button').attributes('aria-busy')).toBeUndefined()
  })

  it('se produzir o endereço falha, avisa com um toast e libera o botão', async () => {
    const toasts = useToastsStore()
    const wrapper = mount(DownloadButton, { props: { resolve: () => Promise.reject(new Error('As trilhas não foram geradas.')) } })
    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(clicked).toEqual([])
    expect(toasts.items[0]).toMatchObject({ tone: 'error', description: 'As trilhas não foram geradas.' })
    expect(wrapper.find('button').attributes('disabled')).toBeUndefined()
  })

  it('sem endereço nem resolve, fica desabilitado', () => {
    expect(mount(DownloadButton).find('button').attributes('disabled')).toBeDefined()
  })

  it('desabilitado, não baixa', async () => {
    const wrapper = mount(DownloadButton, { props: { url: '/x', disabled: true } })
    await wrapper.find('button').trigger('click')
    expect(clicked).toEqual([])
  })
})
