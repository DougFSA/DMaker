import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { TimelineView } from '@/api'
import { audioEffectCatalog } from '@/test/audioEffectsFixtures'
import { mountEditorPart, openEditor, type OpenedEditor } from '@/test/editorMount'
import { timelineItem, timelineTrack } from '@/test/editorFixtures'
import { filterSchema } from '@/test/filterFixtures'
import { reply } from '@/test/routedFetch'
import AudioEffectsSection from './AudioEffectsSection.vue'
import FiltersPanel from './FiltersPanel.vue'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})
beforeEach(() => window.localStorage.clear())

function effectsSpec(): Record<string, unknown> {
  return {
    name: 'demo',
    version: 1,
    output: { preset: 'instagram/reels', encoder: 'x264', quality: 'high', guides: false },
    sources: {},
    timeline: [
      { type: 'clip', src: 'a.mp4', start: 0, speed: 1, volume: 1, mute: false, fade_in: 0, fade_out: 0 },
      { type: 'card', title: 'Fim', duration: 3, logo: true, motion: 'zoom-in', motion_amount: 0.04 },
    ],
    overlays: [
      { type: 'text', text: 'Olá', role: 'title', start: 0 },
      { type: 'video', src: 'pip.mp4', start: 1, position: 'bottom-right' },
    ],
    audio: {
      voice_gain: 1,
      normalize: 'two-pass',
      mute_clips: false,
      music: { src: 'musica.mp3', volume: 0.18, loop: true },
      tracks: [{ source: 'x', volume: 1 }],
      narration: [{ text: 'Olá', speed: 1 }],
      voiceover: [{ src: 'voz.wav', start: 0, offset: 0, volume: 1 }],
    },
  }
}

/** A vista com uma trilha de cada tipo, cada item com o id `<trilha>-<índice>` que a linha do tempo usa. */
function effectsView(): TimelineView {
  const item = (id: string, index: number, kind: string) => timelineItem(index, { id, kind, label: `${kind}.${index}` })
  return {
    total: 9,
    fps: 30,
    width: 1080,
    height: 1920,
    tracks: [
      timelineTrack('V1', [item('V1-0', 0, 'clip'), item('V1-1', 1, 'card')]),
      timelineTrack('TX', [item('TX-0', 0, 'text')], { kind: 'text' }),
      timelineTrack('V2', [item('V2-1', 1, 'video')]),
      timelineTrack('A1', [item('A1-0', 0, 'clip-audio')], { kind: 'audio' }),
      timelineTrack('A2', [item('A2-0', 0, 'track')], { kind: 'audio' }),
      timelineTrack('NAR', [item('NAR-0', 0, 'narration')], { kind: 'audio' }),
      timelineTrack('VO', [item('VO-0', 0, 'voiceover')], { kind: 'audio' }),
      timelineTrack('MUS', [item('MUS-0', 0, 'music')], { kind: 'audio' }),
    ],
    sources: {},
    warnings: [],
  }
}

async function mountEffects(
  spec: Record<string, unknown> = effectsSpec(),
  routes: Record<string, unknown> = {},
): Promise<{ opened: OpenedEditor; wrapper: VueWrapper }> {
  const opened = await openEditor(spec, {
    'GET /api/audio-effects': audioEffectCatalog(),
    'POST /api/projects/demo/timeline': () => effectsView(),
    ...routes,
  })
  const wrapper = await mountEditorPart(AudioEffectsSection, opened, {}, true)
  return { opened, wrapper }
}

async function choose(opened: OpenedEditor, ...ids: string[]): Promise<void> {
  opened.store.select(ids)
  await flushPromises()
}

const cards = (wrapper: VueWrapper) => wrapper.findAll('[data-effect-type]')
const cardTypes = (wrapper: VueWrapper) => cards(wrapper).map((card) => card.attributes('data-effect-type'))
const card = (wrapper: VueWrapper, index: number) => cards(wrapper)[index]!
const target = (wrapper: VueWrapper) => wrapper.find('[data-effects-target]').text()

/** Abre o menu e devolve o `type` de cada efeito oferecido; se ele já estava aberto, fecha e abre de novo. */
async function openMenu(wrapper: VueWrapper): Promise<string[]> {
  if (document.body.querySelector('.effects-menu')) {
    await wrapper.find('[data-effects-add]').trigger('click')
    await flushPromises()
  }
  await wrapper.find('[data-effects-add]').trigger('click')
  await flushPromises()
  return [...document.body.querySelectorAll('[data-add-effect]')].map((button) => button.getAttribute('data-add-effect') ?? '')
}

async function addEffect(wrapper: VueWrapper, type: string): Promise<void> {
  await openMenu(wrapper)
  ;(document.body.querySelector(`[data-add-effect="${type}"]`) as HTMLElement).click()
  await flushPromises()
}

const effectsAt = (opened: OpenedEditor, path: string) => opened.store.get(path) as Array<Record<string, unknown>> | undefined
const input = (wrapper: VueWrapper, index: number, param: string) => card(wrapper, index).find(`[data-effect-param="${param}"] input`)

/** Desfaz até o começo e conta os passos: cada ação da cadeia vale exatamente um. */
function undoSteps(opened: OpenedEditor): number {
  let steps = 0
  while (opened.store.undo()) steps += 1
  return steps
}

describe('AudioEffectsSection: qual cadeia aparece', () => {
  it('sem seleção edita o master e diz que está vazio', async () => {
    const { wrapper } = await mountEffects()
    expect(wrapper.text()).toContain('Efeitos de áudio')
    expect(target(wrapper)).toBe('Master (mistura inteira)')
    expect(wrapper.find('[data-effects-empty]').exists()).toBe(true)
    expect(cards(wrapper)).toHaveLength(0)
  })

  it('cada item de som edita a cadeia dele e o cabeçalho diz qual é', async () => {
    const { opened, wrapper } = await mountEffects()
    const expected: Array<[string, string]> = [
      ['V1-0', 'Som do clipe 1 · clip.0'],
      // a sombra de áudio edita o clipe da V1, então o nome é o do clipe
      ['A1-0', 'Som do clipe 1 · clip.0'],
      ['A2-0', 'Faixa de áudio A2 · track.0'],
      ['MUS-0', 'Música · music.0'],
      ['NAR-0', 'Narração 1 · narration.0'],
      ['VO-0', 'Voz gravada 1 · voiceover.0'],
      ['V2-1', 'Som do PiP V2 · video.1'],
    ]
    for (const [id, title] of expected) {
      await choose(opened, id)
      expect(target(wrapper)).toBe(title)
    }
    await choose(opened)
    expect(target(wrapper)).toBe('Master (mistura inteira)')
  })

  it('item sem som avisa e não deixa adicionar', async () => {
    const { opened, wrapper } = await mountEffects()
    for (const id of ['TX-0', 'V1-1']) {
      await choose(opened, id)
      expect(wrapper.find('[data-effects-silent]').text()).toContain('não tem som')
      expect(wrapper.find('[data-effects-silent]').text()).toContain('master')
      expect(wrapper.find('[data-effects-add]').attributes('disabled')).toBeDefined()
      expect(wrapper.find('[data-effects-target]').exists()).toBe(false)
    }
  })

  it('mostra os efeitos que a spec já tem, no lugar certo e na ordem', async () => {
    const spec = effectsSpec()
    ;(spec.timeline as Array<Record<string, unknown>>)[0]!.effects = [
      { type: 'normalize', peak_db: -3, remove_dc: true, stereo_independent: false },
      { type: 'amplify', gain_db: 6, prevent_clipping: true },
    ]
    const { opened, wrapper } = await mountEffects(spec)
    expect(cards(wrapper)).toHaveLength(0)
    await choose(opened, 'A1-0')
    expect(cardTypes(wrapper)).toEqual(['normalize', 'amplify'])
    expect((input(wrapper, 0, 'peak_db').element as HTMLInputElement).value).toBe('-3')
    expect((input(wrapper, 1, 'gain_db').element as HTMLInputElement).value).toBe('6')
    expect((input(wrapper, 1, 'prevent_clipping').element as HTMLInputElement).checked).toBe(true)
    await choose(opened, 'V1-0')
    expect(cardTypes(wrapper)).toEqual(['normalize', 'amplify'])
    await choose(opened, 'MUS-0')
    expect(cardTypes(wrapper)).toEqual([])
  })
})

describe('AudioEffectsSection: o menu "+ Efeito"', () => {
  it('lista o catálogo com o nome em português e o do Audacity', async () => {
    const { wrapper } = await mountEffects()
    expect(await openMenu(wrapper)).toEqual(['amplify', 'normalize', 'invert', 'reverse'])
    const names = (selector: string) => [...document.body.querySelectorAll(selector)].map((element) => element.textContent)
    expect(names('.effects-menu__name')).toEqual(['Amplificar', 'Normalizar', 'Inverter', 'Reverter'])
    expect(names('.effects-menu__audacity')).toEqual(['Amplify', 'Normalize', 'Invert', 'Reverse'])
  })

  it('o Repetir só aparece onde o item pode crescer: voz gravada e música', async () => {
    const { opened, wrapper } = await mountEffects()
    expect(await openMenu(wrapper)).not.toContain('repeat')
    for (const id of ['V1-0', 'A2-0', 'NAR-0', 'V2-1']) {
      await choose(opened, id)
      expect(await openMenu(wrapper)).not.toContain('repeat')
      expect(document.body.querySelector('[data-effects-hidden]')?.textContent).toContain('Repetir: só vale em voz gravada e música.')
    }
  })

  it('na voz gravada e na música o Repetir está no menu', async () => {
    const { opened, wrapper } = await mountEffects()
    await choose(opened, 'VO-0')
    expect(await openMenu(wrapper)).toContain('repeat')
    expect(document.body.querySelector('[data-effects-hidden]')).toBeNull()
    await choose(opened, 'MUS-0')
    expect(await openMenu(wrapper)).toContain('repeat')
  })

  it('o efeito que o catálogo trouxer depois aparece sem mexer na tela', async () => {
    const catalog = audioEffectCatalog()
    catalog.effects.push({
      type: 'echo',
      label: 'Eco',
      audacity_name: 'Echo',
      summary: 'Repete o som mais baixo.',
      changes_duration: false,
      parameters: [{ name: 'delay', label: 'Atraso', kind: 'number', unit: 's', default: 0.5, minimum: 0.01, maximum: 10, hint: '', options: [] }],
    })
    const { wrapper } = await mountEffects(effectsSpec(), { 'GET /api/audio-effects': catalog })
    expect(await openMenu(wrapper)).toContain('echo')
    ;(document.body.querySelector('[data-add-effect="echo"]') as HTMLElement).click()
    await flushPromises()
    expect(card(wrapper, 0).text()).toContain('Eco')
    expect((input(wrapper, 0, 'delay').element as HTMLInputElement).value).toBe('0.5')
  })
})

describe('AudioEffectsSection: adicionar', () => {
  it('põe o efeito no fim da cadeia com os padrões do catálogo e fecha o menu', async () => {
    const { opened, wrapper } = await mountEffects()
    await addEffect(wrapper, 'amplify')
    expect(cardTypes(wrapper)).toEqual(['amplify'])
    expect(effectsAt(opened, 'audio.master_effects')).toEqual([{ type: 'amplify', gain_db: 0, prevent_clipping: false }])
    expect(document.body.querySelector('[data-add-effect]')).toBeNull()
    await addEffect(wrapper, 'invert')
    expect(effectsAt(opened, 'audio.master_effects')).toEqual([
      { type: 'amplify', gain_db: 0, prevent_clipping: false },
      { type: 'invert' },
    ])
    expect(cardTypes(wrapper)).toEqual(['amplify', 'invert'])
    expect(opened.store.dirty).toBe(true)
  })

  it('grava no campo effects do item selecionado', async () => {
    const { opened, wrapper } = await mountEffects()
    await choose(opened, 'V1-0')
    await addEffect(wrapper, 'normalize')
    expect(effectsAt(opened, 'timeline.0.effects')).toEqual([{ type: 'normalize', peak_db: -1, remove_dc: true, stereo_independent: false }])
    await choose(opened, 'MUS-0')
    await addEffect(wrapper, 'repeat')
    expect(effectsAt(opened, 'audio.music.effects')).toEqual([{ type: 'repeat', times: 2 }])
    await choose(opened, 'VO-0')
    await addEffect(wrapper, 'reverse')
    expect(effectsAt(opened, 'audio.voiceover.0.effects')).toEqual([{ type: 'reverse' }])
    await choose(opened, 'NAR-0')
    await addEffect(wrapper, 'invert')
    expect(effectsAt(opened, 'audio.narration.0.effects')).toEqual([{ type: 'invert' }])
    await choose(opened, 'A2-0')
    await addEffect(wrapper, 'invert')
    expect(effectsAt(opened, 'audio.tracks.0.effects')).toEqual([{ type: 'invert' }])
    await choose(opened, 'V2-1')
    await addEffect(wrapper, 'invert')
    expect(effectsAt(opened, 'overlays.1.effects')).toEqual([{ type: 'invert' }])
    // nada vazou para o master nem para o outro texto
    expect(opened.store.get('audio.master_effects')).toBeUndefined()
    expect(opened.store.get('overlays.0')).not.toHaveProperty('effects')
  })

  it('desfazer tira o efeito e a chave, e o projeto volta idêntico ao de antes', async () => {
    const { opened, wrapper } = await mountEffects()
    const before = JSON.stringify(opened.store.spec)
    await addEffect(wrapper, 'amplify')
    expect(opened.store.undo()).toBe(true)
    await flushPromises()
    expect(opened.store.get('audio.master_effects')).toBeUndefined()
    expect(JSON.stringify(opened.store.spec)).toBe(before)
    expect(cards(wrapper)).toHaveLength(0)
  })
})

describe('AudioEffectsSection: ligar, desligar e remover', () => {
  it('desligar grava enabled false e apaga o cartão; ligar tira a chave', async () => {
    const { opened, wrapper } = await mountEffects()
    await addEffect(wrapper, 'amplify')
    await card(wrapper, 0).find('[data-effect-toggle]').trigger('click')
    expect(effectsAt(opened, 'audio.master_effects')).toEqual([{ type: 'amplify', gain_db: 0, prevent_clipping: false, enabled: false }])
    expect(card(wrapper, 0).classes()).toContain('is-off')
    expect(card(wrapper, 0).find('[data-effect-toggle]').attributes('aria-checked')).toBe('false')
    await card(wrapper, 0).find('[data-effect-toggle]').trigger('click')
    expect(effectsAt(opened, 'audio.master_effects')).toEqual([{ type: 'amplify', gain_db: 0, prevent_clipping: false }])
    expect(card(wrapper, 0).classes()).not.toContain('is-off')
  })

  it('remover tira o cartão; o último remove a chave da spec', async () => {
    const { opened, wrapper } = await mountEffects()
    await addEffect(wrapper, 'amplify')
    await addEffect(wrapper, 'invert')
    await card(wrapper, 0).find('[data-effect-remove]').trigger('click')
    expect(cardTypes(wrapper)).toEqual(['invert'])
    expect(effectsAt(opened, 'audio.master_effects')).toEqual([{ type: 'invert' }])
    await card(wrapper, 0).find('[data-effect-remove]').trigger('click')
    expect(opened.store.get('audio')).not.toHaveProperty('master_effects')
    expect(wrapper.find('[data-effects-empty]').exists()).toBe(true)
  })

  it('desfazer a remoção traz o efeito de volta', async () => {
    const { opened, wrapper } = await mountEffects()
    await addEffect(wrapper, 'amplify')
    await card(wrapper, 0).find('[data-effect-remove]').trigger('click')
    expect(opened.store.undo()).toBe(true)
    await flushPromises()
    expect(cardTypes(wrapper)).toEqual(['amplify'])
  })
})

describe('AudioEffectsSection: reordenar', () => {
  async function withThree() {
    const mounted = await mountEffects()
    for (const type of ['amplify', 'normalize', 'invert']) await addEffect(mounted.wrapper, type)
    return mounted
  }

  it('os botões subir e descer mudam a ordem do processamento', async () => {
    const { opened, wrapper } = await withThree()
    expect(card(wrapper, 0).find('[data-effect-move="up"]').attributes('disabled')).toBeDefined()
    expect(card(wrapper, 2).find('[data-effect-move="down"]').attributes('disabled')).toBeDefined()
    await card(wrapper, 0).find('[data-effect-move="down"]').trigger('click')
    expect(cardTypes(wrapper)).toEqual(['normalize', 'amplify', 'invert'])
    expect(effectsAt(opened, 'audio.master_effects')!.map((effect) => effect.type)).toEqual(['normalize', 'amplify', 'invert'])
    await card(wrapper, 2).find('[data-effect-move="up"]').trigger('click')
    expect(cardTypes(wrapper)).toEqual(['normalize', 'invert', 'amplify'])
  })

  it('os botões têm nome acessível com o efeito', async () => {
    const { wrapper } = await withThree()
    expect(card(wrapper, 1).find('[data-effect-move="up"]').attributes('aria-label')).toBe('Subir o efeito Normalizar')
    expect(card(wrapper, 1).find('[data-effect-move="down"]').attributes('aria-label')).toBe('Descer o efeito Normalizar')
    expect(card(wrapper, 1).find('[data-effect-remove]').attributes('aria-label')).toBe('Remover o efeito Normalizar')
    expect(card(wrapper, 1).find('[data-effect-toggle]').attributes('aria-label')).toBe('Desligar o efeito Normalizar')
  })

  it('arrastar pela alça e soltar sobre outro cartão move o efeito', async () => {
    const { opened, wrapper } = await withThree()
    const data = { setData: vi.fn(), effectAllowed: '', dropEffect: '' }
    await card(wrapper, 0).find('[data-effect-grip]').trigger('dragstart', { dataTransfer: data })
    expect(card(wrapper, 0).classes()).toContain('is-dragging')
    await card(wrapper, 2).trigger('dragover', { dataTransfer: data })
    expect(card(wrapper, 2).classes()).toContain('is-drop-target')
    await card(wrapper, 2).trigger('drop', { dataTransfer: data })
    await card(wrapper, 2).find('[data-effect-grip]').trigger('dragend', { dataTransfer: data })
    expect(cardTypes(wrapper)).toEqual(['normalize', 'invert', 'amplify'])
    expect(effectsAt(opened, 'audio.master_effects')!.map((effect) => effect.type)).toEqual(['normalize', 'invert', 'amplify'])
    expect(wrapper.findAll('.is-dragging, .is-drop-target')).toHaveLength(0)
  })

  it('soltar sobre o próprio cartão não muda nada', async () => {
    const { opened, wrapper } = await withThree()
    const before = JSON.stringify(opened.store.spec)
    const history = opened.store.canUndo
    const data = { setData: vi.fn(), effectAllowed: '', dropEffect: '' }
    await card(wrapper, 1).find('[data-effect-grip]').trigger('dragstart', { dataTransfer: data })
    await card(wrapper, 1).trigger('drop', { dataTransfer: data })
    expect(JSON.stringify(opened.store.spec)).toBe(before)
    expect(opened.store.canUndo).toBe(history)
  })

  it('o que vem de fora (um arquivo, um painel) não é aceito: o evento segue para quem o trata', async () => {
    const { opened, wrapper } = await withThree()
    const before = JSON.stringify(opened.store.spec)
    for (const type of ['dragover', 'drop']) {
      const event = new Event(type, { bubbles: true, cancelable: true })
      card(wrapper, 0).element.dispatchEvent(event)
      expect(event.defaultPrevented).toBe(false)
    }
    expect(JSON.stringify(opened.store.spec)).toBe(before)
    // o arraste que saiu de uma alça daqui é aceito
    await card(wrapper, 0).find('[data-effect-grip]').trigger('dragstart', { dataTransfer: { setData: vi.fn(), effectAllowed: '' } })
    const own = new Event('dragover', { bubbles: true, cancelable: true })
    card(wrapper, 1).element.dispatchEvent(own)
    expect(own.defaultPrevented).toBe(true)
  })

  it('o cartão guarda o que a pessoa digitou quando muda de lugar', async () => {
    const { opened, wrapper } = await withThree()
    await input(wrapper, 0, 'gain_db').setValue('9')
    await card(wrapper, 0).find('[data-effect-move="down"]').trigger('click')
    // a digitação que esperava foi gravada antes de mover
    expect(effectsAt(opened, 'audio.master_effects')![1]).toMatchObject({ type: 'amplify', gain_db: 9 })
    expect((input(wrapper, 1, 'gain_db').element as HTMLInputElement).value).toBe('9')
  })
})

describe('AudioEffectsSection: parâmetros', () => {
  it('o número digitado espera 300 ms de silêncio e vira um passo só do desfazer', async () => {
    const { opened, wrapper } = await mountEffects()
    await addEffect(wrapper, 'amplify')
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    await input(wrapper, 0, 'gain_db').setValue('3')
    await vi.advanceTimersByTimeAsync(299)
    expect(effectsAt(opened, 'audio.master_effects')![0]!.gain_db).toBe(0)
    await vi.advanceTimersByTimeAsync(1)
    expect(effectsAt(opened, 'audio.master_effects')![0]!.gain_db).toBe(3)
    await input(wrapper, 0, 'gain_db').setValue('4.5')
    await vi.advanceTimersByTimeAsync(300)
    expect(effectsAt(opened, 'audio.master_effects')![0]!.gain_db).toBe(4.5)
    vi.useRealTimers()
    // adicionar vale um passo, e as duas digitações no mesmo campo, outro
    expect(undoSteps(opened)).toBe(2)
  })

  it('o número fora da faixa do catálogo é limitado, nunca gravado como está', async () => {
    const { opened, wrapper } = await mountEffects()
    await addEffect(wrapper, 'amplify')
    await input(wrapper, 0, 'gain_db').setValue('150')
    expect(card(wrapper, 0).text()).toContain('Use de -100 a 100.')
    await input(wrapper, 0, 'gain_db').trigger('focusout')
    expect(effectsAt(opened, 'audio.master_effects')![0]!.gain_db).toBe(100)
    expect((input(wrapper, 0, 'gain_db').element as HTMLInputElement).value).toBe('100')
    await input(wrapper, 0, 'gain_db').setValue('-500')
    await input(wrapper, 0, 'gain_db').trigger('focusout')
    expect(effectsAt(opened, 'audio.master_effects')![0]!.gain_db).toBe(-100)
  })

  it('o inteiro arredonda e respeita o mínimo', async () => {
    const { opened, wrapper } = await mountEffects()
    await choose(opened, 'VO-0')
    await addEffect(wrapper, 'repeat')
    await input(wrapper, 0, 'times').setValue('3.6')
    await input(wrapper, 0, 'times').trigger('focusout')
    expect(effectsAt(opened, 'audio.voiceover.0.effects')![0]!.times).toBe(4)
    await input(wrapper, 0, 'times').setValue('0')
    await input(wrapper, 0, 'times').trigger('focusout')
    expect(effectsAt(opened, 'audio.voiceover.0.effects')![0]!.times).toBe(1)
  })

  it('o campo numérico mostra o limite, o passo e a unidade do catálogo', async () => {
    const { wrapper } = await mountEffects()
    await addEffect(wrapper, 'amplify')
    const gain = input(wrapper, 0, 'gain_db').element as HTMLInputElement
    expect([gain.min, gain.max, gain.step]).toEqual(['-100', '100', '0.1'])
    expect(card(wrapper, 0).find('[data-effect-param="gain_db"]').text()).toContain('dB')
    expect(card(wrapper, 0).find('[data-effect-param="gain_db"]').text()).toContain('Ganho em dB: positivo sobe o volume, negativo desce.')
    await addEffect(wrapper, 'normalize')
    expect(card(wrapper, 1).find('[data-effect-param="peak_db"]').text()).toContain('dBFS')
  })

  it('esvaziar o campo e sair não apaga o valor da spec', async () => {
    const { opened, wrapper } = await mountEffects()
    await addEffect(wrapper, 'amplify')
    await input(wrapper, 0, 'gain_db').setValue('5')
    await input(wrapper, 0, 'gain_db').trigger('focusout')
    await input(wrapper, 0, 'gain_db').setValue('')
    await input(wrapper, 0, 'gain_db').trigger('focusout')
    expect(effectsAt(opened, 'audio.master_effects')![0]!.gain_db).toBe(5)
    expect((input(wrapper, 0, 'gain_db').element as HTMLInputElement).value).toBe('5')
  })

  it('a caixa de marcar grava na hora, cada clique num passo do desfazer', async () => {
    const { opened, wrapper } = await mountEffects()
    await addEffect(wrapper, 'amplify')
    await input(wrapper, 0, 'prevent_clipping').setValue(true)
    expect(effectsAt(opened, 'audio.master_effects')![0]!.prevent_clipping).toBe(true)
    await input(wrapper, 0, 'prevent_clipping').setValue(false)
    expect(effectsAt(opened, 'audio.master_effects')![0]!.prevent_clipping).toBe(false)
    // adicionar e os dois cliques: três passos
    expect(undoSteps(opened)).toBe(3)
  })

  it('a escolha lista as opções do catálogo e grava na hora', async () => {
    const catalog = audioEffectCatalog()
    catalog.effects.push({
      type: 'fade',
      label: 'Fade',
      audacity_name: 'Fade',
      summary: '',
      changes_duration: false,
      parameters: [{ name: 'curve', label: 'Curva', kind: 'choice', unit: '', default: 'linear', minimum: null, maximum: null, hint: '', options: ['linear', 'log'] }],
    })
    const { opened, wrapper } = await mountEffects(effectsSpec(), { 'GET /api/audio-effects': catalog })
    await addEffect(wrapper, 'fade')
    const select = card(wrapper, 0).find('[data-effect-param="curve"] select')
    expect([...(select.element as HTMLSelectElement).options].map((option) => option.value)).toEqual(['linear', 'log'])
    expect((select.element as HTMLSelectElement).value).toBe('linear')
    await select.setValue('log')
    expect(effectsAt(opened, 'audio.master_effects')![0]!.curve).toBe('log')
  })

  it('os campos de cada unidade só aparecem no modo dela (shown_when), sem um if por tipo', async () => {
    const catalog = audioEffectCatalog()
    const field = (name: string, label: string, kind: 'number' | 'choice', extra: Record<string, unknown> = {}) => ({
      name,
      label,
      kind,
      unit: '',
      default: null,
      minimum: null,
      maximum: null,
      hint: '',
      options: [],
      ...extra,
    })
    catalog.effects.push({
      type: 'change_pitch',
      label: 'Mudar Tom',
      audacity_name: 'Change Pitch',
      summary: '',
      changes_duration: false,
      parameters: [
        field('mode', 'Unidade', 'choice', { default: 'semitones', options: ['semitones', 'percent'] }),
        field('semitones', 'Semitons', 'number', { default: 0, shown_when: { mode: 'semitones' } }),
        field('percent', 'Mudança de frequência', 'number', { default: 0, shown_when: { mode: 'percent' } }),
      ],
    })
    const { opened, wrapper } = await mountEffects(effectsSpec(), { 'GET /api/audio-effects': catalog })
    await addEffect(wrapper, 'change_pitch')
    const shown = () =>
      card(wrapper, 0)
        .findAll('.effect__body > .effect__fields [data-effect-param]')
        .map((element) => element.attributes('data-effect-param'))
    expect(shown()).toEqual(['mode', 'semitones'])
    await card(wrapper, 0).find('[data-effect-param="mode"] select').setValue('percent')
    expect(shown()).toEqual(['mode', 'percent'])
    expect(effectsAt(opened, 'audio.master_effects')![0]!.mode).toBe('percent')
    // o valor do outro modo continua na spec: só a tela o esconde
    expect(effectsAt(opened, 'audio.master_effects')![0]!.semitones).toBe(0)
  })

  it('o efeito sem parâmetros diz que não tem', async () => {
    const { wrapper } = await mountEffects()
    await addEffect(wrapper, 'reverse')
    expect(card(wrapper, 0).text()).toContain('Este efeito não tem parâmetros.')
  })
})

describe('AudioEffectsSection: intervalo', () => {
  async function withOne() {
    const mounted = await mountEffects()
    await addEffect(mounted.wrapper, 'amplify')
    return mounted
  }
  const bound = (wrapper: VueWrapper, name: 'start' | 'end') => card(wrapper, 0).find(`[data-effect-interval] [data-effect-param="${name}"] input`)

  it('é recolhido e diz que vale o item todo; o início e o fim ficam fora da spec', async () => {
    const { opened, wrapper } = await withOne()
    const interval = card(wrapper, 0).find('[data-effect-interval]')
    expect(interval.attributes('open')).toBeUndefined()
    expect(interval.text()).toContain('item todo')
    expect(interval.text()).toContain('Fora do intervalo o som passa intacto.')
    expect(effectsAt(opened, 'audio.master_effects')![0]).not.toHaveProperty('start')
    expect(effectsAt(opened, 'audio.master_effects')![0]).not.toHaveProperty('end')
  })

  it('grava o início e o fim em segundos, e esvaziar apaga a chave', async () => {
    const { opened, wrapper } = await withOne()
    await bound(wrapper, 'start').setValue('1.5')
    await bound(wrapper, 'start').trigger('focusout')
    await bound(wrapper, 'end').setValue('4')
    await bound(wrapper, 'end').trigger('focusout')
    expect(effectsAt(opened, 'audio.master_effects')![0]).toMatchObject({ start: 1.5, end: 4 })
    expect(card(wrapper, 0).find('[data-effect-interval]').text()).toContain('1,5 s a 4,0 s')
    await bound(wrapper, 'start').setValue('')
    await bound(wrapper, 'start').trigger('focusout')
    expect(effectsAt(opened, 'audio.master_effects')![0]).not.toHaveProperty('start')
    expect(card(wrapper, 0).find('[data-effect-interval]').text()).toContain('até 4,0 s')
  })

  it('um fim antes do início fica na tela com o aviso e não vai para a spec', async () => {
    const { opened, wrapper } = await withOne()
    await bound(wrapper, 'start').setValue('5')
    await bound(wrapper, 'start').trigger('focusout')
    await bound(wrapper, 'end').setValue('2')
    await bound(wrapper, 'end').trigger('focusout')
    expect(card(wrapper, 0).text()).toContain('O fim precisa ser maior que o início.')
    expect(effectsAt(opened, 'audio.master_effects')![0]).not.toHaveProperty('end')
    await bound(wrapper, 'end').setValue('8')
    await bound(wrapper, 'end').trigger('focusout')
    expect(card(wrapper, 0).text()).not.toContain('O fim precisa ser maior que o início.')
    expect(effectsAt(opened, 'audio.master_effects')![0]).toMatchObject({ start: 5, end: 8 })
  })

  it('o início negativo é limitado a zero', async () => {
    const { opened, wrapper } = await withOne()
    await bound(wrapper, 'start').setValue('-3')
    await bound(wrapper, 'start').trigger('focusout')
    expect(effectsAt(opened, 'audio.master_effects')![0]).toMatchObject({ start: 0 })
  })

  it('já abre quando a spec tem intervalo', async () => {
    const spec = effectsSpec()
    spec.audio = { ...(spec.audio as object), master_effects: [{ type: 'invert', start: 1, end: 2 }] }
    const { wrapper } = await mountEffects(spec)
    const interval = card(wrapper, 0).find('[data-effect-interval]')
    expect(interval.attributes('open')).toBeDefined()
    expect(interval.text()).toContain('1,0 s a 2,0 s')
  })
})

describe('AudioEffectsSection: cada ação é um passo do desfazer', () => {
  it('adicionar, ligar, mover, mudar um valor e remover: cinco passos, desfeitos um a um', async () => {
    const { opened, wrapper } = await mountEffects()
    await addEffect(wrapper, 'amplify')
    await addEffect(wrapper, 'invert')
    // dois passos de adicionar, mais um por ação abaixo
    await card(wrapper, 0).find('[data-effect-toggle]').trigger('click')
    await card(wrapper, 0).find('[data-effect-move="down"]').trigger('click')
    await input(wrapper, 1, 'prevent_clipping').setValue(true)
    await card(wrapper, 0).find('[data-effect-remove]').trigger('click')
    expect(cardTypes(wrapper)).toEqual(['amplify'])

    // do mais novo para o mais antigo
    expect(opened.store.undo()).toBe(true)
    await flushPromises()
    expect(cardTypes(wrapper)).toEqual(['invert', 'amplify'])
    opened.store.undo()
    await flushPromises()
    expect(effectsAt(opened, 'audio.master_effects')![1]).toMatchObject({ type: 'amplify', prevent_clipping: false })
    opened.store.undo()
    await flushPromises()
    expect(cardTypes(wrapper)).toEqual(['amplify', 'invert'])
    opened.store.undo()
    await flushPromises()
    expect(effectsAt(opened, 'audio.master_effects')![0]).not.toHaveProperty('enabled')
    opened.store.undo()
    await flushPromises()
    expect(cardTypes(wrapper)).toEqual(['amplify'])
    opened.store.undo()
    await flushPromises()
    expect(opened.store.get('audio.master_effects')).toBeUndefined()
    expect(opened.store.canUndo).toBe(false)
  })

  it('refazer devolve a ação', async () => {
    const { opened, wrapper } = await mountEffects()
    await addEffect(wrapper, 'amplify')
    opened.store.undo()
    await flushPromises()
    expect(cards(wrapper)).toHaveLength(0)
    opened.store.redo()
    await flushPromises()
    expect(cardTypes(wrapper)).toEqual(['amplify'])
  })
})

describe('AudioEffectsSection: quando o catálogo não carrega', () => {
  it('avisa com discrição, não deixa adicionar e tenta de novo a pedido', async () => {
    const { opened, wrapper } = await mountEffects(effectsSpec(), { 'GET /api/audio-effects': reply(500, { detail: 'catálogo indisponível' }) })
    expect(wrapper.find('[data-effects-error]').text()).toContain('catálogo indisponível')
    expect(wrapper.find('[data-effects-add]').attributes('disabled')).toBeDefined()
    opened.fetch.set('GET /api/audio-effects', audioEffectCatalog())
    await wrapper.find('[data-effects-error] button').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-effects-error]').exists()).toBe(false)
    expect(wrapper.find('[data-effects-add]').attributes('disabled')).toBeUndefined()
    expect(await openMenu(wrapper)).toContain('amplify')
  })

  it('um catálogo fora do contrato vale como falha', async () => {
    const { wrapper } = await mountEffects(effectsSpec(), { 'GET /api/audio-effects': { effects: 'nada' } })
    expect(wrapper.find('[data-effects-error]').exists()).toBe(true)
  })

  it('os efeitos que a spec já tem seguem à mostra, só com ligar, mover e remover', async () => {
    const spec = effectsSpec()
    spec.audio = { ...(spec.audio as object), master_effects: [{ type: 'amplify', gain_db: 3 }] }
    const { opened, wrapper } = await mountEffects(spec, { 'GET /api/audio-effects': reply(500, { detail: 'fora do ar' }) })
    expect(cardTypes(wrapper)).toEqual(['amplify'])
    expect(card(wrapper, 0).find('[data-effect-param]').exists()).toBe(false)
    await card(wrapper, 0).find('[data-effect-toggle]').trigger('click')
    expect(effectsAt(opened, 'audio.master_effects')).toEqual([{ type: 'amplify', gain_db: 3, enabled: false }])
  })

  it('um efeito de tipo desconhecido (de um servidor mais novo) aparece pelo nome do tipo', async () => {
    const spec = effectsSpec()
    spec.audio = { ...(spec.audio as object), master_effects: [{ type: 'phaser', rate: 2 }] }
    const { opened, wrapper } = await mountEffects(spec)
    expect(card(wrapper, 0).text()).toContain('phaser')
    expect(card(wrapper, 0).text()).toContain('fora do catálogo')
    expect(card(wrapper, 0).find('[data-effect-param]').exists()).toBe(false)
    await card(wrapper, 0).find('[data-effect-remove]').trigger('click')
    expect(opened.store.get('audio')).not.toHaveProperty('master_effects')
  })

  it('carrega o catálogo uma vez só', async () => {
    const { opened, wrapper } = await mountEffects()
    await addEffect(wrapper, 'invert')
    expect(opened.fetch.to('GET /api/audio-effects')).toHaveLength(1)
  })
})

describe('AudioEffectsSection: no painel Filtros', () => {
  it('aparece abaixo dos grupos de filtros, e o resto do painel segue funcionando', async () => {
    const opened = await openEditor(effectsSpec(), {
      'GET /api/schema': filterSchema(),
      'GET /api/audio-effects': audioEffectCatalog(),
      'POST /api/projects/demo/timeline': () => effectsView(),
    })
    const wrapper = await mountEditorPart(FiltersPanel, opened, {}, true)
    expect(wrapper.find('[data-audio-effects]').exists()).toBe(true)
    expect(wrapper.text()).toContain('Nenhum filtro aplicado')
    await choose(opened, 'V1-0')
    expect(wrapper.text()).toContain('Clipe')
    expect(target(wrapper)).toBe('Som do clipe 1 · clip.0')
    // os filtros do item e os efeitos de áudio dele ficam no mesmo painel
    const groups = wrapper.find('.filters__body').element.children
    expect(groups[groups.length - 1]).toBe(wrapper.find('[data-audio-effects]').element)
  })

  it('sem o catálogo de efeitos o painel Filtros continua inteiro', async () => {
    const opened = await openEditor(effectsSpec(), {
      'GET /api/schema': filterSchema(),
      'POST /api/projects/demo/timeline': () => effectsView(),
    })
    const wrapper = await mountEditorPart(FiltersPanel, opened, {}, true)
    expect(wrapper.find('[aria-label="Adicionar filtro"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('[data-effects-error]').exists()).toBe(true)
  })
})
