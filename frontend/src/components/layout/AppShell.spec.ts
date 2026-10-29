import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import AppShell from './AppShell.vue'

const Blank = { render: () => null }

async function mountShell(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/projetos', component: Blank, meta: { title: 'Projetos' } },
      { path: '/editor/:name?', component: Blank, meta: { title: 'Editor', wide: true } },
    ],
  })
  await router.push(path)
  await router.isReady()
  // a barra lateral e a de cima têm as suas próprias telas de teste; aqui só importa o miolo
  return mount(AppShell, { global: { plugins: [createPinia(), router], stubs: { SidebarNav: true, TopBar: true } } })
}

describe('AppShell', () => {
  it('o conteúdo tem o limite de leitura nas telas comuns', async () => {
    const shell = await mountShell('/projetos')
    expect(shell.find('#conteudo').classes()).not.toContain('shell__content--wide')
  })

  it('a rota que pede a largura toda (o editor) tira o limite do conteúdo', async () => {
    const shell = await mountShell('/editor/demo')
    expect(shell.find('#conteudo').classes()).toContain('shell__content--wide')
  })

  it('o editor sem projeto (/editor) também usa a largura toda', async () => {
    const shell = await mountShell('/editor')
    expect(shell.find('#conteudo').classes()).toContain('shell__content--wide')
  })
})
