import { describe, expect, it } from 'vitest'
import {
  BUILTIN_NAMES,
  EDITING_AREAS,
  SIZE_DEFAULTS,
  builtinLayouts,
  clampSize,
  isBuiltinName,
  neighborSlot,
  normalizeLayout,
  placement,
  sameLayout,
  swapPanels,
  withFullAreas,
  workbenchGrid,
  type WorkbenchSlot,
} from './editorLayout'

describe('normalizeLayout', () => {
  it('de um objeto qualquer faz um layout completo, com o padrão nos tamanhos que faltam', () => {
    const layout = normalizeLayout({})
    expect(layout).toEqual({
      version: 1,
      areas: {},
      hidden: [],
      sizes: { 'row-top': 0.42, 'col-left': 240, 'col-right': 240, 'col-sidebar': 248 },
    })
  })

  it('descarta encaixe e painel que a interface não conhece, e o que não é lista ou número', () => {
    const layout = normalizeLayout({
      areas: { 'top-left': 'filters', 'canto-novo': 'media', bottom: 'painel-que-nao-existe', 'top-right': 7 },
      hidden: ['progress', 'inventado', 'progress', 3],
      sizes: { 'col-left': 'larga', 'col-right': Number.NaN },
      tab: 'planilha',
    })
    expect(layout.areas).toEqual({ 'top-left': 'filters' })
    expect(layout.hidden).toEqual(['progress'])
    expect(layout.sizes['col-left']).toBe(SIZE_DEFAULTS['col-left'])
    expect(layout.sizes['col-right']).toBe(SIZE_DEFAULTS['col-right'])
    expect(layout.tab).toBeUndefined()
  })

  it('corta os tamanhos fora da faixa', () => {
    const layout = normalizeLayout({ sizes: { 'row-top': 3, 'col-left': 10, 'col-right': 9999, 'col-sidebar': 0 } })
    expect(layout.sizes).toEqual({ 'row-top': 0.85, 'col-left': 160, 'col-right': 560, 'col-sidebar': 200 })
  })

  it('guarda a aba que o layout abre, quando é conhecida', () => {
    expect(normalizeLayout({ tab: 'voice' }).tab).toBe('voice')
    expect(normalizeLayout({ tab: 'timeline' }).tab).toBe('timeline')
  })

  it('nunca lança erro com valor que nem é objeto', () => {
    for (const raw of [null, undefined, 'texto', 42, [], true]) expect(() => normalizeLayout(raw)).not.toThrow()
    expect(normalizeLayout(null).version).toBe(1)
  })

  it('um layout salvo pela interface clássica (sem o tamanho da barra lateral) é aceito como está', () => {
    const saved = { version: 1, areas: { 'top-left': 'filters' }, sizes: { 'col-left': 300 }, hidden: ['progress'] }
    const layout = normalizeLayout(saved)
    expect(layout.sizes['col-left']).toBe(300)
    expect(layout.hidden).toEqual(['progress'])
  })
})

describe('clampSize', () => {
  it('limita cada tamanho à própria faixa', () => {
    expect(clampSize('row-top', 0)).toBe(0.1)
    expect(clampSize('col-sidebar', 1000)).toBe(520)
    expect(clampSize('col-left', 300)).toBe(300)
  })
})

describe('swapPanels', () => {
  const layout = { areas: { ...EDITING_AREAS }, sizes: {}, hidden: [] }

  it('troca os dois painéis de encaixe', () => {
    const swapped = swapPanels(layout, 'player', 'timeline')
    expect(swapped.areas['top-center']).toBe('timeline')
    expect(swapped.areas.bottom).toBe('player')
    expect(swapped.areas['top-left']).toBe('filters')
  })

  it('trocar com o mesmo painel, ou duas vezes, volta ao que era', () => {
    expect(swapPanels(layout, 'media', 'media').areas).toEqual(layout.areas)
    expect(swapPanels(swapPanels(layout, 'media', 'filters'), 'media', 'filters').areas).toEqual(layout.areas)
  })

  it('se só um dos dois está na grade, ele assume o encaixe do outro', () => {
    const partial = { areas: { 'top-left': 'filters' }, sizes: {}, hidden: [] }
    expect(swapPanels(partial, 'filters', 'media').areas).toEqual({ 'top-left': 'media' })
    expect(swapPanels(partial, 'media', 'filters').areas).toEqual({ 'top-left': 'media' })
  })

  it('sem nenhum dos dois na grade, nada muda; e o layout original não é mexido', () => {
    const partial = { areas: { 'top-left': 'filters' }, sizes: {}, hidden: [] }
    expect(swapPanels(partial, 'media', 'timeline').areas).toEqual({ 'top-left': 'filters' })
    swapPanels(layout, 'player', 'timeline')
    expect(layout.areas['top-center']).toBe('player')
  })

  it('mantém o tamanho, o que está oculto e a aba', () => {
    const swapped = swapPanels({ ...layout, sizes: { 'col-left': 400 }, hidden: ['media'], tab: 'voice' }, 'player', 'filters')
    expect(swapped.sizes['col-left']).toBe(400)
    expect(swapped.hidden).toEqual(['media'])
    expect(swapped.tab).toBe('voice')
  })
})

describe('layouts embutidos', () => {
  const builtins = builtinLayouts()

  it('são os seis da interface clássica, na mesma ordem', () => {
    expect(BUILTIN_NAMES).toEqual(['Edição', 'Efeitos', 'Áudio', 'Player', 'Revisão', 'Voz'])
    expect(isBuiltinName('Efeitos')).toBe(true)
    expect(isBuiltinName('Meu layout')).toBe(false)
  })

  it('todos partem da mesma disposição: player em cima, filtros, linha do tempo e mídia embaixo', () => {
    for (const layout of Object.values(builtins)) expect(layout.areas).toEqual(EDITING_AREAS)
  })

  it('cada um muda só o que o nome promete', () => {
    expect(builtins.Edição!.sizes['row-top']).toBe(0.42)
    expect(builtins.Efeitos!.sizes['col-left']).toBe(420)
    expect(builtins.Efeitos!.hidden).toContain('media')
    expect(builtins.Áudio!.sizes['row-top']).toBe(0.16)
    expect(builtins.Player!.sizes['row-top']).toBe(0.72)
    expect(builtins.Revisão!.sizes['row-top']).toBe(0.22)
    expect(builtins.Revisão!.hidden).toEqual([])
    expect(builtins.Voz!.tab).toBe('voice')
    expect(builtins.Edição!.tab).toBe('timeline')
  })

  it('já saem normalizados', () => {
    for (const layout of Object.values(builtins)) expect(normalizeLayout(layout)).toEqual(layout)
  })

  it('cada chamada devolve objetos novos, que ninguém altera por engano', () => {
    builtinLayouts().Edição!.hidden.push('media')
    expect(builtinLayouts().Edição!.hidden).toEqual(['progress'])
  })
})

describe('placement', () => {
  it('põe cada painel no encaixe que o layout diz', () => {
    expect(placement(builtinLayouts().Edição!)).toEqual({
      'top-center': 'player',
      'top-left': 'filters',
      bottom: 'timeline',
      'top-right': 'media',
    })
  })

  it('completa o que faltou pelo padrão', () => {
    expect(placement({ areas: { 'top-left': 'filters' }, sizes: {}, hidden: [] })).toEqual({
      'top-center': 'player',
      'top-left': 'filters',
      bottom: 'timeline',
      'top-right': 'media',
    })
  })

  it('um painel que ocupa o encaixe padrão de outro vai para o primeiro livre', () => {
    const result = placement({ areas: { 'top-center': 'timeline', bottom: 'player' }, sizes: {}, hidden: [] })
    expect(result['top-center']).toBe('timeline')
    expect(result.bottom).toBe('player')
    expect(new Set(Object.values(result))).toEqual(new Set(['player', 'timeline', 'filters', 'media']))
  })

  it('um painel repetido vale só no primeiro encaixe, e painel que não é de bancada é ignorado', () => {
    const result = placement({ areas: { 'top-center': 'player', bottom: 'player', 'top-left': 'sidebar' }, sizes: {}, hidden: [] })
    expect(Object.values(result).filter((panel) => panel === 'player')).toHaveLength(1)
    expect(Object.values(result).every((panel) => panel !== null)).toBe(true)
  })

  it('withFullAreas escreve a disposição inteira para a troca não deixar lacuna', () => {
    const full = withFullAreas({ areas: { 'top-left': 'filters' }, sizes: {}, hidden: [] })
    expect(swapPanels(full, 'media', 'player').areas).toMatchObject({ 'top-center': 'media', 'top-right': 'player' })
  })
})

describe('neighborSlot', () => {
  it('anda pela grade: a faixa de cima sobre a do meio, e esquerda, meio e direita embaixo', () => {
    expect(neighborSlot('top-center', 'down')).toBe('bottom')
    expect(neighborSlot('bottom', 'up')).toBe('top-center')
    expect(neighborSlot('bottom', 'left')).toBe('top-left')
    expect(neighborSlot('bottom', 'right')).toBe('top-right')
    expect(neighborSlot('top-left', 'right')).toBe('bottom')
    expect(neighborSlot('top-right', 'left')).toBe('bottom')
    expect(neighborSlot('top-left', 'up')).toBe('top-center')
  })

  it('onde não há vizinho, devolve null', () => {
    expect(neighborSlot('top-center', 'up')).toBeNull()
    expect(neighborSlot('top-center', 'left')).toBeNull()
    expect(neighborSlot('top-left', 'left')).toBeNull()
    expect(neighborSlot('bottom', 'down')).toBeNull()
  })
})

describe('sameLayout', () => {
  it('ignora a ordem dos ocultos e pequenas diferenças de ponto flutuante', () => {
    const a = { areas: { ...EDITING_AREAS }, sizes: { 'row-top': 0.42 }, hidden: ['media', 'progress'] }
    const b = { areas: { ...EDITING_AREAS }, sizes: { 'row-top': 0.4200001 }, hidden: ['progress', 'media'] }
    expect(sameLayout(a, b)).toBe(true)
  })

  it('percebe painel trocado, tamanho mudado e painel oculto', () => {
    const base = builtinLayouts().Edição!
    expect(sameLayout(base, swapPanels(base, 'player', 'media'))).toBe(false)
    expect(sameLayout(base, { ...base, sizes: { ...base.sizes, 'col-left': 300 } })).toBe(false)
    expect(sameLayout(base, { ...base, hidden: [...base.hidden, 'filters'] })).toBe(false)
  })
})

describe('workbenchGrid', () => {
  const all: Record<WorkbenchSlot, boolean> = { 'top-center': true, 'top-left': true, bottom: true, 'top-right': true }
  const layout = builtinLayouts().Edição!

  it('com tudo visível, usa os tamanhos do layout e os três divisores', () => {
    const grid = workbenchGrid(layout, all)
    expect(grid.columns).toBe('240px 6px minmax(0, 1fr) 6px 240px')
    expect(grid.rows).toBe('42.0% 6px minmax(0, 1fr)')
    expect([grid.showRowDivider, grid.showLeftDivider, grid.showRightDivider]).toEqual([true, true, true])
  })

  it('a coluna de um painel oculto some junto com o divisor dela', () => {
    const grid = workbenchGrid(layout, { ...all, 'top-right': false })
    expect(grid.columns).toBe('240px 6px minmax(0, 1fr) 0px 0px')
    expect(grid.showRightDivider).toBe(false)
  })

  it('sem o player, a faixa de baixo ocupa a altura toda; sem a de baixo, é o player que ocupa', () => {
    const noPlayer = workbenchGrid(layout, { ...all, 'top-center': false })
    expect(noPlayer.rows).toBe('0px 0px minmax(0, 1fr)')
    expect(noPlayer.showRowDivider).toBe(false)
    const onlyPlayer = workbenchGrid(layout, { 'top-center': true, 'top-left': false, bottom: false, 'top-right': false })
    expect(onlyPlayer.rows).toBe('minmax(0, 1fr) 0px 0px')
  })

  it('sem a linha do tempo, as colunas laterais dividem a largura e não há divisor entre elas', () => {
    const grid = workbenchGrid(layout, { ...all, bottom: false })
    expect(grid.columns).toBe('minmax(0, 1fr) 0px 0px 0px minmax(0, 1fr)')
    expect([grid.showLeftDivider, grid.showRightDivider]).toEqual([false, false])
  })

  it('a altura da faixa de cima vem da fração do layout', () => {
    expect(workbenchGrid(builtinLayouts().Player!, all).rows).toBe('72.0% 6px minmax(0, 1fr)')
  })
})
