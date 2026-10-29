import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { describe, expect, it } from 'vitest'
import type { QueueItem } from '@/api'
import type { MoveLimits } from '@/lib/queue'
import { finishedItem, queueItem } from '@/test/queueServer'
import QueueItemCard from './QueueItemCard.vue'

function mountCard(item: QueueItem, extra: { working?: boolean; limits?: MoveLimits } = {}) {
  return mount(QueueItemCard, { props: { item, ...extra }, global: { plugins: [createPinia()] } })
}

const actionButtons = (wrapper: ReturnType<typeof mountCard>) =>
  wrapper.findAll('.item__actions button').map((button) => button.text())

describe('QueueItemCard', () => {
  it('mostra o título, o estado, de onde veio o roteiro e o andamento', () => {
    const wrapper = mountCard(
      queueItem({
        title: 'Curso de pintura',
        state: 'running',
        state_label: 'Rodando',
        source: { kind: 'file', name: 'curso.docx' },
        chapter: 2,
        chapters_total: 4,
        chapter_title: 'Tintas a óleo',
        utterance: 5,
        utterances: 20,
        percent: 25,
        eta_label: '8 min',
      }),
    )
    expect(wrapper.find('h3').text()).toBe('Curso de pintura')
    expect(wrapper.text()).toContain('Rodando')
    expect(wrapper.text()).toContain('arquivo · curso.docx · WAV')
    expect(wrapper.text()).toContain('capítulo 2 de 4, fala 5 de 20 · faltam cerca de 8 min')
    expect(wrapper.text()).toContain('Tintas a óleo')
    expect(wrapper.find('[role="progressbar"]').attributes('aria-valuenow')).toBe('25')
  })

  it('os botões seguem o estado do item', () => {
    expect(actionButtons(mountCard(queueItem({ state: 'running' })))).toEqual(['Pausar', 'Cancelar'])
    expect(actionButtons(mountCard(queueItem({ state: 'paused' }), { limits: { up: true, down: true } }))).toEqual([
      'Retomar',
      'Cancelar',
      'Subir',
      'Descer',
    ])
    expect(actionButtons(mountCard(queueItem({ state: 'failed', error: 'sem memória' })))).toEqual(['Tentar de novo', 'Remover'])
    expect(actionButtons(mountCard(queueItem({ state: 'cancelled' })))).toEqual(['Tentar de novo', 'Remover'])
    expect(actionButtons(mountCard(finishedItem()))).toEqual(['Remover'])
  })

  it('cada botão avisa o que vai acontecer', () => {
    const wrapper = mountCard(queueItem({ state: 'running' }))
    const pause = wrapper.find('[data-action="pause"]')
    expect(pause.attributes('title')).toBe('Para na próxima fala e guarda o que já foi narrado')
  })

  it('o leitor de tela ouve a qual item o botão se refere', () => {
    const wrapper = mountCard(queueItem({ title: 'Curso de pintura', state: 'running' }))
    expect(wrapper.find('[data-action="pause"]').attributes('aria-label')).toBe('Pausar: Curso de pintura')
    expect(wrapper.find('[data-action="cancel"]').attributes('aria-label')).toBe('Cancelar: Curso de pintura')
  })

  it('apertar um botão avisa a ação', async () => {
    const wrapper = mountCard(queueItem({ state: 'running' }))
    await wrapper.find('[data-action="cancel"]').trigger('click')
    await wrapper.find('[data-action="pause"]').trigger('click')
    expect(wrapper.emitted('act')).toEqual([['cancel'], ['pause']])
  })

  it('o primeiro da fila não sobe e o último não desce', () => {
    const first = mountCard(queueItem(), { limits: { up: false, down: true } })
    expect(first.find('[data-action="up"]').attributes('disabled')).toBeDefined()
    expect(first.find('[data-action="down"]').attributes('disabled')).toBeUndefined()

    const last = mountCard(queueItem(), { limits: { up: true, down: false } })
    expect(last.find('[data-action="up"]').attributes('disabled')).toBeUndefined()
    expect(last.find('[data-action="down"]').attributes('disabled')).toBeDefined()
  })

  it('enquanto um comando espera a resposta, todos os botões ficam parados', () => {
    const wrapper = mountCard(queueItem(), { working: true, limits: { up: true, down: true } })
    const disabled = wrapper.findAll('.item__actions button').map((button) => button.attributes('disabled') !== undefined)
    expect(disabled).toEqual([true, true, true, true])
  })

  it('rodando e sem fala pronta, a barra fica indeterminada', () => {
    const preparing = mountCard(queueItem({ state: 'running', chapter: 0, percent: 0 }))
    expect(preparing.find('[role="progressbar"]').attributes('aria-valuenow')).toBeUndefined()
    expect(preparing.text()).toContain('Preparando o roteiro')

    const waiting = mountCard(queueItem({ state: 'pending', percent: 0 }))
    expect(waiting.find('[role="progressbar"]').attributes('aria-valuenow')).toBe('0')
  })

  it('item pronto não tem barra e mostra a pasta e a duração do áudio', () => {
    const wrapper = mountCard(finishedItem({ output_dir: 'output/voz/roteiro-pronto' }))
    expect(wrapper.find('[role="progressbar"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Pronto · 1 capítulo · 2 min de áudio')
    expect(wrapper.text()).toContain('Pasta: output/voz/roteiro-pronto')
  })

  it('item pronto lista os arquivos para ouvir e baixar', () => {
    const wrapper = mountCard(finishedItem())
    expect(wrapper.find('summary').text()).toBe('Arquivos prontos (2)')
  })

  it('a falha mostra a primeira linha do erro e deixa abrir o resto', () => {
    const wrapper = mountCard(
      queueItem({ state: 'failed', error: 'VoiceNotFoundError: A voz "x" não existe.\nTraceback (most recent call last)' }),
    )
    expect(wrapper.find('.item__progress').text()).toBe('A voz "x" não existe.')
    expect(wrapper.find('.item__error pre').text()).toContain('Traceback')
  })

  it('erro de uma linha só não ganha o bloco de detalhes', () => {
    const wrapper = mountCard(queueItem({ state: 'failed', error: 'sem memória' }))
    expect(wrapper.find('.item__error').exists()).toBe(false)
  })

  it('o aviso do momento aparece sob o andamento', () => {
    const wrapper = mountCard(queueItem({ state: 'running', note: 'Aguardando outra síntese terminar' }))
    expect(wrapper.text()).toContain('Aguardando outra síntese terminar')
  })
})
