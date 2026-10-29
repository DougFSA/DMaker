import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, type EffectScope } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { useJobsStore } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'
import { FakeEventSource, stubFetch } from '@/test/fetch'
import { useJobNotifications } from './useJobNotifications'

let scope: EffectScope

beforeEach(() => {
  setActivePinia(createPinia())
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
  stubFetch({})
  scope = effectScope()
  scope.run(() => useJobNotifications(createRouter({ history: createMemoryHistory(), routes: [] })))
})
afterEach(() => {
  scope.stop()
  vi.unstubAllGlobals()
})

/** Faz o job `j1` terminar do jeito pedido, como o SSE do servidor faria. */
function endJob(status: 'done' | 'error' | 'cancelled', error: string | null = null): void {
  useJobsStore().track('j1', { description: 'dublagem: gerar (entrevista.en.dub.json)' })
  FakeEventSource.latest().emit({ kind: 'end', t: 1, status, error, result: null })
}

describe('useJobNotifications', () => {
  it('job concluído avisa com o caminho para as saídas', () => {
    endJob('done')
    expect(useToastsStore().items[0]).toMatchObject({ tone: 'success', title: 'Concluído' })
  })

  it('job que falhou mostra a primeira linha do erro', () => {
    endJob('error', 'RuntimeError: sem espaço\ntraceback')
    expect(useToastsStore().items[0]).toMatchObject({ tone: 'error', title: 'O job falhou' })
    expect(useToastsStore().items[0]!.description).toContain('RuntimeError: sem espaço')
  })

  it('job parado a pedido não é falha: avisa que parou', () => {
    endJob('cancelled')
    const toast = useToastsStore().items[0]!
    expect(toast).toMatchObject({ tone: 'info', title: 'Parado a pedido', description: 'dublagem: gerar (entrevista.en.dub.json)' })
    expect(useToastsStore().items.map((item) => item.title)).not.toContain('O job falhou')
  })
})
