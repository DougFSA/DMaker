import type { IconName } from '@/components/ui/AppIcon.vue'

export interface NavItem {
  key: string
  label: string
  to: string
  icon: IconName
  /** false = tela de uma fase futura: o item aparece com o selo "em breve" e leva à interface clássica. */
  ready: boolean
  /** Frase da página "em breve", dizendo o que a tela vai trazer. */
  promise?: string
}

/** Ordem da barra lateral. Cada fase seguinte troca `ready` e a rota, sem mexer no resto do layout. */
export const NAV_ITEMS: NavItem[] = [
  { key: 'projects', label: 'Projetos', to: '/projetos', icon: 'folder', ready: true },
  {
    key: 'editor',
    label: 'Editor',
    to: '/editor',
    icon: 'film',
    ready: false,
    promise: 'Player, linha do tempo com trilhas, arrastar e aparar trechos e layouts de tela.',
  },
  {
    key: 'voice',
    label: 'Voz',
    to: '/voz',
    icon: 'mic',
    ready: false,
    promise: 'Estúdio de voz: vozes, nova voz por arquivo ou microfone, narração com prévia e pronúncia.',
  },
  {
    key: 'dubbing',
    label: 'Dublagem',
    to: '/dublagem',
    icon: 'languages',
    ready: false,
    promise: 'Isolar a voz, corrigir a fala, trocar a voz e dublar com tabela de segmentos e falantes.',
  },
  {
    key: 'queue',
    label: 'Fila',
    to: '/fila',
    icon: 'queue',
    ready: false,
    promise: 'A fila de narrações e trabalhos de voz em andamento.',
  },
  {
    key: 'models',
    label: 'Modelos',
    to: '/modelos',
    icon: 'layers',
    ready: false,
    promise: 'Os modelos de voz e de transcrição instalados na máquina.',
  },
  { key: 'outputs', label: 'Saídas', to: '/saidas', icon: 'video', ready: true },
]

/** Onde a interface anterior continua disponível enquanto a nova não cobre tudo. */
export const CLASSIC_UI_PATH = '/classica'
