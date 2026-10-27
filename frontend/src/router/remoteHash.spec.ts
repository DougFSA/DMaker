import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import { useJobsStore } from '@/stores/jobs'
import { createAppRouter } from './index'
import { followRemoteRender, parseRemoteHash } from './remoteHash'

describe('hash de render remoto', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('EventSource', class { close() {} } as unknown as typeof EventSource)
  })

  it('lê projeto e job do hash', () => {
    expect(parseRemoteHash('#project=meu%20video&job=abc')).toEqual({ project: 'meu video', job: 'abc' })
    expect(parseRemoteHash('#project=a')).toEqual({ project: 'a', job: null })
    expect(parseRemoteHash('')).toBeNull()
    expect(parseRemoteHash('#outra=coisa')).toBeNull()
  })

  it('abre o projeto e passa a acompanhar o job', async () => {
    const router = createAppRouter(createMemoryHistory())
    const followed = await followRemoteRender(router, '#project=demo&job=j9')
    expect(followed).toBe(true)
    expect(router.currentRoute.value.name).toBe('project')
    expect(router.currentRoute.value.params.name).toBe('demo')
    expect(useJobsStore().jobs['j9']).toMatchObject({ project: 'demo', status: 'running' })
  })

  it('não faz nada sem hash de render', async () => {
    const router = createAppRouter(createMemoryHistory())
    expect(await followRemoteRender(router, '')).toBe(false)
  })
})

describe('rotas', () => {
  it('redireciona a raiz para Projetos e cria as telas das próximas fases', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/')
    expect(router.currentRoute.value.name).toBe('projects')
    await router.push('/voz')
    expect(router.currentRoute.value.name).toBe('soon-voice')
    await router.push('/inexistente')
    expect(router.currentRoute.value.name).toBe('not-found')
  })
})
