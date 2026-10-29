import { createRouter, createWebHistory, type RouterHistory } from 'vue-router'

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
      {
        path: '/agente',
        name: 'agent',
        component: () => import('@/views/AgentView.vue'),
        meta: { title: 'Agente' },
      },
      // as áreas do DMK-38: cada rota já tem a view própria ("em construção" até a frente dela chegar)
      {
        path: '/voz',
        component: () => import('@/views/voice/VoiceShellView.vue'),
        children: [
          {
            path: '',
            name: 'voice',
            component: () => import('@/views/voice/VoicesView.vue'),
            meta: { title: 'Vozes' },
          },
          {
            path: 'narracao',
            name: 'voice-narration',
            component: () => import('@/views/voice/NarrationView.vue'),
            meta: { title: 'Narração' },
          },
          {
            path: 'pronuncia',
            name: 'voice-pronunciation',
            component: () => import('@/views/voice/PronunciationView.vue'),
            meta: { title: 'Pronúncia' },
          },
          {
            path: 'isolar',
            name: 'voice-isolate',
            component: () => import('@/views/voice/IsolateView.vue'),
            meta: { title: 'Isolar voz' },
          },
          {
            path: 'corrigir',
            name: 'voice-fix',
            component: () => import('@/views/voice/FixSpeechView.vue'),
            meta: { title: 'Corrigir fala' },
          },
          {
            path: 'trocar',
            name: 'voice-swap',
            component: () => import('@/views/voice/SwapVoiceView.vue'),
            meta: { title: 'Trocar voz' },
          },
        ],
      },
      {
        path: '/dublagem',
        name: 'dubbing',
        component: () => import('@/views/DubbingView.vue'),
        meta: { title: 'Dublagem' },
      },
      {
        path: '/fila',
        name: 'queue',
        component: () => import('@/views/QueueView.vue'),
        meta: { title: 'Fila' },
      },
      {
        path: '/modelos',
        name: 'models',
        component: () => import('@/views/ModelsView.vue'),
        meta: { title: 'Modelos' },
      },
      {
        // sem nome (/editor) é o item do menu lateral; com nome é o editor daquele projeto
        path: '/editor/:name?',
        name: 'editor',
        component: () => import('@/views/EditorView.vue'),
        props: true,
        meta: { title: 'Editor' },
      },
      {
        path: '/:rest(.*)*',
        name: 'not-found',
        component: () => import('@/views/NotFoundView.vue'),
        meta: { title: 'Página não encontrada' },
      },
    ],
  })

  router.afterEach((to, _from, failure) => {
    // uma navegação recusada (o editor perguntou se descarta e a pessoa ficou) não troca o título da aba
    if (failure) return
    document.title = `${to.meta.title} · DMaker`
  })

  return router
}
