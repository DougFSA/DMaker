import { describe, expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import { CLASSIC_UI_PATH, NAV_ITEMS } from '@/navigation'
import { createAppRouter } from './index'

function newRouter() {
  return createAppRouter(createMemoryHistory())
}

describe('rotas das áreas do DMK-38', () => {
  const areas: Array<[string, string, string]> = [
    ['/voz', 'voice', 'Vozes'],
    ['/voz/narracao', 'voice-narration', 'Narração'],
    ['/voz/pronuncia', 'voice-pronunciation', 'Pronúncia'],
    ['/voz/isolar', 'voice-isolate', 'Isolar voz'],
    ['/voz/corrigir', 'voice-fix', 'Corrigir fala'],
    ['/voz/trocar', 'voice-swap', 'Trocar voz'],
    ['/dublagem', 'dubbing', 'Dublagem'],
    ['/fila', 'queue', 'Fila'],
    ['/modelos', 'models', 'Modelos'],
    ['/editor/meu-video', 'editor', 'Editor'],
    ['/editor', 'editor', 'Editor'],
  ]

  it.each(areas)('%s abre a rota %s, com o título %s', async (path, name, title) => {
    const router = newRouter()
    await router.push(path)
    expect(router.currentRoute.value.name).toBe(name)
    expect(router.currentRoute.value.meta.title).toBe(title)
  })

  it('o título da aba do navegador acompanha a seção da Voz', async () => {
    const router = newRouter()
    await router.push('/voz/pronuncia')
    expect(document.title).toBe('Pronúncia · DMaker')
  })

  it('o editor recebe o nome do projeto como parâmetro', async () => {
    const router = newRouter()
    await router.push('/editor/casamento%20da%20ana')
    expect(router.currentRoute.value.params.name).toBe('casamento da ana')
  })

  it('as seções da Voz são filhas de /voz (uma só casca)', async () => {
    const router = newRouter()
    await router.push('/voz/isolar')
    expect(router.currentRoute.value.matched).toHaveLength(2)
    expect(router.currentRoute.value.matched[0]?.path).toBe('/voz')
  })

  it('as rotas antigas continuam no lugar', async () => {
    const router = newRouter()
    for (const [path, name] of [
      ['/projetos', 'projects'],
      ['/lote', 'batch'],
      ['/saidas', 'outputs'],
      ['/transicoes', 'transitions'],
      ['/looks', 'looks'],
      ['/infograficos', 'infographics'],
      ['/agente', 'agent'],
    ] as const) {
      await router.push(path)
      expect(router.currentRoute.value.name).toBe(name)
    }
  })
})

describe('barra lateral', () => {
  it('todo item leva a uma rota que existe, nunca à página de não encontrado', async () => {
    const router = newRouter()
    for (const item of NAV_ITEMS) {
      await router.push(item.to)
      expect(router.currentRoute.value.name, item.to).not.toBe('not-found')
    }
  })

  it('as chaves e os caminhos dos itens não se repetem', () => {
    expect(new Set(NAV_ITEMS.map((item) => item.key)).size).toBe(NAV_ITEMS.length)
    expect(new Set(NAV_ITEMS.map((item) => item.to)).size).toBe(NAV_ITEMS.length)
  })

  it('a interface clássica continua em /classica', () => {
    expect(CLASSIC_UI_PATH).toBe('/classica')
  })
})
