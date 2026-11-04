import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAudioPanelStore } from '@/stores/audioPanel'
import EditorSlot from './EditorSlot.vue'
import { AUDIO_PANEL, EDITOR_PANELS, type EditorPanelDef } from './panels'

// os painéis de verdade precisam de um projeto aberto; aqui só interessa qual deles o encaixe escolhe
vi.mock('./panels', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./panels')>()
  const fake = (name: string) => ({ template: `<div data-fake="${name}" />` })
  return { ...actual, componentOf: (panel: EditorPanelDef) => fake(panel.id) }
})

let wrapper: VueWrapper | null = null

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

const panelDef = (id: string): EditorPanelDef => EDITOR_PANELS.find((panel) => panel.id === id) as EditorPanelDef

describe('o encaixe da linha do tempo', () => {
  it('mostra a linha do tempo e, com o painel Áudio aberto, mostra o painel Áudio no mesmo lugar', async () => {
    const audio = useAudioPanelStore()
    wrapper = mount(EditorSlot, { props: { panel: panelDef('timeline') } })
    await flushPromises()
    expect(wrapper.find('[data-fake="timeline"]').exists()).toBe(true)
    expect(wrapper.attributes('data-audio-open')).toBeUndefined()
    audio.open = true
    await flushPromises()
    expect(wrapper.find('[data-fake="audio"]').exists()).toBe(true)
    expect(wrapper.find('[data-fake="timeline"]').exists()).toBe(false)
    expect(wrapper.attributes('data-audio-open')).toBe('1')
    expect(wrapper.attributes('aria-label')).toBe('Áudio')
    // "voltar à linha do tempo": fechar o painel traz a linha do tempo de volta
    audio.open = false
    await flushPromises()
    expect(wrapper.find('[data-fake="timeline"]').exists()).toBe(true)
  })

  it('os outros encaixes não trocam de painel', async () => {
    useAudioPanelStore().open = true
    wrapper = mount(EditorSlot, { props: { panel: panelDef('media') } })
    await flushPromises()
    expect(wrapper.find('[data-fake="media"]').exists()).toBe(true)
    expect(wrapper.find('[data-fake="audio"]').exists()).toBe(false)
  })
})

describe('o painel Áudio no registro', () => {
  it('não é um painel do layout: os oito painéis e o formato salvo (que a clássica lê) não mudam', () => {
    expect(EDITOR_PANELS.map((panel) => panel.id)).not.toContain('audio')
    expect(AUDIO_PANEL.id).toBe('audio')
    expect(AUDIO_PANEL.load).toBeTypeOf('function')
    expect(AUDIO_PANEL.title).not.toMatch(/[—–]/)
  })
})
