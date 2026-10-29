import { describe, expect, it } from 'vitest'
import { EDITOR_PANELS, componentOf, panelsIn, type EditorPanelId } from './panels'

describe('registro de painéis do editor', () => {
  it('conhece os oito painéis, cada um num encaixe', () => {
    const ids = EDITOR_PANELS.map((panel) => panel.id).sort()
    const expected: EditorPanelId[] = ['captions', 'filters', 'json', 'media', 'player', 'preview', 'properties', 'timeline']
    expect(ids).toEqual(expected)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('a bancada tem mídia, player, filtros e linha do tempo; o inspetor, as quatro abas', () => {
    expect(panelsIn('workbench').map((panel) => panel.id)).toEqual(['media', 'player', 'filters', 'timeline'])
    expect(panelsIn('inspector').map((panel) => panel.id)).toEqual(['properties', 'json', 'captions', 'preview'])
  })

  it('os painéis do inspetor existem; os da bancada esperam ser plugados (load: null)', () => {
    for (const panel of panelsIn('inspector')) expect(panel.load, panel.id).toBeTypeOf('function')
    for (const panel of panelsIn('workbench')) expect(panel.load, panel.id).toBeNull()
  })

  it('só a aba Legendas depende de uma condição', () => {
    expect(EDITOR_PANELS.filter((panel) => panel.when).map((panel) => panel.id)).toEqual(['captions'])
  })

  it('componentOf devolve null para painel sem componente e o mesmo componente em chamadas seguidas', () => {
    const player = EDITOR_PANELS.find((panel) => panel.id === 'player')!
    const json = EDITOR_PANELS.find((panel) => panel.id === 'json')!
    expect(componentOf(player)).toBeNull()
    const first = componentOf(json)
    expect(first).not.toBeNull()
    expect(componentOf(json)).toBe(first)
  })

  it('os títulos não usam travessão (regra da marca)', () => {
    for (const panel of EDITOR_PANELS) expect(panel.title).not.toMatch(/[—–]/)
  })
})
