import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, type EffectScope } from 'vue'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { useEditorStore } from '@/stores/editor'
import { useJobsStore } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'
import { useWorkspaceStore } from '@/stores/workspace'
import { FakeEventSource } from '@/test/fetch'
import { focusTarget, useRemoteFocus } from './useRemoteFocus'

describe('focusTarget', () => {
  it('quem já está no projeto, na tela dele ou no editor, fica onde está', () => {
    expect(focusTarget({ name: 'project', params: { name: 'a' } }, 'a')).toBeNull()
    expect(focusTarget({ name: 'editor', params: { name: 'a' } }, 'a')).toBeNull()
  })

  it('de outra tela vai para a tela do projeto', () => {
    expect(focusTarget({ name: 'outputs', params: {} }, 'a')).toEqual({ name: 'project', params: { name: 'a' } })
    expect(focusTarget({ name: 'project', params: { name: 'b' } }, 'a')).toEqual({ name: 'project', params: { name: 'a' } })
  })

  it('do editor de outro projeto vai para o editor do novo', () => {
    expect(focusTarget({ name: 'editor', params: { name: 'b' } }, 'a')).toEqual({ name: 'editor', params: { name: 'a' } })
  })
})

function serverJobs(list: Array<Record<string, unknown>>): void {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(list)))),
  )
}

const remote = {
  job_id: 'cli1',
  description: 'demo: preview',
  status: 'running',
  elapsed_s: 0,
  progress: {},
  error: null,
  cancellable: false,
  focus: true,
  project: 'demo',
}

let scope: EffectScope
let router: Router

beforeEach(async () => {
  setActivePinia(createPinia())
  FakeEventSource.reset()
  vi.stubGlobal('EventSource', FakeEventSource)
  localStorage.clear()
  const blank = { render: () => null }
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/saidas', name: 'outputs', component: blank },
      { path: '/projetos/:name', name: 'project', component: blank },
      { path: '/editor/:name?', name: 'editor', component: blank },
    ],
  })
  await router.push('/saidas')
  scope = effectScope()
  scope.run(() => useRemoteFocus(router))
})
afterEach(() => {
  scope.stop()
  vi.unstubAllGlobals()
})

/** A interface abre sem nada, e o render da linha de comando aparece na consulta seguinte. */
async function remoteJobAppears(): Promise<void> {
  const jobs = useJobsStore()
  serverJobs([])
  await jobs.refresh()
  serverJobs([remote])
  await jobs.refresh()
  await flushPromises()
}

describe('useRemoteFocus', () => {
  it('abre sozinha a tela do projeto do job da linha de comando', async () => {
    await remoteJobAppears()
    expect(router.currentRoute.value.name).toBe('project')
    expect(router.currentRoute.value.params.name).toBe('demo')
    expect(useWorkspaceStore().currentProject).toBe('demo')
    expect(useJobsStore().jobs['cli1']).toBeDefined()
  })

  it('com mudança não salva no editor, não troca a tela e avisa com o botão para ir', async () => {
    const editor = useEditorStore()
    Object.defineProperty(editor, 'dirty', { value: true })
    await remoteJobAppears()
    expect(router.currentRoute.value.name).toBe('outputs')
    const toast = useToastsStore().items.at(-1)
    expect(toast?.title).toBe('Um job novo começou')
    toast?.action?.run()
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('project')
  })
})
