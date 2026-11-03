/* Apoio dos testes de tela estreita: o jsdom não tem `matchMedia`, então este falso responde a uma consulta só e
   avisa os ouvintes quando o teste troca o resultado, como o navegador faz ao redimensionar a janela. */
import { vi } from 'vitest'

export interface FakeMediaQuery {
  /** Troca o resultado da consulta e avisa quem está ouvindo. */
  set(matches: boolean): void
  /** Quantos ouvintes de `change` estão registrados agora. */
  listenerCount(): number
}

export function installFakeMatchMedia(initial: boolean): FakeMediaQuery {
  let matches = initial
  const listeners = new Set<(event: MediaQueryListEvent) => void>()

  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      media: query,
      get matches() {
        return matches
      },
      addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => listeners.add(listener),
      removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) =>
        listeners.delete(listener),
    })),
  )

  return {
    set(next) {
      matches = next
      for (const listener of [...listeners]) listener({ matches: next } as MediaQueryListEvent)
    },
    listenerCount: () => listeners.size,
  }
}
