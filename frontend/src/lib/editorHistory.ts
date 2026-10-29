/* Pilha de desfazer e refazer da spec: cada passo é uma fotografia (o JSON da spec inteira) de antes da mudança.
   Função pura sobre texto, sem Vue; quem decide o que vale um passo é o store do editor. */

/** Quantas fotografias a pilha guarda; passou disso, a mais antiga sai. */
export const HISTORY_LIMIT = 100

export class SnapshotHistory {
  private past: string[] = []
  private future: string[] = []

  constructor(private readonly limit: number = HISTORY_LIMIT) {}

  get canUndo(): boolean {
    return this.past.length > 0
  }

  get canRedo(): boolean {
    return this.future.length > 0
  }

  get undoCount(): number {
    return this.past.length
  }

  get redoCount(): number {
    return this.future.length
  }

  /** Guarda o estado de ANTES de uma mudança. Mudança nova apaga o que havia para refazer. */
  record(before: string): void {
    this.past.push(before)
    if (this.past.length > this.limit) this.past.shift()
    this.future = []
  }

  /** Volta um passo: devolve a fotografia a restaurar e guarda `current` para refazer. Sem passo, devolve null. */
  undo(current: string): string | null {
    const snapshot = this.past.pop()
    if (snapshot === undefined) return null
    this.future.push(current)
    return snapshot
  }

  /** Refaz um passo desfeito: devolve a fotografia a restaurar e guarda `current` para desfazer de novo. */
  redo(current: string): string | null {
    const snapshot = this.future.pop()
    if (snapshot === undefined) return null
    this.past.push(current)
    return snapshot
  }

  clear(): void {
    this.past = []
    this.future = []
  }
}
