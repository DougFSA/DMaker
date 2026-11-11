import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import type { TimelineTrack } from '@/api'
import { timelineItem, timelineTrack } from '@/test/editorFixtures'
import TimelineTrackMix from './TimelineTrackMix.vue'
import TimelineTrackRow from './TimelineTrackRow.vue'

let wrapper: VueWrapper | null = null

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

function audioTrack(extra: Partial<TimelineTrack> = {}): TimelineTrack {
  return timelineTrack('VO', [timelineItem(0, { id: 'VO-0', kind: 'voiceover' })], { kind: 'audio', label: 'VO', gain_db: 0, pan: 0, solo: false, ...extra })
}

async function openMix(track: TimelineTrack) {
  wrapper = mount(TimelineTrackMix, { props: { track }, attachTo: document.body })
  await wrapper.get('[data-track-action="mix"]').trigger('click')
  await flushPromises()
  return wrapper
}

const field = <T extends Element>(selector: string) => document.body.querySelector(selector) as unknown as T

function drag(input: HTMLInputElement, value: string): void {
  input.value = value
  input.dispatchEvent(new Event('input', { bubbles: true }))
  input.dispatchEvent(new Event('change', { bubbles: true }))
}

describe('ganho e pan da trilha', () => {
  it('mostra o ganho e o pan da spec, e o botão acende quando algum deles não é o padrão', async () => {
    const view = await openMix(audioTrack({ gain_db: -6, pan: -0.5 }))
    expect(field<HTMLElement>('[data-mix-gain-text]').textContent).toBe('-6,0 dB')
    expect(field<HTMLElement>('[data-mix-pan-text]').textContent).toBe('50% esquerda')
    expect(view.get('[data-track-action="mix"]').classes()).toContain('mix__trigger--on')
  })

  it('soltar o ganho manda UMA mudança de ganho; arrastar sem soltar não manda nada', async () => {
    const view = await openMix(audioTrack())
    const gain = field<HTMLInputElement>('[data-mix-gain]')
    gain.value = '-12'
    gain.dispatchEvent(new Event('input', { bubbles: true }))
    expect(view.emitted('change')).toBeUndefined()
    gain.dispatchEvent(new Event('change', { bubbles: true }))
    expect(view.emitted('change')).toEqual([[{ gain_db: -12 }]])
  })

  it('o pan vai de -1 a 1 e o ganho respeita os limites da spec', async () => {
    const view = await openMix(audioTrack())
    drag(field<HTMLInputElement>('[data-mix-pan]'), '100')
    drag(field<HTMLInputElement>('[data-mix-gain]'), '24')
    expect(view.emitted('change')).toEqual([[{ pan: 1 }], [{ gain_db: 24 }]])
  })

  it('Zerar devolve só o que estava fora do padrão', async () => {
    const view = await openMix(audioTrack({ gain_db: -3, pan: 0 }))
    field<HTMLButtonElement>('[data-mix-reset]').click()
    expect(view.emitted('change')).toEqual([[{ gain_db: 0 }]])
  })

  it('acompanha a spec quando ela muda por fora (desfazer)', async () => {
    const view = await openMix(audioTrack({ gain_db: -6 }))
    await view.setProps({ track: audioTrack({ gain_db: 0 }) })
    expect(field<HTMLElement>('[data-mix-gain-text]').textContent).toBe('0,0 dB')
  })
})

describe('o cabeçalho da trilha de áudio', () => {
  const props = { total: 10, pxPerSec: 60, windowStart: 0, windowEnd: 10, selected: new Set<string>() }

  it('tem solo e o popover de ganho e pan, e o solo manda a operação da trilha', async () => {
    wrapper = mount(TimelineTrackRow, { props: { ...props, track: audioTrack() }, attachTo: document.body })
    expect(wrapper.find('[data-track-action="mix"]').exists()).toBe(true)
    await wrapper.get('[data-track-action="solo"]').trigger('click')
    expect(wrapper.emitted('track-set')).toEqual([['VO', { solo: true }]])
    await wrapper.setProps({ track: audioTrack({ solo: true }) })
    expect(wrapper.get('[data-track-action="solo"]').attributes('aria-pressed')).toBe('true')
    await wrapper.get('[data-track-action="solo"]').trigger('click')
    expect(wrapper.emitted('track-set')?.at(-1)).toEqual(['VO', { solo: false }])
  })

  it('trilha de vídeo e de marcadores não têm solo nem ganho', () => {
    wrapper = mount(TimelineTrackRow, { props: { ...props, track: timelineTrack('V1', []) } })
    expect(wrapper.find('[data-track-action="solo"]').exists()).toBe(false)
    expect(wrapper.find('[data-track-action="mix"]').exists()).toBe(false)
  })

  it('a trilha silenciada pelo solo de outra fica esmaecida como a muda', () => {
    wrapper = mount(TimelineTrackRow, { props: { ...props, track: audioTrack({ silenced: true }) } })
    expect(wrapper.classes()).toContain('row--muted')
  })

  it('o ganho vira operação da trilha', async () => {
    wrapper = mount(TimelineTrackRow, { props: { ...props, track: audioTrack() }, attachTo: document.body })
    await wrapper.get('[data-track-action="mix"]').trigger('click')
    await flushPromises()
    drag(field<HTMLInputElement>('[data-mix-gain]'), '-9')
    expect(wrapper.emitted('track-set')).toEqual([['VO', { gain_db: -9 }]])
  })
})
