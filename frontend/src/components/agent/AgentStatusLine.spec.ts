import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AgentStatusLine from './AgentStatusLine.vue'

afterEach(() => vi.useRealTimers())

describe('AgentStatusLine', () => {
  it('diz a etapa e conta o tempo decorrido', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-30T12:00:00Z'))
    const wrapper = mount(AgentStatusLine, {
      props: { stage: { stage: 'loading_model', label: 'Carregando o modelo', since: Date.now() }, stopping: false, waiting: false },
    })
    expect(wrapper.text()).toBe('Carregando o modelo... 0 s')

    await vi.advanceTimersByTimeAsync(65_000)
    expect(wrapper.text()).toBe('Carregando o modelo... 1 min 05 s')
    wrapper.unmount()
  })

  it('antes de o servidor informar a etapa, diz que aguarda o modelo', () => {
    const wrapper = mount(AgentStatusLine, { props: { stage: null, stopping: false, waiting: false } })
    expect(wrapper.text()).toBe('Aguardando o modelo...')
  })

  it('esperando um clique, diz que espera a confirmação e não mostra o ponto de andamento', () => {
    const wrapper = mount(AgentStatusLine, {
      props: { stage: { stage: 'tool', label: 'Chamando a ferramenta render_project', since: Date.now() }, stopping: false, waiting: true },
    })
    expect(wrapper.text()).toBe('Esperando a sua confirmação.')
    expect(wrapper.find('.working__dot').exists()).toBe(false)
  })

  it('parando, diz "Parando"; numa ferramenta, avisa que ela termina antes', () => {
    const reading = mount(AgentStatusLine, {
      props: { stage: { stage: 'reading', label: 'Lendo o pedido', since: Date.now() }, stopping: true, waiting: false },
    })
    expect(reading.text()).toBe('Parando...')

    const tool = mount(AgentStatusLine, {
      props: { stage: { stage: 'tool', label: 'Chamando a ferramenta render_project', since: Date.now() }, stopping: true, waiting: false },
    })
    expect(tool.text()).toBe('Parando. A ferramenta em andamento precisa terminar antes.')
  })
})
