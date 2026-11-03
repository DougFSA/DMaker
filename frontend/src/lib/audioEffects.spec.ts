import { describe, expect, it } from 'vitest'
import type { AudioEffectSettings, TimelineItem } from '@/api'
import { audioEffectCatalog } from '@/test/audioEffectsFixtures'
import { timelineItem, timelineTrack } from '@/test/editorFixtures'
import {
  addEffectIn,
  chainOf,
  clampParam,
  effectContextFor,
  effectPath,
  effectsFor,
  intervalProblem,
  isEnabled,
  MASTER_LIST_PATH,
  MASTER_TITLE,
  moveEffectIn,
  newEffect,
  paramValue,
  removeEffectIn,
  setEffectFieldIn,
  setEnabledIn,
  targetMayGrow,
} from './audioEffects'

const catalog = audioEffectCatalog()
const info = (type: string) => catalog.effects.find((effect) => effect.type === type)!

function item(index: number, kind: string, label = `item ${index}`): Pick<TimelineItem, 'kind' | 'index' | 'label'> {
  return { kind, index, label }
}

/** A V1 com um clipe, uma imagem e um cartão, que a faixa A1 espelha pelo índice. */
const view = {
  tracks: [
    timelineTrack('V1', [
      timelineItem(0, { id: 'V1-0', kind: 'clip', label: 'entrevista.mp4' }),
      timelineItem(1, { id: 'V1-1', kind: 'image', label: 'foto.png' }),
      timelineItem(2, { id: 'V1-2', kind: 'card', label: 'Fim' }),
    ]),
  ],
}

function chainOfSelection(trackId: string, selected: Pick<TimelineItem, 'kind' | 'index' | 'label'>) {
  const context = effectContextFor({ trackId, item: selected }, view)
  return context.kind === 'chain' ? context.chain : null
}

describe('a cadeia que a seleção edita', () => {
  it('sem seleção é o master, a mistura inteira', () => {
    const context = effectContextFor(null, view)
    expect(context).toEqual({
      kind: 'chain',
      chain: { targetKey: 'audio.master', listPath: 'audio.master_effects', title: MASTER_TITLE },
    })
    expect(MASTER_LIST_PATH).toBe('audio.master_effects')
    expect(MASTER_TITLE).toBe('Master (mistura inteira)')
  })

  it('o clipe da V1 edita o som dele em timeline.N', () => {
    expect(chainOfSelection('V1', item(0, 'clip', 'C:/pasta/entrevista.mp4'))).toEqual({
      targetKey: 'timeline.N',
      listPath: 'timeline.0.effects',
      title: 'Som do clipe 1 · entrevista.mp4',
    })
  })

  it('a faixa A1 edita o clipe da V1 de mesmo índice', () => {
    expect(chainOfSelection('A1', item(0, 'clip-audio'))?.listPath).toBe('timeline.0.effects')
  })

  it('imagem e cartão da V1 não têm som, nem a sombra deles na A1', () => {
    expect(effectContextFor({ trackId: 'V1', item: item(1, 'image') }, view)).toEqual({ kind: 'silent' })
    expect(effectContextFor({ trackId: 'V1', item: item(2, 'card') }, view)).toEqual({ kind: 'silent' })
    expect(effectContextFor({ trackId: 'A1', item: item(1, 'clip-audio') }, view)).toEqual({ kind: 'silent' })
  })

  it('a A1 sem a V1 na vista não adivinha', () => {
    expect(effectContextFor({ trackId: 'A1', item: item(0, 'clip-audio') }, null)).toEqual({ kind: 'silent' })
  })

  it('as faixas externas A2, A3... editam audio.tracks.N pelo índice do item', () => {
    expect(chainOfSelection('A2', item(0, 'track', 'mesa.wav'))).toEqual({
      targetKey: 'audio.tracks.N',
      listPath: 'audio.tracks.0.effects',
      title: 'Faixa de áudio A2 · mesa.wav',
    })
    expect(chainOfSelection('A3', item(1, 'track'))?.listPath).toBe('audio.tracks.1.effects')
    expect(chainOfSelection('A12', item(10, 'track'))?.listPath).toBe('audio.tracks.10.effects')
  })

  it('a música edita audio.music.effects', () => {
    expect(chainOfSelection('MUS', item(0, 'music', 'musica.mp3'))).toEqual({
      targetKey: 'audio.music',
      listPath: 'audio.music.effects',
      title: 'Música · musica.mp3',
    })
  })

  it('a narração edita audio.narration.N', () => {
    expect(chainOfSelection('NAR', item(1, 'narration', 'Olá, mundo'))).toEqual({
      targetKey: 'audio.narration.N',
      listPath: 'audio.narration.1.effects',
      title: 'Narração 2 · Olá, mundo',
    })
  })

  it('a voz gravada (trilha VO) edita audio.voiceover.N', () => {
    expect(chainOfSelection('VO', item(0, 'voiceover', 'podcast.wav'))).toEqual({
      targetKey: 'audio.voiceover.N',
      listPath: 'audio.voiceover.0.effects',
      title: 'Voz gravada 1 · podcast.wav',
    })
  })

  it('o vídeo sobreposto (V2, V3...) edita o som do PiP em overlays.N', () => {
    expect(chainOfSelection('V2', item(1, 'video', 'pip.mp4'))).toEqual({
      targetKey: 'overlays.N',
      listPath: 'overlays.1.effects',
      title: 'Som do PiP V2 · pip.mp4',
    })
    expect(chainOfSelection('V3', item(0, 'video'))?.listPath).toBe('overlays.0.effects')
  })

  it('texto, gráficos, legendas e o que não é vídeo numa camada V2 não têm som', () => {
    for (const [trackId, kind] of [
      ['TX', 'text'],
      ['GR', 'image'],
      ['GR', 'progress-bar'],
      ['CC', 'captions'],
      ['V2', 'image'],
      ['XX', 'outra'],
    ] as const) {
      expect(effectContextFor({ trackId, item: item(0, kind) }, view)).toEqual({ kind: 'silent' })
    }
  })

  it('sem rótulo o título fica só com o nome do lugar', () => {
    expect(chainOfSelection('MUS', item(0, 'music', ''))?.title).toBe('Música')
  })
})

describe('onde o Repetir vale', () => {
  it('só onde o catálogo diz que o item pode crescer', () => {
    expect(targetMayGrow(catalog.targets, 'audio.voiceover.N')).toBe(true)
    expect(targetMayGrow(catalog.targets, 'audio.music')).toBe(true)
    for (const key of ['timeline.N', 'overlays.N', 'audio.narration.N', 'audio.tracks.N', 'audio.master']) {
      expect(targetMayGrow(catalog.targets, key)).toBe(false)
    }
  })

  it('lugar que o catálogo não conhece não cresce', () => {
    expect(targetMayGrow(catalog.targets, 'audio.novo')).toBe(false)
    expect(targetMayGrow([], 'audio.music')).toBe(false)
  })

  it('o menu esconde os efeitos que mudam a duração onde o item não cresce', () => {
    expect(effectsFor(catalog.effects, false).map((effect) => effect.type)).toEqual(['amplify', 'normalize', 'invert', 'reverse'])
    expect(effectsFor(catalog.effects, true).map((effect) => effect.type)).toEqual(['amplify', 'normalize', 'invert', 'reverse', 'repeat'])
  })
})

describe('o efeito novo', () => {
  it('leva o type e os padrões do catálogo, sem enabled nem intervalo', () => {
    expect(newEffect(info('amplify'))).toEqual({ type: 'amplify', gain_db: 0, prevent_clipping: false })
    expect(newEffect(info('normalize'))).toEqual({ type: 'normalize', peak_db: -1, remove_dc: true, stereo_independent: false })
    expect(newEffect(info('repeat'))).toEqual({ type: 'repeat', times: 2 })
  })

  it('o efeito sem parâmetros é só o type', () => {
    expect(newEffect(info('invert'))).toEqual({ type: 'invert' })
  })

  it('parâmetro sem padrão fica de fora', () => {
    const open = { ...info('amplify'), parameters: [{ ...info('amplify').parameters[0]!, default: null }] }
    expect(newEffect(open)).toEqual({ type: 'amplify' })
  })
})

describe('ler o efeito', () => {
  const amplify = info('amplify')
  const gain = amplify.parameters[0]!
  const clip = amplify.parameters[1]!

  it('o enabled omitido vale ligado', () => {
    expect(isEnabled({})).toBe(true)
    expect(isEnabled({ enabled: true })).toBe(true)
    expect(isEnabled({ enabled: false })).toBe(false)
  })

  it('o valor da spec vale; sem ele, o padrão do catálogo', () => {
    expect(paramValue({ type: 'amplify', gain_db: 6 }, gain)).toBe(6)
    expect(paramValue({ type: 'amplify' }, gain)).toBe(0)
    expect(paramValue({ type: 'amplify', prevent_clipping: true }, clip)).toBe(true)
    expect(paramValue({ type: 'amplify' }, clip)).toBe(false)
  })

  it('a escolha lê o texto e cai no padrão', () => {
    const choice = { name: 'mode', kind: 'choice' as const, default: 'soft' }
    expect(paramValue({ type: 'x', mode: 'hard' }, choice)).toBe('hard')
    expect(paramValue({ type: 'x' }, choice)).toBe('soft')
    expect(paramValue({ type: 'x' }, { ...choice, default: null })).toBeNull()
  })

  it('valor de tipo errado na spec não passa pelo formulário', () => {
    expect(paramValue({ type: 'amplify', gain_db: 'alto' }, gain)).toBe(0)
    expect(paramValue({ type: 'amplify', prevent_clipping: 'sim' }, clip)).toBe(false)
  })
})

describe('limites do catálogo', () => {
  const gain = info('amplify').parameters[0]!
  const times = info('repeat').parameters[0]!

  it('limita o número à faixa', () => {
    expect(clampParam(gain, 150)).toBe(100)
    expect(clampParam(gain, -150)).toBe(-100)
    expect(clampParam(gain, 3.5)).toBe(3.5)
  })

  it('o inteiro arredonda antes de limitar', () => {
    expect(clampParam(times, 2.6)).toBe(3)
    expect(clampParam(times, 0)).toBe(1)
    expect(clampParam(times, 1000)).toBe(100)
  })

  it('sem limite não limita', () => {
    expect(clampParam({ kind: 'number', minimum: 0, maximum: null }, 9999)).toBe(9999)
    expect(clampParam({ kind: 'number', minimum: 0, maximum: null }, -3)).toBe(0)
  })

  it('o fim do intervalo tem de vir depois do início', () => {
    expect(intervalProblem(1, 4)).toBeNull()
    expect(intervalProblem(4, 4)).toBe('O fim precisa ser maior que o início.')
    expect(intervalProblem(5, 2)).toBe('O fim precisa ser maior que o início.')
    expect(intervalProblem(null, 2)).toBeNull()
    expect(intervalProblem(3, undefined)).toBeNull()
  })
})

describe('mudar a cadeia na spec', () => {
  function specWith(effects?: AudioEffectSettings[]): Record<string, unknown> {
    return { audio: { music: { src: 'm.mp3', ...(effects ? { effects } : {}) } }, timeline: [{ type: 'clip', src: 'a.mp4' }] }
  }

  it('adicionar cria a lista que faltava e depois acrescenta ao fim', () => {
    const spec = specWith()
    expect(addEffectIn(spec, 'audio.music.effects', { type: 'invert' })).toBe(0)
    expect(addEffectIn(spec, 'audio.music.effects', { type: 'reverse' })).toBe(1)
    expect(chainOf(spec, 'audio.music.effects').map((effect) => effect.type)).toEqual(['invert', 'reverse'])
  })

  it('o master mora em audio.master_effects e a lista nasce sozinha', () => {
    const spec: Record<string, unknown> = {}
    addEffectIn(spec, MASTER_LIST_PATH, { type: 'normalize' })
    expect(spec).toEqual({ audio: { master_effects: [{ type: 'normalize' }] } })
  })

  it('o clipe guarda os efeitos nele mesmo', () => {
    const spec = specWith()
    addEffectIn(spec, 'timeline.0.effects', { type: 'amplify', gain_db: 3 })
    expect((spec.timeline as Array<Record<string, unknown>>)[0]).toEqual({
      type: 'clip',
      src: 'a.mp4',
      effects: [{ type: 'amplify', gain_db: 3 }],
    })
  })

  it('remover o último efeito tira a chave da spec: projeto sem efeito fica como era', () => {
    const spec = specWith([{ type: 'invert' }])
    expect(removeEffectIn(spec, 'audio.music.effects', 0)).toBe(true)
    expect(spec).toEqual({ audio: { music: { src: 'm.mp3' } }, timeline: [{ type: 'clip', src: 'a.mp4' }] })
    expect(spec.audio).not.toHaveProperty('music.effects')
  })

  it('esvaziar o master tira audio.master_effects', () => {
    const spec: Record<string, unknown> = { audio: { voice_gain: 1, master_effects: [{ type: 'invert' }] } }
    removeEffectIn(spec, MASTER_LIST_PATH, 0)
    expect(spec).toEqual({ audio: { voice_gain: 1 } })
  })

  it('remover um do meio mantém os outros na ordem', () => {
    const spec = specWith([{ type: 'invert' }, { type: 'reverse' }, { type: 'amplify' }])
    removeEffectIn(spec, 'audio.music.effects', 1)
    expect(chainOf(spec, 'audio.music.effects').map((effect) => effect.type)).toEqual(['invert', 'amplify'])
  })

  it('remover posição que não existe não muda nada', () => {
    const spec = specWith([{ type: 'invert' }])
    expect(removeEffectIn(spec, 'audio.music.effects', 3)).toBe(false)
    expect(removeEffectIn(spec, 'audio.music.effects', -1)).toBe(false)
    expect(removeEffectIn(spec, 'audio.voiceover.0.effects', 0)).toBe(false)
    expect(chainOf(spec, 'audio.music.effects')).toHaveLength(1)
  })

  it('mover empurra os do meio e muda a ordem do processamento', () => {
    const spec = specWith([{ type: 'invert' }, { type: 'reverse' }, { type: 'amplify' }])
    expect(moveEffectIn(spec, 'audio.music.effects', 0, 2)).toBe(true)
    expect(chainOf(spec, 'audio.music.effects').map((effect) => effect.type)).toEqual(['reverse', 'amplify', 'invert'])
    expect(moveEffectIn(spec, 'audio.music.effects', 2, 0)).toBe(true)
    expect(chainOf(spec, 'audio.music.effects').map((effect) => effect.type)).toEqual(['invert', 'reverse', 'amplify'])
  })

  it('mover para o mesmo lugar ou para fora da lista não faz nada', () => {
    const spec = specWith([{ type: 'invert' }, { type: 'reverse' }])
    expect(moveEffectIn(spec, 'audio.music.effects', 1, 1)).toBe(false)
    expect(moveEffectIn(spec, 'audio.music.effects', 1, 2)).toBe(false)
    expect(moveEffectIn(spec, 'audio.music.effects', 0, -1)).toBe(false)
    expect(chainOf(spec, 'audio.music.effects').map((effect) => effect.type)).toEqual(['invert', 'reverse'])
  })

  it('desligar grava enabled false, e ligar tira a chave (omitido vale ligado)', () => {
    const spec = specWith([{ type: 'invert' }])
    expect(setEnabledIn(spec, 'audio.music.effects', 0, false)).toBe(true)
    expect(chainOf(spec, 'audio.music.effects')).toEqual([{ type: 'invert', enabled: false }])
    expect(setEnabledIn(spec, 'audio.music.effects', 0, true)).toBe(true)
    expect(chainOf(spec, 'audio.music.effects')).toEqual([{ type: 'invert' }])
    expect(setEnabledIn(spec, 'audio.music.effects', 4, false)).toBe(false)
  })

  it('muda um parâmetro e o intervalo, e apagar a chave volta ao padrão do servidor', () => {
    const spec = specWith([{ type: 'amplify', gain_db: 0, prevent_clipping: false }])
    expect(setEffectFieldIn(spec, 'audio.music.effects', 0, 'gain_db', 6)).toBe(true)
    expect(setEffectFieldIn(spec, 'audio.music.effects', 0, 'start', 1.5)).toBe(true)
    expect(setEffectFieldIn(spec, 'audio.music.effects', 0, 'end', 4)).toBe(true)
    expect(chainOf(spec, 'audio.music.effects')[0]).toEqual({ type: 'amplify', gain_db: 6, prevent_clipping: false, start: 1.5, end: 4 })
    setEffectFieldIn(spec, 'audio.music.effects', 0, 'start', undefined)
    setEffectFieldIn(spec, 'audio.music.effects', 0, 'end', undefined)
    expect(chainOf(spec, 'audio.music.effects')[0]).toEqual({ type: 'amplify', gain_db: 6, prevent_clipping: false })
  })

  it('mudar um efeito que não existe não cria nada', () => {
    const spec = specWith([{ type: 'invert' }])
    expect(setEffectFieldIn(spec, 'audio.music.effects', 2, 'gain_db', 1)).toBe(false)
    expect(setEffectFieldIn(spec, 'audio.voiceover.0.effects', 0, 'gain_db', 1)).toBe(false)
    expect(spec.audio).toEqual({ music: { src: 'm.mp3', effects: [{ type: 'invert' }] } })
  })

  it('o caminho de um campo do efeito', () => {
    expect(effectPath('timeline.2.effects', 1, 'gain_db')).toBe('timeline.2.effects.1.gain_db')
  })
})
