import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, type EffectScope } from 'vue'
import type { Router } from 'vue-router'
import { FakeEventSource } from '@/test/fetch'
import { useJobsStore } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'
import { useJobNotifications } from './useJobNotifications'

let scope: EffectScope
const router = { push: vi.fn() } as unknown as Router

beforeEach(() => {
  setActivePinia(createPinia())
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
  scope = effectScope()
  scope.run(() => useJobNotifications(router))
})
afterEach(() => {
  scope.stop()
  vi.unstubAllGlobals()
})

/** Um job que a interface viu rodando e que termina como o servidor disser. */
async function finishJob(status: string, error: string | null = null, result: unknown = null): Promise<void> {
  useJobsStore().track('j1', { description: 'Narração: roteiro curto' })
  FakeEventSource.latest().emit({ kind: 'end', t: 9, status, error, result })
  await flushPromises()
}

const lastToast = () => useToastsStore().items.at(-1)

describe('avisos de fim de job', () => {
  it('um job concluído avisa com o botão para as saídas', async () => {
    await finishJob('done')
    expect(lastToast()).toMatchObject({ tone: 'success', title: 'Concluído', description: 'Narração: roteiro curto' })
    expect(lastToast()?.action?.label).toBe('Ver saídas')
  })

  it('um job parado a pedido avisa "Parado" em tom neutro, e não como falha', async () => {
    await finishJob('cancelled', null, { ready: 2, total: 5 })
    expect(lastToast()).toMatchObject({ tone: 'info', title: 'Parado', description: 'Narração: roteiro curto' })
    expect(useToastsStore().items.map((toast) => toast.title)).not.toContain('O job falhou')
  })

  it('um job que falhou avisa com a primeira linha do erro', async () => {
    await finishJob('error', 'RuntimeError: sem modelo\nTraceback (most recent call last)')
    expect(lastToast()).toMatchObject({ tone: 'error', title: 'O job falhou' })
    expect(lastToast()?.description).toContain('RuntimeError: sem modelo')
    expect(lastToast()?.description).not.toContain('Traceback')
  })
})
