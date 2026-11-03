import { afterEach, describe, expect, it } from 'vitest'
import {
  comboFromEvent,
  comboIndex,
  comboLabel,
  findConflict,
  isModifierKey,
  isTypingTarget,
  keyBelongsToTarget,
  keyLabel,
  mergeKeymap,
  parseOverrides,
  SHORTCUT_CATEGORIES,
  SHORTCUT_DEFAULTS,
  withBinding,
} from './keymap'

type KeyInit = Partial<Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'metaKey' | 'altKey' | 'shiftKey'>> & { key: string }

const press = (init: KeyInit) => comboFromEvent({ ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...init })

describe('a tabela padrão', () => {
  it('tem os 34 atalhos, cada um com id único e ao menos uma tecla', () => {
    expect(SHORTCUT_DEFAULTS).toHaveLength(34)
    expect(new Set(SHORTCUT_DEFAULTS.map((entry) => entry.id)).size).toBe(34)
    for (const entry of SHORTCUT_DEFAULTS) expect(entry.keys.length, entry.id).toBeGreaterThan(0)
  })

  it('cai em seis categorias, todas com atalhos', () => {
    expect(SHORTCUT_CATEGORIES.map((category) => category.id)).toEqual(['reproducao', 'navegacao', 'edicao', 'midia', 'visualizacao', 'geral'])
    for (const category of SHORTCUT_CATEGORIES) {
      expect(SHORTCUT_DEFAULTS.some((entry) => entry.category === category.id), category.id).toBe(true)
    }
  })

  it('o padrão não tem duas ações na mesma tecla', () => {
    const seen = new Map<string, string>()
    for (const entry of SHORTCUT_DEFAULTS) {
      for (const combo of entry.keys) {
        expect(seen.get(combo), `${combo} em ${entry.id}`).toBeUndefined()
        seen.set(combo, entry.id)
      }
    }
  })

  it('as combinações estão na forma canônica que o teclado produz', () => {
    for (const entry of SHORTCUT_DEFAULTS) {
      for (const combo of entry.keys) {
        // Ctrl, Alt e Shift nesta ordem, e a tecla por último
        expect(combo, `${entry.id}: ${combo}`).toMatch(/^(Ctrl\+)?(Alt\+)?(Shift\+)?[^+]+$/)
      }
    }
  })

  it('os rótulos e as categorias não usam travessão (regra da marca)', () => {
    for (const entry of SHORTCUT_DEFAULTS) expect(entry.label).not.toMatch(/[—–]/)
    for (const category of SHORTCUT_CATEGORIES) expect(category.label).not.toMatch(/[—–]/)
  })
})

describe('comboFromEvent', () => {
  it('letra sem modificador vira minúscula; o espaço vira "Space"', () => {
    expect(press({ key: 'S' })).toBe('s')
    expect(press({ key: ' ' })).toBe('Space')
    expect(press({ key: 'ArrowLeft' })).toBe('ArrowLeft')
  })

  it('os modificadores entram na ordem Ctrl, Alt, Shift', () => {
    expect(press({ key: 'z', ctrlKey: true })).toBe('Ctrl+z')
    expect(press({ key: 'Z', ctrlKey: true, shiftKey: true })).toBe('Ctrl+Shift+z')
    expect(press({ key: 'ArrowRight', altKey: true })).toBe('Alt+ArrowRight')
    expect(press({ key: 'a', ctrlKey: true, altKey: true, shiftKey: true })).toBe('Ctrl+Alt+Shift+a')
  })

  it('o Cmd do Mac vale como Ctrl', () => {
    expect(press({ key: 's', metaKey: true })).toBe('Ctrl+s')
  })

  it('o Shift de um caractere como "?" não conta: ele já está no caractere, e senão o "?" nunca casaria', () => {
    expect(press({ key: '?', shiftKey: true })).toBe('?')
    expect(press({ key: '+', shiftKey: true })).toBe('+')
    // numa tecla de nome o Shift conta
    expect(press({ key: 'Home', shiftKey: true })).toBe('Shift+Home')
  })

  it('o ponto de partida de cada atalho padrão é alcançável por um evento', () => {
    expect(press({ key: 'Delete' })).toBe('Delete')
    expect(press({ key: '=' })).toBe('=')
    expect(press({ key: 'Escape' })).toBe('Escape')
  })
})

describe('trocas da pessoa', () => {
  it('a tabela em uso é o padrão com a troca por cima', () => {
    const merged = mergeKeymap({ split: ['b'] })
    expect(merged.find((entry) => entry.id === 'split')?.keys).toEqual(['b'])
    expect(merged.find((entry) => entry.id === 'pause')?.keys).toEqual(['k'])
    expect(merged).toHaveLength(34)
  })

  it('uma troca vazia ou de outro tipo é ignorada', () => {
    const merged = mergeKeymap({ split: [] })
    expect(merged.find((entry) => entry.id === 'split')?.keys).toEqual(['s'])
  })

  it('lê o texto salvo: o que não é objeto, ação desconhecida ou combinação inválida some', () => {
    expect(parseOverrides(null)).toEqual({})
    expect(parseOverrides('não é json')).toEqual({})
    expect(parseOverrides('[1,2]')).toEqual({})
    expect(parseOverrides('{"split":["b"],"inexistente":["x"],"pause":"k","lift":[1,""]}')).toEqual({ split: ['b'] })
  })

  it('trocar a principal mantém as alternativas; devolve cópia e não mexe na original', () => {
    const entries = mergeKeymap({})
    const original = {}
    const changed = withBinding(original, entries, 'remove_ripple', 0, 'q')
    expect(changed).toEqual({ remove_ripple: ['q', 'Delete'] })
    expect(original).toEqual({})
    const again = withBinding(changed, mergeKeymap(changed), 'remove_ripple', 1, 'w')
    expect(again).toEqual({ remove_ripple: ['q', 'w'] })
  })

  it('trocar um atalho que não existe não faz nada', () => {
    expect(withBinding({}, mergeKeymap({}), 'nao_existe' as never, 0, 'q')).toEqual({})
  })
})

describe('índice e conflitos', () => {
  it('cada combinação aponta para as ações que a usam', () => {
    const index = comboIndex(mergeKeymap({ pause: ['s'] }))
    expect(index.get('s')).toEqual(['pause', 'split'])
    expect(index.get('Space')).toEqual(['play_pause'])
    expect(index.get('x')).toEqual(['remove_ripple'])
    expect(index.get('Delete')).toEqual(['remove_ripple'])
  })

  it('o conflito é outra ação na mesma tecla; a própria não conta', () => {
    const entries = mergeKeymap({})
    expect(findConflict(entries, 's', 'pause')?.id).toBe('split')
    expect(findConflict(entries, 's', 'split')).toBeNull()
    expect(findConflict(entries, 'F9', 'split')).toBeNull()
  })
})

describe('rótulos de tecla', () => {
  it('letras em maiúscula, teclas de nome em português, partes separadas', () => {
    expect(comboLabel('Ctrl+Shift+z')).toBe('Ctrl + Shift + Z')
    expect(comboLabel('Space')).toBe('Espaço')
    expect(comboLabel('Alt+ArrowLeft')).toBe('Alt + ←')
    expect(comboLabel('Delete')).toBe('Del')
    expect(comboLabel('PageDown')).toBe('Page Down')
    expect(keyLabel(['x', 'Delete'])).toBe('X ou Del')
    expect(keyLabel([])).toBe('')
  })

  it('só Ctrl, Alt, Shift e Meta são modificadores sozinhos', () => {
    for (const key of ['Control', 'Alt', 'Shift', 'Meta']) expect(isModifierKey(key), key).toBe(true)
    expect(isModifierKey('s')).toBe(false)
  })
})

describe('quando o teclado fica quieto', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  function element(tag: string, attributes: Record<string, string> = {}, parent?: HTMLElement): HTMLElement {
    const node = document.createElement(tag)
    for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value)
    ;(parent ?? document.body).appendChild(node)
    return node
  }

  it('campos de texto seguram as teclas', () => {
    expect(isTypingTarget(element('input'))).toBe(true)
    expect(isTypingTarget(element('textarea'))).toBe(true)
    expect(isTypingTarget(element('select'))).toBe(true)
    expect(isTypingTarget(element('div'))).toBe(false)
    expect(isTypingTarget(window)).toBe(false)
    expect(keyBelongsToTarget(element('input'), 's')).toBe(true)
  })

  it('o Ctrl+S ainda vale com o foco num campo (a ação diz que vale digitando)', () => {
    expect(keyBelongsToTarget(element('textarea'), 'Ctrl+s', true)).toBe(false)
  })

  it('diálogos, menus, listas e controles deslizantes ficam com o teclado, até para o Ctrl+S', () => {
    const dialog = element('div', { role: 'dialog' })
    expect(keyBelongsToTarget(element('button', {}, dialog), 's')).toBe(true)
    expect(keyBelongsToTarget(element('input', {}, dialog), 'Ctrl+s', true)).toBe(true)
    expect(keyBelongsToTarget(element('span', { role: 'slider' }), 'ArrowLeft')).toBe(true)
    expect(keyBelongsToTarget(element('div', { role: 'tablist' }), 'ArrowRight')).toBe(true)
  })

  it('o Espaço num botão aperta o botão; as outras teclas seguem para o editor', () => {
    const button = element('button')
    expect(keyBelongsToTarget(button, 'Space')).toBe(true)
    expect(keyBelongsToTarget(button, 's')).toBe(false)
    expect(keyBelongsToTarget(element('div', { role: 'tab' }), 'Space')).toBe(true)
  })

  it('o corpo da página e a janela deixam o editor agir', () => {
    expect(keyBelongsToTarget(document.body, 'Space')).toBe(false)
    expect(keyBelongsToTarget(window, 'Space')).toBe(false)
  })
})
