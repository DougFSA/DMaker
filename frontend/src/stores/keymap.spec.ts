import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { KEYMAP_STORAGE_KEY } from '@/lib/keymap'
import { useKeymapStore } from './keymap'

beforeEach(() => {
  window.localStorage.clear()
  setActivePinia(createPinia())
})

describe('a tabela em uso', () => {
  it('sem trocas salvas, é o padrão de 34 atalhos', () => {
    const keymap = useKeymapStore()
    expect(keymap.entries).toHaveLength(34)
    expect(keymap.customCount).toBe(0)
    expect(keymap.labelFor('split')).toBe('S')
    expect(keymap.labelFor('remove_ripple')).toBe('X ou Del')
    expect(keymap.byCombo.get('Ctrl+z')).toEqual(['undo'])
  })

  it('lê as trocas que a interface clássica já salvou, na mesma chave e no mesmo formato', () => {
    window.localStorage.setItem(KEYMAP_STORAGE_KEY, JSON.stringify({ split: ['b'], undo: ['Ctrl+u'] }))
    const keymap = useKeymapStore()
    expect(keymap.byCombo.get('b')).toEqual(['split'])
    expect(keymap.byCombo.get('s')).toBeUndefined()
    expect(keymap.customCount).toBe(2)
    expect(keymap.isDefault('split')).toBe(false)
    expect(keymap.isDefault('pause')).toBe(true)
  })

  it('texto quebrado no armazenamento vira o padrão', () => {
    window.localStorage.setItem(KEYMAP_STORAGE_KEY, '{{{')
    expect(useKeymapStore().customCount).toBe(0)
  })
})

describe('trocar uma tecla', () => {
  it('vale na hora e fica guardada no navegador', () => {
    const keymap = useKeymapStore()
    keymap.setBinding('split', 'b')
    expect(keymap.byCombo.get('b')).toEqual(['split'])
    expect(keymap.byCombo.get('s')).toBeUndefined()
    expect(JSON.parse(window.localStorage.getItem(KEYMAP_STORAGE_KEY) ?? '{}')).toEqual({ split: ['b'] })
  })

  it('o conflito é avisado, não bloqueado: as duas ações passam a usar a tecla', () => {
    const keymap = useKeymapStore()
    expect(keymap.conflictFor('k', 'split')?.id).toBe('pause')
    keymap.setBinding('split', 'k')
    expect(keymap.byCombo.get('k')).toEqual(['pause', 'split'])
  })

  it('restaurar os padrões apaga as trocas e o que estava guardado', () => {
    const keymap = useKeymapStore()
    keymap.setBinding('split', 'b')
    keymap.reset()
    expect(keymap.customCount).toBe(0)
    expect(keymap.byCombo.get('s')).toEqual(['split'])
    expect(window.localStorage.getItem(KEYMAP_STORAGE_KEY)).toBeNull()
  })

  it('sem acesso ao armazenamento a troca ainda vale até recarregar', () => {
    const keymap = useKeymapStore()
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('bloqueado')
    })
    keymap.setBinding('split', 'b')
    expect(keymap.byCombo.get('b')).toEqual(['split'])
    vi.restoreAllMocks()
  })
})

describe('comandos registrados por fora', () => {
  it('o painel Mídia registra o A e o V e desregistra ao sair', () => {
    const keymap = useKeymapStore()
    const handler = vi.fn()
    const stop = keymap.register('media_append', handler)
    expect(keymap.registered.get('media_append')).toBe(handler)
    stop()
    expect(keymap.registered.has('media_append')).toBe(false)
  })

  it('quem foi trocado por outro registro não derruba o novo ao desregistrar', () => {
    const keymap = useKeymapStore()
    const first = vi.fn()
    const second = vi.fn()
    const stopFirst = keymap.register('media_insert', first)
    keymap.register('media_insert', second)
    stopFirst()
    expect(keymap.registered.get('media_insert')).toBe(second)
  })
})

describe('a janela de atalhos', () => {
  it('abre pelo store, para o botão ? e a tecla ? usarem o mesmo caminho', () => {
    const keymap = useKeymapStore()
    expect(keymap.dialogOpen).toBe(false)
    keymap.openDialog()
    expect(keymap.dialogOpen).toBe(true)
  })
})
