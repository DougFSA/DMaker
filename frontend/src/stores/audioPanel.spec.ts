import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { audioWave, voiceSpec, voiceView } from '@/test/audioPanelFixtures'
import { openEditor, type OpenedEditor } from '@/test/editorMount'
import { useToastsStore } from './toasts'
import { SPEEDS, useAudioPanelStore } from './audioPanel'

let opened: OpenedEditor

async function openVoiceProject() {
  const view = voiceView()
  opened = await openEditor(voiceSpec(), {
    'POST /api/projects/demo/timeline': () => view,
    'POST /api/projects/demo/edit': () => ({ spec: voiceSpec(), timeline: view }),
  })
  const panel = useAudioPanelStore()
  const entry = opened.store.findItem('VO-0')
  expect(entry).not.toBeNull()
  return { panel, entry: entry as NonNullable<typeof entry> }
}

const edits = () => opened.fetch.to('POST /api/projects/demo/edit').map((call) => (call.body as { op: unknown }).op)

beforeEach(() => window.localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

describe('abrir o painel', () => {
  it('abre o item de áudio selecionado e guarda o alvo dele', async () => {
    const { panel, entry } = await openVoiceProject()
    expect(panel.open).toBe(false)
    expect(panel.openFor(entry)).toBe(true)
    expect(panel.open).toBe(true)
    expect(panel.target).toBe('audio.voiceover.0')
    expect(panel.title).toContain('Voz gravada 1')
  })

  it('recusa um item sem som e explica', async () => {
    const { panel } = await openVoiceProject()
    const card = opened.store.findItem('V1-0')
    expect(panel.openFor(card)).toBe(false)
    expect(panel.open).toBe(false)
    expect(useToastsStore().items.at(-1)?.title).toContain('item com som')
    expect(panel.openFor(null)).toBe(false)
  })

  it('fecha quando outro projeto é aberto', async () => {
    const { panel, entry } = await openVoiceProject()
    panel.openFor(entry)
    opened.store.close()
    await flushPromises()
    expect(panel.open).toBe(false)
    expect(panel.target).toBeNull()
  })
})

describe('a resposta do item', () => {
  it('guarda a duração, o relógio e mostra o áudio inteiro na primeira vez', async () => {
    const { panel, entry } = await openVoiceProject()
    panel.openFor(entry)
    panel.setOverview(audioWave())
    expect(panel.duration).toBe(12)
    expect(panel.rate).toBe(48000)
    expect(panel.clock).toEqual({ start: 0.5, speed: 1, origin: 0 })
    expect(panel.view).toEqual({ start: 0, end: 12 })
    // uma resposta seguinte (depois de uma edição) não tira o zoom da pessoa
    panel.setView({ start: 2, end: 4 })
    panel.setOverview(audioWave({ key: 'chave-2' }))
    expect(panel.view).toEqual({ start: 2, end: 4 })
  })

  it('volta ao áudio inteiro se o item encolheu e a janela ficou fora dele', async () => {
    const { panel, entry } = await openVoiceProject()
    panel.openFor(entry)
    panel.setOverview(audioWave())
    panel.setView({ start: 8, end: 11 })
    panel.select(9, 11)
    panel.setOverview(audioWave({ duration: 6, frames: 288000 }))
    expect(panel.view).toEqual({ start: 0, end: 6 })
    expect(panel.selection).toBeNull()
  })
})

describe('selecionar e dar zoom não mudam a spec', () => {
  it('seleciona, estende, limpa e arredonda para a amostra', async () => {
    const { panel, entry } = await openVoiceProject()
    panel.openFor(entry)
    panel.setOverview(audioWave())
    panel.select(3.00001, 5)
    expect(panel.selection?.start).toBeCloseTo(3, 4)
    panel.setCursor(5)
    panel.extendTo(7)
    expect(panel.selection?.end).toBeCloseTo(7)
    panel.clearSelection()
    expect(panel.selection).toBeNull()
    panel.selectAll()
    expect(panel.selection).toEqual({ start: 0, end: 12 })
    expect(opened.store.dirty).toBe(false)
    expect(edits()).toEqual([])
  })

  it('aproxima, afasta, ajusta à seleção e ao áudio inteiro', async () => {
    const { panel, entry } = await openVoiceProject()
    panel.openFor(entry)
    panel.setOverview(audioWave())
    panel.zoomIn(6)
    expect(panel.view.end - panel.view.start).toBeCloseTo(6)
    panel.zoomOut(6)
    expect(panel.view).toEqual({ start: 0, end: 12 })
    panel.select(4, 6)
    panel.zoomToSelection()
    expect(panel.view.start).toBeCloseTo(3.9)
    expect(panel.view.end).toBeCloseTo(6.1)
    panel.zoomToRange(1, 2)
    expect(panel.view).toEqual({ start: 1, end: 2 })
    panel.zoomToProject()
    expect(panel.view).toEqual({ start: 0, end: 12 })
  })

  it('"selecionar até o marcador" vai do cursor ao marcador, no tempo do eixo do item', async () => {
    const { panel, entry } = await openVoiceProject()
    const view = voiceView()
    view.tracks.push({
      id: 'MK',
      kind: 'markers',
      label: 'MK',
      muted: false,
      hidden: false,
      locked: false,
      items: [timelineItemMarker(8.5)],
    })
    opened.store.view = view
    panel.openFor(entry)
    panel.setOverview(audioWave())
    panel.setCursor(2)
    expect(panel.selectToMarker(1)).toBe(true)
    // o marcador está em 8,5 s do projeto e o item começa em 0,5 s: 8 s do eixo
    expect(panel.selection).toEqual({ start: 2, end: 8 })
    panel.setCursor(9)
    expect(panel.selectToMarker(1)).toBe(false) // depois do cursor não há marcador
    expect(panel.selectToMarker(-1)).toBe(true) // e para trás, sim: do marcador ao cursor
    expect(panel.selection).toEqual({ start: 8, end: 9 })
  })
})

function timelineItemMarker(at: number) {
  return {
    id: 'MK-0',
    kind: 'marker',
    index: 0,
    label: 'ponto',
    start: at,
    end: at,
    in_point: 0,
    out_point: null,
    src: null,
    source: null,
    transition: null,
    muted: false,
    extra: { instant: at, group: '' },
    path: null,
  }
}

describe('os comandos viram operações do editor', () => {
  it('silenciar e cortar a seleção mandam o intervalo em tempo do projeto', async () => {
    const { panel, entry } = await openVoiceProject()
    panel.openFor(entry)
    panel.setOverview(audioWave())
    panel.select(2, 4)
    expect(await panel.silence()).toBe(true)
    expect(edits().at(-1)).toEqual({ type: 'audio_silence', target: 'audio.voiceover.0', start: 2.5, end: 4.5 })
    expect(await panel.cut()).toBe(true)
    expect(edits().at(-1)).toEqual({ type: 'audio_cut', target: 'audio.voiceover.0', start: 2.5, end: 4.5 })
    expect(panel.selection).toBeNull() // cortou: a seleção já não existe
    expect(panel.soundVersion).toBeGreaterThan(0)
  })

  it('cada comando é um passo do desfazer e segue o Salvar', async () => {
    const { panel, entry } = await openVoiceProject()
    panel.openFor(entry)
    panel.setOverview(audioWave())
    panel.select(2, 4)
    expect(opened.store.canUndo).toBe(false)
    await panel.silence()
    expect(opened.store.canUndo).toBe(true)
    // o servidor de mentira devolve a mesma spec, então o editor não fica "sujo": o que vale é o passo no histórico
    expect(opened.fetch.to('PUT /api/projects/demo')).toHaveLength(0)
  })

  it('divide só a voz gravada, no cursor', async () => {
    const { panel, entry } = await openVoiceProject()
    panel.openFor(entry)
    panel.setOverview(audioWave())
    panel.setCursor(5)
    expect(panel.canSplit).toBe(true)
    await panel.split()
    expect(edits().at(-1)).toEqual({ type: 'audio_split', target: 'audio.voiceover.0', at: 5.5 })
  })

  it('o marcador na seleção é uma região; sem seleção, um instante no cursor', async () => {
    const { panel, entry } = await openVoiceProject()
    panel.openFor(entry)
    panel.setOverview(audioWave())
    panel.select(1, 3)
    await panel.label()
    expect(edits().at(-1)).toEqual({ type: 'marker_add', start: 1.5, end: 3.5, text: '' })
    panel.clearSelection()
    panel.setCursor(4)
    await panel.label()
    expect(edits().at(-1)).toEqual({ type: 'marker_add', at: 4.5, text: '' })
  })

  it('aplicar um efeito grava o intervalo da seleção em tempo do eixo', async () => {
    const { panel, entry } = await openVoiceProject()
    panel.openFor(entry)
    panel.setOverview(audioWave())
    panel.select(2, 4)
    await panel.applyEffect('normalize', { peak_db: -1 })
    expect(edits().at(-1)).toEqual({
      type: 'audio_effect',
      action: 'add',
      target: 'audio.voiceover.0',
      effect: { type: 'normalize', peak_db: -1, start: 2, end: 4 },
    })
  })

  it('o envelope cria o efeito na primeira vez e troca os pontos nas seguintes', async () => {
    const { panel, entry } = await openVoiceProject()
    panel.openFor(entry)
    panel.setOverview(audioWave())
    await panel.applyEnvelope([{ at: 1, db: 0 }, { at: 3, db: -6 }], null)
    expect(edits().at(-1)).toEqual({
      type: 'audio_envelope',
      target: 'audio.voiceover.0',
      points: [{ at: 1.5, db: 0 }, { at: 3.5, db: -6 }],
    })
    await panel.applyEnvelope([{ at: 1, db: 0 }, { at: 3, db: -3 }], 1)
    expect(edits().at(-1)).toMatchObject({ type: 'audio_effect', action: 'set', index: 1, params: { points: [{ at: 1, db: 0 }, { at: 3, db: -3 }] } })
  })

  it('o comando recusado vira um aviso e não chama o servidor', async () => {
    const { panel, entry } = await openVoiceProject()
    panel.openFor(entry)
    panel.setOverview(audioWave())
    expect(await panel.silence()).toBe(false) // sem seleção
    expect(edits()).toEqual([])
    expect(useToastsStore().items.at(-1)?.title).toContain('Selecione um trecho')
  })
})

describe('velocidade e ferramenta', () => {
  it('a velocidade fica entre um quarto e quatro vezes', async () => {
    const { panel } = await openVoiceProject()
    panel.setSpeed(9)
    expect(panel.speed).toBe(SPEEDS[SPEEDS.length - 1])
    panel.setSpeed(0.01)
    expect(panel.speed).toBe(SPEEDS[0])
    panel.setTool('envelope')
    expect(panel.tool).toBe('envelope')
  })
})
