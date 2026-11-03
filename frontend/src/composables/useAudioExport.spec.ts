import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useConfirmStore } from '@/stores/confirm'
import { useJobsStore } from '@/stores/jobs'
import { FakeEventSource } from '@/test/fetch'
import { reply, routedFetch } from '@/test/routedFetch'
import { useAudioExport } from './useAudioExport'

beforeEach(() => {
  setActivePinia(createPinia())
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
})
afterEach(() => vi.unstubAllGlobals())

describe('useAudioExport', () => {
  it('inicia o job e o acompanha quando nada existe ainda', async () => {
    routedFetch({ 'POST /api/projects/ep/audio-export': { job_id: 'job-9' } })
    const result = await useAudioExport().start('ep', { preset: 'audio/mp3', mode: 'mix' })
    expect(result).toBe(true)
    expect(useJobsStore().jobs).toHaveProperty('job-9')
  })

  it('um arquivo que já existe pede o sim da pessoa e só então manda de novo com overwrite', async () => {
    const bodies: unknown[] = []
    routedFetch({
      'POST /api/projects/ep/audio-export': (call: { body?: unknown }) => {
        bodies.push(call.body)
        const body = call.body as { overwrite?: boolean } | undefined
        return body?.overwrite
          ? { job_id: 'job-2' }
          : reply(409, { detail: { message: 'Já existe', existing: ['C:\\out\\ep.mp3'] } })
      },
    })
    const exporting = useAudioExport().start('ep', { preset: 'audio/mp3', mode: 'mix' })
    await flushPromises()
    const confirm = useConfirmStore()
    expect(confirm.current?.options.description).toBe('O arquivo ep.mp3 já existe. Quer substituí-lo?')
    confirm.answer(true)
    expect(await exporting).toBe(true)
    expect(bodies).toHaveLength(2)
    expect(bodies[1]).toMatchObject({ overwrite: true })
  })

  it('dizer não deixa tudo como estava: nenhum job e nenhum segundo pedido', async () => {
    const calls: unknown[] = []
    routedFetch({
      'POST /api/projects/ep/audio-export': (call: unknown) => {
        calls.push(call)
        return reply(409, { detail: { message: 'Já existe', existing: ['a.mp3', 'b.mp3'] } })
      },
    })
    const exporting = useAudioExport().start('ep', { preset: 'audio/mp3', mode: 'regions' })
    await flushPromises()
    useConfirmStore().answer(false)
    expect(await exporting).toBe(false)
    expect(calls).toHaveLength(1)
    expect(Object.keys(useJobsStore().jobs)).toHaveLength(0)
  })
})
