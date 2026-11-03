import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { LEFTOVER_DIR, LEFTOVER_FILE } from '@/test/modelsServer'
import LeftoversCard from './LeftoversCard.vue'

const leftovers = [LEFTOVER_FILE, LEFTOVER_DIR]

describe('LeftoversCard', () => {
  it('lista cada sobra com o tamanho e mostra o total', () => {
    const wrapper = mount(LeftoversCard, { props: { leftovers, total: '2 item(ns), 3,0 MB' } })
    expect(wrapper.findAll('li').map((item) => item.text())).toEqual(['velho/modelo.bin: 2,0 MB', 'restos/: 1,0 MB'])
    expect(wrapper.find('[data-testid="leftovers-total"]').text()).toBe('2 item(ns), 3,0 MB')
  })

  it('pede para apagar ao clicar, e só quando não está bloqueado', async () => {
    const free = mount(LeftoversCard, { props: { leftovers, total: 't' } })
    await free.find('button').trigger('click')
    expect(free.emitted('prune')).toHaveLength(1)

    const blocked = mount(LeftoversCard, { props: { leftovers, total: 't', blockedReason: 'Espere o download terminar.' } })
    expect(blocked.find('button').attributes('disabled')).toBeDefined()
    expect(blocked.text()).toContain('Espere o download terminar.')
  })

  it('enquanto apaga, o botão mostra que está ocupado', () => {
    const wrapper = mount(LeftoversCard, { props: { leftovers, total: 't', loading: true } })
    expect(wrapper.find('button').attributes('aria-busy')).toBe('true')
  })
})
