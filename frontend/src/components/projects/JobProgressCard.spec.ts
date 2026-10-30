import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { JobView } from '@/stores/jobs'
import JobProgressCard from './JobProgressCard.vue'

function job(overrides: Partial<JobView> = {}): JobView {
  return {
    id: 'j1',
    description: 'demo: preview',
    status: 'running',
    project: 'demo',
    progress: null,
    startedAtMs: Date.now() - 4000,
    finishedAtMs: null,
    error: null,
    log: [],
    result: null,
    ...overrides,
  }
}

const stages = (wrapper: ReturnType<typeof mount>) =>
  wrapper.findAll('.stage').map((node) => [node.find('span:not(.visually-hidden):not(.stage__dot):not(.stage__detail)').text(), node.classes()[1]])

describe('JobProgressCard: etapas do render', () => {
  it('lista as sete etapas deduzidas do log, com a atual em destaque e o detalhe do comando', () => {
    const wrapper = mount(JobProgressCard, {
      props: {
        job: job({
          log: ['render demo: instagram/reels 540x960 (preview)', 'trechos: 5 (5 a gerar, 0 em cache)'],
          progress: { label: 'trecho 2/5', percent: 40 },
        }),
      },
    })
    expect(stages(wrapper)).toEqual([
      ['Fontes e sincronização', 'stage--done'],
      ['Trechos', 'stage--current'],
      ['Legendas', 'stage--pending'],
      ['Camada de texto', 'stage--pending'],
      ['Loudness', 'stage--pending'],
      ['Montagem final', 'stage--pending'],
      ['Miniatura', 'stage--pending'],
    ])
    expect(wrapper.find('.stage--current').attributes('aria-current')).toBe('step')
    expect(wrapper.find('.stage--current .stage__detail').text()).toBe('trecho 2/5')
  })

  it('diz a situação de cada etapa também para o leitor de tela', () => {
    const wrapper = mount(JobProgressCard, { props: { job: job({ log: ['render demo: x', 'trechos: 2'] }) } })
    const hidden = wrapper.findAll('.stage .visually-hidden').map((node) => node.text())
    expect(hidden.slice(0, 3)).toEqual([', feita', ', em andamento', ', por fazer'])
  })

  it('um job que não é render (sem marca de etapa) não mostra a lista', () => {
    const wrapper = mount(JobProgressCard, { props: { job: job({ description: 'narração (voz automática)', log: ['Iniciado'] }) } })
    expect(wrapper.find('.stages').exists()).toBe(false)
    expect(wrapper.find('[role="progressbar"]').exists()).toBe(true)
  })

  it('terminado, a lista some e o cartão mostra o resultado', () => {
    const wrapper = mount(JobProgressCard, {
      props: { job: job({ status: 'done', finishedAtMs: Date.now(), log: ['render demo: x', 'pronto: a.mp4'] }) },
    })
    expect(wrapper.find('.stages').exists()).toBe(false)
    expect(wrapper.text()).toContain('Terminou em')
  })
})
