import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { projectSpec } from '@/test/editorFixtures'
import { mountEditorPart, openEditor, type OpenedEditor } from '@/test/editorMount'
import SegmentCrossfade from './SegmentCrossfade.vue'

let wrapper: VueWrapper | null = null
let opened: OpenedEditor

function twoClips(extra: Record<string, unknown> = {}): Record<string, unknown> {
  const spec = projectSpec()
  spec.timeline = [
    { type: 'clip', src: 'a.mp4', start: 2, end: 6, speed: 1, volume: 1, mute: false },
    { type: 'clip', src: 'b.mp4', start: 3, end: 7, speed: 1, volume: 1, mute: false, ...extra },
  ]
  return spec
}

async function mountCrossfade(spec: Record<string, unknown>) {
  opened = await openEditor(spec)
  wrapper = await mountEditorPart(SegmentCrossfade, opened, { index: 1 })
}

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

describe('o crossfade do som no corte de entrada de um clipe', () => {
  it('desligado, só mostra a caixa de marcar e nenhum campo', async () => {
    await mountCrossfade(twoClips())
    expect(wrapper?.find('input[type="checkbox"]').element).toHaveProperty('checked', false)
    expect(wrapper?.findAll('input[type="number"]')).toHaveLength(0)
  })

  it('ligar põe o campo na spec com a duração de meio segundo e a potência constante', async () => {
    await mountCrossfade(twoClips())
    await wrapper?.find('input[type="checkbox"]').setValue(true)
    await flushPromises()
    const clip = (opened.store.spec as { timeline: Record<string, unknown>[] }).timeline[1]
    expect(clip?.audio_crossfade).toEqual({ duration: 0.5, curve: 'constant_power_1' })
    expect(wrapper?.find('input[type="number"]').exists()).toBe(true)
  })

  it('desligar tira o campo da spec, sem deixar um objeto vazio', async () => {
    await mountCrossfade(twoClips({ audio_crossfade: { duration: 0.8, curve: 'constant_gain' } }))
    expect(wrapper?.find('input[type="checkbox"]').element).toHaveProperty('checked', true)
    await wrapper?.find('input[type="checkbox"]').setValue(false)
    await flushPromises()
    const clip = (opened.store.spec as { timeline: Record<string, unknown>[] }).timeline[1]
    expect('audio_crossfade' in (clip ?? {})).toBe(false)
  })

  it('com uma transição de imagem no corte avisa que o crossfade de som não vale', async () => {
    await mountCrossfade(twoClips({ audio_crossfade: { duration: 0.5 }, transition: { type: 'fade', duration: 0.5 } }))
    expect(wrapper?.find('[data-crossfade-ignored]').exists()).toBe(true)
  })
})
