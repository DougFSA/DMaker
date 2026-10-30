import type { IconName } from '@/components/ui/AppIcon.vue'

export interface NavItem {
  key: string
  label: string
  to: string
  icon: IconName
}

/** Ordem da barra lateral. */
export const NAV_ITEMS: NavItem[] = [
  { key: 'projects', label: 'Projetos', to: '/projetos', icon: 'folder' },
  { key: 'batch', label: 'Lote', to: '/lote', icon: 'copy' },
  { key: 'editor', label: 'Editor', to: '/editor', icon: 'film' },
  { key: 'voice', label: 'Voz', to: '/voz', icon: 'mic' },
  { key: 'dubbing', label: 'Dublagem', to: '/dublagem', icon: 'languages' },
  { key: 'queue', label: 'Fila', to: '/fila', icon: 'queue' },
  { key: 'models', label: 'Modelos', to: '/modelos', icon: 'layers' },
  { key: 'outputs', label: 'Saídas', to: '/saidas', icon: 'video' },
  { key: 'transitions', label: 'Transições', to: '/transicoes', icon: 'sparkles' },
  { key: 'looks', label: 'Looks', to: '/looks', icon: 'grid' },
  { key: 'infographics', label: 'Infográficos', to: '/infograficos', icon: 'layers' },
  { key: 'agent', label: 'Agente', to: '/agente', icon: 'sparkles' },
]

/** Onde a interface clássica continua disponível: só o link do rodapé da barra lateral leva até ela. */
export const CLASSIC_UI_PATH = '/classica'
