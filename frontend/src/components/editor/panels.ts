/* O registro dos painéis do editor. A tela do editor não conhece nenhum painel pelo nome: ela percorre esta lista
   e põe cada um no encaixe dele. Painel que ainda não existe tem `load: null` e o encaixe mostra um aviso discreto.

   Para plugar um painel novo, crie o componente em `components/editor/` e troque o `load: null` da linha dele por
   `() => import('./NomeDoPainel.vue')`. O componente não recebe props: lê e muda tudo pelo store do editor
   (`useEditorStore`). Hoje os oito painéis existem; o `load: null` fica para um painel futuro. */
import { defineAsyncComponent, type Component } from 'vue'
import type { useEditorStore } from '@/stores/editor'

export type EditorPanelId = 'properties' | 'json' | 'captions' | 'preview' | 'player' | 'timeline' | 'filters' | 'media'

/**
 * Onde o painel mora: nos encaixes da bancada (player, linha do tempo, filtros e mídia, no alto da tela) ou nas
 * abas do inspetor (propriedades, JSON, legendas e preview, embaixo).
 */
export type EditorZone = 'workbench' | 'inspector'

export interface EditorPanelDef {
  id: EditorPanelId
  title: string
  zone: EditorZone
  /** Carrega o componente do painel; `null` enquanto ele não existe. */
  load: (() => Promise<{ default: Component }>) | null
  /** Painel que só aparece em certas condições (a aba Legendas só com legendas automáticas). */
  when?: (editor: ReturnType<typeof useEditorStore>) => boolean
}

export const EDITOR_PANELS: EditorPanelDef[] = [
  // bancada
  { id: 'media', title: 'Mídia', zone: 'workbench', load: () => import('./MediaPanel.vue') },
  { id: 'player', title: 'Player', zone: 'workbench', load: () => import('./PlayerPanel.vue') },
  { id: 'filters', title: 'Filtros', zone: 'workbench', load: () => import('./FiltersPanel.vue') },
  { id: 'timeline', title: 'Linha do tempo', zone: 'workbench', load: () => import('./TimelinePanel.vue') },
  // inspetor
  { id: 'properties', title: 'Propriedades', zone: 'inspector', load: () => import('./PropertiesPanel.vue') },
  { id: 'json', title: 'JSON', zone: 'inspector', load: () => import('./JsonPanel.vue') },
  {
    id: 'captions',
    title: 'Legendas',
    zone: 'inspector',
    load: () => import('./CaptionsPanel.vue'),
    when: (editor) => editor.captionsExists,
  },
  { id: 'preview', title: 'Preview', zone: 'inspector', load: () => import('./PreviewPanel.vue') },
]

export function panelsIn(zone: EditorZone): EditorPanelDef[] {
  return EDITOR_PANELS.filter((panel) => panel.zone === zone)
}

const resolved = new Map<EditorPanelId, Component>()

/** O componente do painel (carregado sob demanda e guardado), ou null se ele ainda não existe. */
export function componentOf(panel: EditorPanelDef): Component | null {
  if (!panel.load) return null
  let component = resolved.get(panel.id)
  if (!component) {
    component = defineAsyncComponent(panel.load)
    resolved.set(panel.id, component)
  }
  return component
}
