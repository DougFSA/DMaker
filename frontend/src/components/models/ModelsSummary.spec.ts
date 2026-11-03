import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { ModelInventory } from '@/api'
import { DEFAULT_MODELS, LEFTOVER_FILE } from '@/test/modelsServer'
import ModelsSummary from './ModelsSummary.vue'

function inventory(over: Partial<ModelInventory> = {}): ModelInventory {
  return {
    models_dir: 'X:/dados/cache/models',
    models: DEFAULT_MODELS,
    leftovers: [],
    total_bytes: 4_000_000_000,
    total_label: '3,73 GB',
    leftover_bytes: 0,
    leftover_label: '0 B',
    disk_free_bytes: 50_000_000_000,
    disk_free_label: '46,57 GB',
    ...over,
  }
}

describe('ModelsSummary', () => {
  it('mostra o que os modelos ocupam, o espaço livre e a pasta', () => {
    const wrapper = mount(ModelsSummary, { props: { inventory: inventory() } })
    expect(wrapper.find('[data-testid="models-summary"]').text()).toBe('Ocupado em cache/models: 3,73 GB · Livre no disco: 46,57 GB')
    expect(wrapper.find('[data-testid="models-dir"]').text()).toBe('X:/dados/cache/models')
  })

  it('acrescenta as sobras quando existem e tira o espaço livre quando não foi medido', () => {
    const wrapper = mount(ModelsSummary, {
      props: { inventory: inventory({ leftovers: [LEFTOVER_FILE], leftover_label: '2,0 MB', disk_free_bytes: null, disk_free_label: null }) },
    })
    expect(wrapper.find('[data-testid="models-summary"]').text()).toBe('Ocupado em cache/models: 3,73 GB · Sobras: 2,0 MB')
  })
})
