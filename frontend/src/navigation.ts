import type { IconName } from '@/components/ui/AppIcon.vue'

export interface NavItem {
  key: string
  label: string
  to: string
  icon: IconName
  /**
   * false = a área ainda não está completa: o item aparece com o selo "em breve" e a rota mostra a view
   * "em construção". Quando uma frente do DMK-38 termina a sua área, ela troca só este valor para true
   * (e a view da rota pelo conteúdo de verdade).
   */
  ready: boolean
}

/** Ordem da barra lateral. Cada área tem o seu bloco, para trocar `ready` não encostar nas vizinhas. */
export const NAV_ITEMS: NavItem[] = [
  { key: 'projects', label: 'Projetos', to: '/projetos', icon: 'folder', ready: true },
  { key: 'batch', label: 'Lote', to: '/lote', icon: 'copy', ready: true },
  {
    key: 'editor',
    label: 'Editor',
    to: '/editor',
    icon: 'film',
    ready: true,
  },
  {
    key: 'voice',
    label: 'Voz',
    to: '/voz',
    icon: 'mic',
    ready: true,
  },
  {
    key: 'dubbing',
    label: 'Dublagem',
    to: '/dublagem',
    icon: 'languages',
    ready: true,
  },
  {
    key: 'queue',
    label: 'Fila',
    to: '/fila',
    icon: 'queue',
    ready: true,
  },
  {
    key: 'models',
    label: 'Modelos',
    to: '/modelos',
    icon: 'layers',
    ready: true,
  },
  { key: 'outputs', label: 'Saídas', to: '/saidas', icon: 'video', ready: true },
  { key: 'transitions', label: 'Transições', to: '/transicoes', icon: 'sparkles', ready: true },
  { key: 'looks', label: 'Looks', to: '/looks', icon: 'grid', ready: true },
  { key: 'infographics', label: 'Infográficos', to: '/infograficos', icon: 'layers', ready: true },
  { key: 'agent', label: 'Agente', to: '/agente', icon: 'sparkles', ready: true },
]

/** Onde a interface anterior continua disponível enquanto a nova não cobre tudo. */
export const CLASSIC_UI_PATH = '/classica'
