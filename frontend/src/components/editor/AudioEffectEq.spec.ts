/* Os efeitos de equalização no painel Filtros: o gráfico da resposta de frequência que o servidor calcula, os 31 controles do
   EQ Gráfico, os pontos arrastáveis do EQ por Curva, a escolha com opções numéricas e as predefinições salvas pela pessoa. */
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { TimelineView } from '@/api'
import { mountEditorPart, openEditor, type OpenedEditor } from '@/test/editorMount'
import { timelineItem, timelineTrack } from '@/test/editorFixtures'
import { eqCatalog, responseCurve } from '@/test/eqFixtures'
import { reply, type RoutedCall } from '@/test/routedFetch'
import { useConfirmStore } from '@/stores/confirm'
import { useAudioEffectsStore } from '@/stores/audioEffects'
import { useToastsStore } from '@/stores/toasts'
import AudioEffectsSection from './AudioEffectsSection.vue'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})
beforeEach(() => window.localStorage.clear())

function spec(): Record<string, unknown> {
  return {
    name: 'demo',
    version: 1,
    output: { preset: 'instagram/reels', encoder: 'x264', quality: 'high', guides: false },
    sources: {},
    timeline: [{ type: 'clip', src: 'a.mp4', start: 0, speed: 1, volume: 1, mute: false, fade_in: 0, fade_out: 0 }],
    overlays: [],
    audio: { voice_gain: 1, normalize: 'two-pass', mute_clips: false, voiceover: [{ src: 'voz.wav', start: 0, offset: 0, volume: 1 }] },
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

const RESPONSE = 'POST /api/audio-effects/response'

async function mountEq(routes: Record<string, unknown> = {}): Promise<{ opened: OpenedEditor; wrapper: VueWrapper }> {
  const opened = await openEditor(spec(), {
    'GET /api/audio-effects': eqCatalog(),
    'POST /api/projects/demo/timeline': () => view(),
    [RESPONSE]: () => responseCurve(),
    ...routes,
  })
  const wrapper = await mountEditorPart(AudioEffectsSection, opened, {}, true)
  opened.store.select(['VO-0'])
  await flushPromises()
  return { opened, wrapper }
}

async function addEffect(wrapper: VueWrapper, type: string): Promise<void> {
  await wrapper.find('[data-effects-add]').trigger('click')
  await flushPromises()
  ;(document.body.querySelector(`[data-add-effect="${type}"]`) as HTMLElement).click()
  await flushPromises()
}

/** O campo de texto do nome (o atributo cai no próprio campo ou no envoltório, conforme o componente). */
function nameInput(): HTMLInputElement {
  const marked = document.body.querySelector('[data-preset-name]') as HTMLElement
  return (marked.matches('input') ? marked : marked.querySelector('input')) as HTMLInputElement
}

/** Deixa passar o tempo do relógio falso (a espera de cada campo) e volta ao relógio de verdade. */
async function wait(ms: number): Promise<void> {
  await vi.advanceTimersByTimeAsync(ms)
  vi.useRealTimers()
  await flushPromises()
}

const chain = (opened: OpenedEditor) => opened.store.get('audio.voiceover.0.effects') as Array<Record<string, unknown>> | undefined
const responseCalls = (opened: OpenedEditor) => (opened.fetch.to(RESPONSE) as RoutedCall[]).map((call) => call.body as Record<string, unknown>)

describe('o gráfico da resposta de frequência', () => {
  it('o passa-alta mostra a curva que o servidor calculou, pedida sem o intervalo nem o bypass', async () => {
    const { opened, wrapper } = await mountEq()
    await addEffect(wrapper, 'highpass')
    expect(chain(opened)).toEqual([{ type: 'highpass', slope_db: 6, frequency_hz: 100 }])
    expect(wrapper.find('[data-effect-response] [data-eq-curve]').exists()).toBe(true)
    expect(responseCalls(opened)[0]).toEqual({ effect: { type: 'highpass', slope_db: 6, frequency_hz: 100 } })
  })

  it('mudar o parâmetro pede a curva de novo, uma vez só depois que o valor para de mudar', async () => {
    const { opened, wrapper } = await mountEq()
    await addEffect(wrapper, 'highpass')
    const before = responseCalls(opened).length
    vi.useFakeTimers()
    const field = wrapper.find('[data-effect-param="frequency_hz"] input')
    for (const value of ['1', '12', '120']) {
      ;(field.element as HTMLInputElement).value = value
      await field.trigger('input')
    }
    await wait(1000)
    const calls = responseCalls(opened)
    expect(calls.length - before).toBe(1)
    expect((calls.at(-1)!.effect as Record<string, unknown>).frequency_hz).toBe(120)
  })

  it('uma resposta atrasada de um pedido antigo não sobrepõe a do mais novo', async () => {
    const answers: Array<(value: unknown) => void> = []
    const { wrapper } = await mountEq({ [RESPONSE]: () => new Promise((resolve) => answers.push(resolve)) })
    await addEffect(wrapper, 'highpass')
    await flushPromises()
    vi.useFakeTimers()
    const field = wrapper.find('[data-effect-param="frequency_hz"] input')
    ;(field.element as HTMLInputElement).value = '200'
    await field.trigger('input')
    await wait(1000)
    expect(answers.length).toBeGreaterThanOrEqual(2)
    answers[1]!({ hz: [20, 20000], db: [-1, -1] })
    await flushPromises()
    answers[0]!({ hz: [20, 20000], db: [-30, -30] }) // o pedido velho chega por último
    await flushPromises()
    const path = wrapper.find('[data-eq-curve]').attributes('d') ?? ''
    expect(path).toMatch(/^M0\.0 /)
    const first = Number(path.split(' ')[1])
    const second = Number(path.split(' L')[1]!.split(' ')[1])
    expect(first).toBeLessThan(150) // -1 dB fica perto do alto; -30 dB estaria embaixo
    expect(second).toBeLessThan(150)
  })

  it('se o servidor recusa, o gráfico avisa o motivo e o resto do cartão continua', async () => {
    const { opened, wrapper } = await mountEq({ [RESPONSE]: () => reply(422, { detail: 'slope_db: valor fora da lista' }) })
    await addEffect(wrapper, 'highpass')
    expect(wrapper.find('[data-eq-error]').text()).toContain('slope_db: valor fora da lista')
    expect(chain(opened)).toHaveLength(1)
  })
})

describe('a escolha com opções numéricas', () => {
  it('mostra a inclinação padrão e grava o número, não o texto', async () => {
    const { opened, wrapper } = await mountEq()
    await addEffect(wrapper, 'highpass')
    const select = wrapper.find('[data-effect-param="slope_db"] select')
    expect((select.element as HTMLSelectElement).value).toBe('6')
    await select.setValue('24')
    await flushPromises()
    expect(chain(opened)![0]!.slope_db).toBe(24)
    expect((wrapper.find('[data-effect-param="slope_db"] select').element as HTMLSelectElement).value).toBe('24')
  })
})

describe('o EQ Gráfico', () => {
  it('põe os 31 controles e grava um passo só por gesto', async () => {
    const { opened, wrapper } = await mountEq()
    await addEffect(wrapper, 'graphic_eq')
    expect(wrapper.findAll('[data-band-sliders] input[type="range"]')).toHaveLength(31)
    expect((chain(opened)![0]!.gains_db as number[]).every((gain) => gain === 0)).toBe(true)
    const slider = wrapper.find('[data-band="22"]')
    vi.useFakeTimers()
    ;(slider.element as HTMLInputElement).value = '6'
    await slider.trigger('input')
    expect((chain(opened)![0]!.gains_db as number[])[22]).toBe(0) // enquanto arrasta, a spec não muda
    await wait(300)
    // o gráfico foi pedido com o ganho novo, ainda antes de gravar
    expect(responseCalls(opened).some((body) => ((body.effect as Record<string, unknown>).gains_db as number[])[22] === 6)).toBe(true)
    await slider.trigger('change')
    await flushPromises()
    const gains = chain(opened)![0]!.gains_db as number[]
    expect(gains[22]).toBe(6)
    expect(gains.filter((gain) => gain !== 0)).toHaveLength(1)
    expect(opened.store.undo()).toBe(true) // um gesto, um passo do desfazer
    expect((chain(opened)![0]!.gains_db as number[])[22]).toBe(0)
  })

  it('o efeito novo não divide a lista de ganhos com o catálogo', async () => {
    const { opened, wrapper } = await mountEq()
    await addEffect(wrapper, 'graphic_eq')
    const slider = wrapper.find('[data-band="3"]')
    ;(slider.element as HTMLInputElement).value = '-8'
    await slider.trigger('input')
    await slider.trigger('change')
    await flushPromises()
    const catalogGains = useAudioEffectsStore().infoOf('graphic_eq')!.parameters[0]!.default as number[]
    expect(catalogGains.every((gain) => gain === 0)).toBe(true)
    expect(chain(opened)![0]!.gains_db).not.toBe(catalogGains)
  })
})

describe('o EQ por Curva', () => {
  it('mostra os pontos e acrescenta um com clique duplo, gravando a lista na spec', async () => {
    const { opened, wrapper } = await mountEq()
    await addEffect(wrapper, 'filter_curve_eq')
    expect(wrapper.findAll('[data-eq-point]')).toHaveLength(2)
    const svg = wrapper.find('[data-eq-control="freq_points"] svg')
    ;(svg.element as SVGSVGElement).getBoundingClientRect = () => ({ left: 0, top: 0, width: 480, height: 200, right: 480, bottom: 200, x: 0, y: 0, toJSON: () => ({}) })
    svg.element.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, clientX: 240, clientY: 100 }))
    await flushPromises()
    const points = chain(opened)![0]!.points as Array<{ hz: number; db: number }>
    expect(points).toHaveLength(3)
    expect(points.map((point) => point.hz)).toEqual([...points.map((point) => point.hz)].sort((a, b) => a - b))
    expect(wrapper.findAll('[data-eq-point]')).toHaveLength(3)
  })

  it('arrastar um ponto redesenha ao vivo e grava só ao soltar, num passo do desfazer', async () => {
    const { opened, wrapper } = await mountEq()
    await addEffect(wrapper, 'filter_curve_eq')
    const svg = wrapper.find('[data-eq-control="freq_points"] svg')
    ;(svg.element as SVGSVGElement).getBoundingClientRect = () => ({ left: 0, top: 0, width: 480, height: 200, right: 480, bottom: 200, x: 0, y: 0, toJSON: () => ({}) })
    const before = responseCalls(opened).length
    vi.useFakeTimers()
    wrapper.find('[data-eq-point="0"]').element.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, cancelable: true }))
    svg.element.dispatchEvent(new MouseEvent('pointermove', { bubbles: true, clientX: 100, clientY: 60 }))
    await flushPromises()
    expect((chain(opened)![0]!.points as Array<{ db: number }>)[0]!.db).toBe(0) // a spec espera o soltar
    await wait(400)
    expect(responseCalls(opened).length).toBeGreaterThan(before) // o gráfico já pediu a curva nova
    svg.element.dispatchEvent(new MouseEvent('pointerup', { bubbles: true }))
    await flushPromises()
    const moved = (chain(opened)![0]!.points as Array<{ hz: number; db: number }>)[0]!
    expect(moved.db).toBeGreaterThan(0)
    expect(opened.store.undo()).toBe(true)
    expect((chain(opened)![0]!.points as Array<{ db: number }>)[0]!.db).toBe(0)
  })
})

describe('as predefinições salvas pela pessoa', () => {
  it('o menu mostra as embutidas e as da pessoa, e só estas têm o botão de apagar', async () => {
    const { wrapper } = await mountEq()
    await wrapper.find('[data-effects-add]').trigger('click')
    await flushPromises()
    const rows = [...document.body.querySelectorAll('[data-preset-origin]')]
    expect(rows.map((row) => row.getAttribute('data-preset-origin'))).toEqual(['builtin', 'user'])
    expect(document.body.querySelectorAll('[data-remove-preset]')).toHaveLength(1)
    expect(document.body.querySelector('[data-remove-preset]')?.getAttribute('data-remove-preset')).toBe('meu-corte')
  })

  it('aplicar a predefinição da pessoa põe o efeito na cadeia', async () => {
    const { opened, wrapper } = await mountEq()
    await wrapper.find('[data-effects-add]').trigger('click')
    await flushPromises()
    ;(document.body.querySelector('[data-add-preset="meu-corte"]') as HTMLElement).click()
    await flushPromises()
    expect(chain(opened)).toEqual([{ type: 'highpass', frequency_hz: 85, slope_db: 24 }])
  })

  it('salvar pede o nome, manda o efeito ao servidor e a predefinição aparece no menu', async () => {
    const saved: Array<{ label: string; effects: unknown[] }> = []
    const { wrapper } = await mountEq({
      'POST /api/audio-effects/presets': (call: RoutedCall) => {
        const body = call.body as { label: string; effects: unknown[] }
        saved.push(body)
        return { id: 'minha-voz', label: body.label, summary: '', effects: body.effects, origin: 'user' }
      },
      'GET /api/audio-effects/presets': () => ({
        presets: [
          { id: 'meu-corte', label: 'Meu corte', summary: '', origin: 'user', effects: [] },
          { id: 'minha-voz', label: 'Minha voz', summary: '', origin: 'user', effects: [{ type: 'highpass', slope_db: 24 }] },
        ],
      }),
    })
    await addEffect(wrapper, 'highpass')
    await wrapper.find('[data-save-preset]').trigger('click')
    await flushPromises()
    const name = nameInput()
    expect(name.value).toBe('Passa-alta') // sugere o nome do efeito
    name.value = 'Minha voz'
    name.dispatchEvent(new Event('input', { bubbles: true }))
    await flushPromises()
    ;(document.body.querySelector('[data-preset-save]') as HTMLElement).click()
    await flushPromises()
    expect(saved).toEqual([{ label: 'Minha voz', effects: [{ type: 'highpass', slope_db: 6, frequency_hz: 100 }], summary: '' }])
    expect(useToastsStore().items.at(-1)?.title).toContain('Minha voz')
    expect(document.body.querySelector('[data-preset-name]')).toBeNull() // a janela fechou
    expect(useAudioEffectsStore().presets.map((preset) => preset.id)).toEqual(['rumble_100hz', 'meu-corte', 'minha-voz'])
  })

  it('avisa quando o nome já é de uma predefinição da pessoa (salvar troca), e o servidor que recusa vira aviso', async () => {
    const { wrapper } = await mountEq({ 'POST /api/audio-effects/presets': () => reply(422, { detail: 'dê um nome à predefinição' }) })
    await addEffect(wrapper, 'highpass')
    await wrapper.find('[data-save-preset]').trigger('click')
    await flushPromises()
    const name = nameInput()
    name.value = ' meu CORTE '
    name.dispatchEvent(new Event('input', { bubbles: true }))
    await flushPromises()
    expect(document.body.querySelector('[data-preset-replace]')).not.toBeNull()
    ;(document.body.querySelector('[data-preset-save]') as HTMLElement).click()
    await flushPromises()
    expect(useToastsStore().items.at(-1)).toMatchObject({ tone: 'error', description: 'dê um nome à predefinição' })
    expect(document.body.querySelector('[data-preset-name]')).not.toBeNull() // fica aberta para corrigir
  })

  it('apagar pergunta antes e, confirmado, chama o servidor e tira do menu', async () => {
    const { opened, wrapper } = await mountEq({
      'DELETE /api/audio-effects/presets/meu-corte': () => ({ id: 'meu-corte', label: 'Meu corte', summary: '', effects: [], origin: 'user' }),
      'GET /api/audio-effects/presets': () => ({ presets: [] }),
    })
    await wrapper.find('[data-effects-add]').trigger('click')
    await flushPromises()
    ;(document.body.querySelector('[data-remove-preset="meu-corte"]') as HTMLElement).click()
    await flushPromises()
    expect(useConfirmStore().current?.options.title).toContain('Meu corte')
    expect(opened.fetch.to('DELETE /api/audio-effects/presets/meu-corte')).toHaveLength(0)
    useConfirmStore().answer(true)
    await flushPromises()
    expect(opened.fetch.to('DELETE /api/audio-effects/presets/meu-corte')).toHaveLength(1)
    expect(useAudioEffectsStore().presets.map((preset) => preset.id)).toEqual(['rumble_100hz'])
    expect(document.body.querySelector('[data-remove-preset]')).toBeNull()
  })

  it('apagar e responder que não deixa tudo como está', async () => {
    const { opened, wrapper } = await mountEq()
    await wrapper.find('[data-effects-add]').trigger('click')
    await flushPromises()
    ;(document.body.querySelector('[data-remove-preset="meu-corte"]') as HTMLElement).click()
    await flushPromises()
    useConfirmStore().answer(false)
    await flushPromises()
    expect(opened.fetch.calls.some((call) => call.method === 'DELETE')).toBe(false)
    expect(useAudioEffectsStore().presets).toHaveLength(2)
  })
})
