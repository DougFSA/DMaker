import { describe, expect, it } from 'vitest'
import { HISTORY_LIMIT, SnapshotHistory } from './editorHistory'

describe('SnapshotHistory', () => {
  it('começa vazia e sem nada para desfazer ou refazer', () => {
    const history = new SnapshotHistory()
    expect(history.canUndo).toBe(false)
    expect(history.canRedo).toBe(false)
    expect(history.undo('atual')).toBeNull()
    expect(history.redo('atual')).toBeNull()
  })

  it('desfaz e refaz na ordem inversa das mudanças', () => {
    const history = new SnapshotHistory()
    history.record('A') // A -> B
    history.record('B') // B -> C
    expect(history.undo('C')).toBe('B')
    expect(history.undo('B')).toBe('A')
    expect(history.undo('A')).toBeNull()
    expect(history.redo('A')).toBe('B')
    expect(history.redo('B')).toBe('C')
    expect(history.redo('C')).toBeNull()
  })

  it('uma mudança nova depois de desfazer apaga o que havia para refazer', () => {
    const history = new SnapshotHistory()
    history.record('A')
    history.undo('B')
    expect(history.canRedo).toBe(true)
    history.record('A')
    expect(history.canRedo).toBe(false)
  })

  it('guarda 100 fotografias e descarta a mais antiga', () => {
    expect(HISTORY_LIMIT).toBe(100)
    const history = new SnapshotHistory()
    for (let i = 0; i < 130; i += 1) history.record(`s${i}`)
    expect(history.undoCount).toBe(100)
    let last: string | null = null
    let current = 's130'
    for (let guard = 0; guard < 200; guard += 1) {
      const step = history.undo(current)
      if (step === null) break
      last = step
      current = step
    }
    expect(last).toBe('s30') // as 30 mais antigas saíram
  })

  it('limpa os dois lados', () => {
    const history = new SnapshotHistory()
    history.record('A')
    history.undo('B')
    history.clear()
    expect(history.canUndo).toBe(false)
    expect(history.canRedo).toBe(false)
  })
})
