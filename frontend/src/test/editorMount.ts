/* Apoio dos testes dos painéis do editor: abre um projeto de mentira no store e monta o componente por cima dele. */
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import type { Component } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { useEditorStore } from '@/stores/editor'
import { editorSchema, projectDetail, projectSpec, timelineView } from './editorFixtures'
import { routedFetch, type RoutedFetch } from './routedFetch'

type Spec = Record<string, unknown>

export interface OpenedEditor {
  pinia: Pinia
  fetch: RoutedFetch
  store: ReturnType<typeof useEditorStore>
}

/** As rotas que a abertura do editor chama; `extra` acrescenta ou troca rotas do teste. */
export function editorRoutes(spec: Spec, extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    'GET /api/projects/demo': () => projectDetail({ spec: spec as never }),
    'GET /api/schema': editorSchema,
    'GET /api/transitions': {
      curves: ['linear'],
      transitions: ['fade', 'dissolve', 'wipeleft'].map((name) => ({ name, kind: 'xfade', summary: '' })),
    },
    'GET /api/state': {
      presets: [
        { id: 'instagram/reels', platform: 'Instagram', name: 'Reels', width: 1080, height: 1920, fps: 30 },
        { id: 'youtube/video', platform: 'YouTube', name: 'Vídeo', width: 1920, height: 1080, fps: 30 },
      ],
      brands: [{ key: 'medlycare', name: 'MedlyCare', colors: {} }],
    },
    'GET /api/templates': [],
    'POST /api/projects/demo/timeline': () => timelineView(),
    'PUT /api/projects/demo': { ok: true, spec_path: 'x' },
    ...extra,
  }
}

/** Abre o projeto "demo" no store, com a spec dada (a de `projectSpec()` por padrão). */
export async function openEditor(spec: Spec = projectSpec(), extra: Record<string, unknown> = {}): Promise<OpenedEditor> {
  const pinia = createPinia()
  setActivePinia(pinia)
  const fetch = routedFetch(editorRoutes(spec, extra))
  const store = useEditorStore()
  await store.open('demo')
  await flushPromises()
  return { pinia, fetch, store }
}

const Blank = { render: () => null }

/** Um router só com os nomes de rota que os links do editor usam, sem carregar nenhuma tela. */
function lightRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/editor/:name?', name: 'editor', component: Blank },
      { path: '/projetos', name: 'projects', component: Blank },
      { path: '/projetos/:name', name: 'project', component: Blank },
    ],
  })
}

/**
 * Monta um componente do editor sobre o store já aberto. `attach` põe o componente no documento, o que os diálogos
 * precisam (eles abrem fora do componente); quem usa isso desmonta o wrapper no fim do teste.
 */
export async function mountEditorPart(
  component: Component,
  opened: OpenedEditor,
  props: Spec = {},
  attach = false,
): Promise<VueWrapper> {
  const router = lightRouter()
  await router.push('/editor/demo')
  await router.isReady()
  const wrapper = mount(component, {
    props,
    global: { plugins: [opened.pinia, router] },
    ...(attach ? { attachTo: document.body } : {}),
  })
  await flushPromises()
  return wrapper
}
