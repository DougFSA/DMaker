import { createRouter, createWebHistory, type RouterHistory } from 'vue-router'
import { NAV_ITEMS } from '@/navigation'

declare module 'vue-router' {
  interface RouteMeta {
    title: string
  }
}

/** `history` entra por parâmetro para os testes usarem a memória em vez do navegador. */
export function createAppRouter(history: RouterHistory = createWebHistory()) {
  const router = createRouter({
    history,
    routes: [
      { path: '/', redirect: '/projetos' },
      {
        path: '/projetos',
        name: 'projects',
        component: () => import('@/views/ProjectsView.vue'),
        meta: { title: 'Projetos' },
      },
      {
        path: '/projetos/:name',
        name: 'project',
        component: () => import('@/views/ProjectDetailView.vue'),
        props: true,
        meta: { title: 'Projeto' },
      },
      {
        path: '/lote',
        name: 'batch',
        component: () => import('@/views/BatchView.vue'),
        meta: { title: 'Lote' },
      },
      {
        path: '/saidas',
        name: 'outputs',
        component: () => import('@/views/OutputsView.vue'),
        meta: { title: 'Saídas' },
      },
      {
        path: '/transicoes',
        name: 'transitions',
        component: () => import('@/views/TransitionsView.vue'),
        meta: { title: 'Transições' },
      },
      {
        path: '/looks',
        name: 'looks',
        component: () => import('@/views/LooksView.vue'),
        meta: { title: 'Looks' },
      },
      {
        path: '/infograficos',
        name: 'infographics',
        component: () => import('@/views/InfographicsView.vue'),
        meta: { title: 'Infográficos' },
      },
      // telas das próximas fases: a rota já existe, só o componente muda quando a fase chegar
      ...NAV_ITEMS.filter((item) => !item.ready).map((item) => ({
        path: item.to,
        name: `soon-${item.key}`,
        component: () => import('@/views/ComingSoonView.vue'),
        props: { itemKey: item.key },
        meta: { title: item.label },
      })),
      {
        path: '/:rest(.*)*',
        name: 'not-found',
        component: () => import('@/views/NotFoundView.vue'),
        meta: { title: 'Página não encontrada' },
      },
    ],
  })

  router.afterEach((to) => {
    document.title = `${to.meta.title} · DMaker`
  })

  return router
}
