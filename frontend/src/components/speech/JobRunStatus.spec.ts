import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import JobRunStatus, { type JobRunView } from './JobRunStatus.vue'

const idle: JobRunView = {
  running: false,
  label: '',
  percent: null,
  startedAtMs: null,
  cancelling: false,
  error: '',
  cancelled: false,
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-29T12:00:00Z'))
})
afterEach(() => vi.useRealTimers())

describe('JobRunStatus', () => {
  it('parado e sem problema não mostra nada', () => {
    expect(mount(JobRunStatus, { props: { job: idle, title: 'Isolar voz' } }).text()).toBe('')
  })

  it('rodando mostra a etapa, a porcentagem e o tempo decorrido, e a barra tem nome', () => {
    const job = { ...idle, running: true, label: 'bloco 2 de 4', percent: 50, startedAtMs: Date.now() - 65_000 }
    const wrapper = mount(JobRunStatus, { props: { job, title: 'Isolar voz' } })
    expect(wrapper.text()).toContain('bloco 2 de 4')
    expect(wrapper.text()).toContain('50%')
    expect(wrapper.text()).toContain('1:05 decorridos')
    expect(wrapper.find('[role="progressbar"]').attributes('aria-label')).toBe('Andamento: Isolar voz')
    expect(wrapper.find('[role="progressbar"]').attributes('aria-valuenow')).toBe('50')
  })

  it('sem porcentagem a barra fica indeterminada e não escreve 0%', () => {
    const job = { ...idle, running: true, label: 'Na fila...', startedAtMs: Date.now() }
    const wrapper = mount(JobRunStatus, { props: { job, title: 'Transcrever' } })
    expect(wrapper.find('[role="progressbar"]').attributes('aria-valuenow')).toBeUndefined()
    expect(wrapper.text()).not.toContain('%')
  })

  it('o relógio anda sozinho a cada segundo', async () => {
    const job = { ...idle, running: true, label: 'x', percent: null, startedAtMs: Date.now() }
    const wrapper = mount(JobRunStatus, { props: { job, title: 'Transcrever' } })
    expect(wrapper.text()).toContain('0:00 decorridos')
    await vi.advanceTimersByTimeAsync(3000)
    expect(wrapper.text()).toContain('0:03 decorridos')
  })

  it('o botão de parar só aparece nos trabalhos que o servidor aceita cancelar', async () => {
    const job = { ...idle, running: true, label: 'x', startedAtMs: Date.now() }
    const sem = mount(JobRunStatus, { props: { job, title: 'T' } })
    expect(sem.findAll('button')).toHaveLength(0)

    const com = mount(JobRunStatus, { props: { job, title: 'T', cancellable: true } })
    await com.find('button').trigger('click')
    expect(com.find('button').text()).toBe('Parar')
    expect(com.emitted('cancel')).toHaveLength(1)
  })

  it('o erro aparece como alerta, com o texto do servidor', () => {
    const wrapper = mount(JobRunStatus, { props: { job: { ...idle, error: 'Não achei "Pedro" na fala.' }, title: 'T' } })
    expect(wrapper.find('[role="alert"]').text()).toContain('Não achei "Pedro" na fala.')
  })

  it('trabalho parado a pedido diz isso sem parecer erro', () => {
    const wrapper = mount(JobRunStatus, { props: { job: { ...idle, cancelled: true }, title: 'T' } })
    expect(wrapper.text()).toContain('Parado a pedido')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })
})
