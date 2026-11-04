/* "Salvar a cadeia como macro" no bloco de efeitos: o botão só aparece com efeitos, pede o nome e o escopo, manda a spec da
   tela e o item ao servidor, e a macro nova aparece no menu "+ Efeito", em Predefinições e macros, com o formato de saída. */
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { TimelineView } from '@/api'
import { mountEditorPart, openEditor, type OpenedEditor } from '@/test/editorMount'
import { timelineItem, timelineTrack } from '@/test/editorFixtures'
import { eqCatalog } from '@/test/eqFixtures'
import { reply, type RoutedCall } from '@/test/routedFetch'
import { useAudioEffectsStore } from '@/stores/audioEffects'
import { useConfirmStore } from '@/stores/confirm'
import { useToastsStore } from '@/stores/toasts'
import AudioEffectsSection from './AudioEffectsSection.vue'

const mounted: VueWrapper[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})
beforeEach(() => window.localStorage.clear())

function spec(withChain: boolean, brand?: string): Record<string, unknown> {
  return {
    name: 'demo',
    version: 1,
    ...(brand ? { brand } : {}),
    output: { preset: 'instagram/reels', encoder: 'x264', quality: 'high', guides: false },
    sources: {},
    timeline: [{ type: 'clip', src: 'a.mp4', start: 0, speed: 1, volume: 1, mute: false, fade_in: 0, fade_out: 0 }],
    overlays: [],
    audio: {
      voice_gain: 1,
      normalize: 'two-pass',
      mute_clips: false,
      voiceover: [
        {
          src: 'voz.wav',
          start: 0,
          offset: 0,
          volume: 1,
          ...(withChain ? { effects: [{ type: 'highpass', slope_db: 12, frequency_hz: 80 }, { type: 'noise_reduction' }] } : {}),
        },
      ],
    },
  }
}

function view(): TimelineView {
  return {
    total: 5,
    fps: 30,
    width: 1080,
    height: 1920,
    tracks: [
      timelineTrack('V1', [timelineItem(0, { id: 'V1-0', kind: 'clip', label: 'clip.0' })]),
      timelineTrack('VO', [timelineItem(0, { id: 'VO-0', kind: 'voiceover', label: 'voiceover.0' })], { kind: 'audio' }),
    ],
    sources: {},
    warnings: [],
  }
}

const MACROS = [
  { id: 'mp3_standard', label: 'MP3 para o padrão', summary: 'Normaliza e grava em MP3.', origin: 'builtin', scope: 'builtin', effects: [{ type: 'normalize' }], output: { preset: 'audio/mp3' } },
  { id: 'da-marca', label: 'Da marca', summary: '', origin: 'user', scope: 'brand:acme', effects: [{ type: 'highpass', frequency_hz: 90 }] },
]

async function mountSection(withChain: boolean, brand?: string, routes: Record<string, unknown> = {}): Promise<{ opened: OpenedEditor; wrapper: VueWrapper }> {
  const opened = await openEditor(spec(withChain, brand), {
    'GET /api/audio-effects': { ...eqCatalog(), presets: MACROS },
    'POST /api/projects/demo/timeline': () => view(),
    ...routes,
  })
  const wrapper = await mountEditorPart(AudioEffectsSection, opened, {}, true)
  mounted.push(wrapper)
  opened.store.select(['VO-0'])
  await flushPromises()
  return { opened, wrapper }
}

function field(selector: string): HTMLInputElement {
  const marked = document.body.querySelector(selector) as HTMLElement
  return (marked.matches('input') ? marked : marked.querySelector('input')) as HTMLInputElement
}

describe('Salvar a cadeia como macro', () => {
  it('o botão só aparece quando o item tem efeitos', async () => {
    const empty = await mountSection(false)
    expect(empty.wrapper.find('[data-save-chain-macro]').exists()).toBe(false)
    empty.wrapper.unmount()
    const full = await mountSection(true)
    expect(full.wrapper.find('[data-save-chain-macro]').exists()).toBe(true)
  })

  it('pede o nome, manda a spec da tela e o item ao servidor e a macro nova entra no menu', async () => {
    const sent: Array<Record<string, unknown>> = []
    const { wrapper } = await mountSection(true, undefined, {
      'POST /api/projects/demo/audio-macros': (call: RoutedCall) => {
        sent.push(call.body as Record<string, unknown>)
        return { id: 'minha-cadeia', label: 'Minha cadeia', summary: '', origin: 'user', scope: 'global', effects: [] }
      },
      'GET /api/audio-effects/presets': () => ({
        presets: [{ id: 'minha-cadeia', label: 'Minha cadeia', summary: '', origin: 'user', scope: 'global', effects: [{ type: 'highpass' }] }],
      }),
    })
    await wrapper.find('[data-save-chain-macro]').trigger('click')
    await flushPromises()
    expect(field('[data-macro-name]').value).toContain('voiceover.0')
    const name = field('[data-macro-name]')
    name.value = 'Minha cadeia'
    name.dispatchEvent(new Event('input', { bubbles: true }))
    await flushPromises()
    ;(document.body.querySelector('[data-macro-save]') as HTMLElement).click()
    await flushPromises()
    expect(sent).toHaveLength(1)
    expect(sent[0]).toMatchObject({ target: 'audio.voiceover.0', label: 'Minha cadeia', scope: 'global' })
    expect((sent[0]!.spec as { audio: { voiceover: Array<{ effects: unknown[] }> } }).audio.voiceover[0]!.effects).toHaveLength(2)
    expect(useToastsStore().items.at(-1)?.title).toContain('Minha cadeia')
    expect(document.body.querySelector('[data-macro-name]')).toBeNull() // a janela fechou
    expect(useAudioEffectsStore().presets.map((preset) => preset.id)).toEqual(['mp3_standard', 'minha-cadeia'])
  })

  it('"só a marca" só existe quando o projeto tem marca, e manda o escopo escolhido', async () => {
    const without = await mountSection(true)
    await without.wrapper.find('[data-save-chain-macro]').trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('não tem marca')
    expect(document.body.textContent).not.toContain('Só a marca')
    without.wrapper.unmount()
    document.body.innerHTML = ''

    const sent: Array<Record<string, unknown>> = []
    const { wrapper } = await mountSection(true, 'acme', {
      'POST /api/projects/demo/audio-macros': (call: RoutedCall) => {
        sent.push(call.body as Record<string, unknown>)
        return { id: 'x', label: 'X', summary: '', origin: 'user', scope: 'brand:acme', effects: [] }
      },
      'GET /api/audio-effects/presets': () => ({ presets: [] }),
    })
    await wrapper.find('[data-save-chain-macro]').trigger('click')
    await flushPromises()
    const choose = [...document.body.querySelectorAll('button')].find((button) => button.textContent?.includes('Só a marca acme'))
    expect(choose).toBeDefined()
    choose!.click()
    const name = field('[data-macro-name]')
    name.value = 'X'
    name.dispatchEvent(new Event('input', { bubbles: true }))
    await flushPromises()
    ;(document.body.querySelector('[data-macro-save]') as HTMLElement).click()
    await flushPromises()
    expect(sent[0]).toMatchObject({ scope: 'brand', label: 'X' })
  })

  it('avisa quando o nome já é de uma macro sua, e o servidor que recusa vira aviso sem fechar a janela', async () => {
    const { wrapper } = await mountSection(true, undefined, {
      'POST /api/projects/demo/audio-macros': () => reply(422, { detail: 'o item audio.voiceover.0 não tem efeitos para salvar como macro' }),
    })
    await wrapper.find('[data-save-chain-macro]').trigger('click')
    await flushPromises()
    const name = field('[data-macro-name]')
    name.value = ' DA marca '
    name.dispatchEvent(new Event('input', { bubbles: true }))
    await flushPromises()
    expect(document.body.querySelector('[data-macro-replace]')).not.toBeNull()
    ;(document.body.querySelector('[data-macro-save]') as HTMLElement).click()
    await flushPromises()
    expect(useToastsStore().items.at(-1)).toMatchObject({ tone: 'error', description: expect.stringContaining('não tem efeitos') })
    expect(document.body.querySelector('[data-macro-name]')).not.toBeNull()
  })
})

describe('o menu "+ Efeito" com as macros', () => {
  it('o grupo se chama Predefinições e macros e a linha mostra o formato de saída e a marca', async () => {
    const { wrapper } = await mountSection(true, 'acme', { 'GET /api/audio-effects/presets': () => ({ presets: [MACROS[1]] }) })
    await wrapper.find('[data-effects-add]').trigger('click')
    await flushPromises()
    expect(document.body.querySelector('.effects-menu__heading')?.textContent).toBe('Predefinições e macros')
    const notes = [...document.body.querySelectorAll('[data-preset-note]')].map((node) => node.textContent)
    expect(notes[0]).toContain('saída MP3 ao aplicar a arquivos')
    expect(notes[1]).toContain('marca acme')
  })

  it('apagar uma macro da marca pede a marca ao servidor', async () => {
    const { opened, wrapper } = await mountSection(true, 'acme', {
      'GET /api/audio-effects/presets': () => ({ presets: [MACROS[1]] }),
      'DELETE /api/audio-effects/presets/da-marca': () => ({ id: 'da-marca', label: 'Da marca', summary: '', effects: [], origin: 'user' }),
    })
    await wrapper.find('[data-effects-add]').trigger('click')
    await flushPromises()
    ;(document.body.querySelector('[data-remove-preset="da-marca"]') as HTMLElement).click()
    await flushPromises()
    useConfirmStore().answer(true)
    await flushPromises()
    const calls = opened.fetch.calls.filter((call) => call.method === 'DELETE')
    expect(calls).toHaveLength(1)
    expect(calls[0]!.url).toContain('/api/audio-effects/presets/da-marca?brand=acme')
  })
})
