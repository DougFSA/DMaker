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
async function finishJob(
  status: string,
  error: string | null = null,
  result: unknown = null,
  description = 'Narração: roteiro curto',
): Promise<void> {
  useJobsStore().track('j1', { description })
  FakeEventSource.latest().emit({ kind: 'end', t: 9, status, error, result })
  await flushPromises()
}

const lastToast = () => useToastsStore().items.at(-1)

describe('avisos de fim de job', () => {
  it('um render concluído avisa com o botão para as saídas', async () => {
    const result = { output: 'output/a.mp4', preset: 'instagram/reels' }
    await finishJob('done', null, result, 'meu: render final')
    expect(lastToast()).toMatchObject({ tone: 'success', title: 'Concluído', description: 'meu: render final' })
    expect(lastToast()?.action?.label).toBe('Ver saídas')
    lastToast()?.action?.run()
    expect(router.push).toHaveBeenLastCalledWith({ name: 'outputs' })
  })

  it('um job de áudio concluído não oferece as saídas: leva à tela que o disparou', async () => {
    await finishJob('done', null, { ready: 3, total: 3 }, 'narração (Ana, 40 caracteres)')
    expect(lastToast()).toMatchObject({ tone: 'success', title: 'Concluído' })
    expect(lastToast()?.action?.label).toBe('Abrir Narração')
    lastToast()?.action?.run()
    expect(router.push).toHaveBeenLastCalledWith({ name: 'voice-narration' })
  })

  it('o download de modelo não ganha um segundo aviso: a tela de Modelos já diz "Modelo baixado"', async () => {
    await finishJob('done', null, { id: 'whisper' }, 'baixar modelo (Whisper)')
    expect(useToastsStore().items).toHaveLength(0)
  })

  it('o download de modelo que falha ainda avisa', async () => {
    await finishJob('error', 'sem rede', null, 'baixar modelo (Whisper)')
    expect(lastToast()).toMatchObject({ tone: 'error', title: 'O job falhou' })
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
