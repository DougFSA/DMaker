import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { DubSegmentReport } from '@/api'
import { rowsFrom, type DubRow } from '@/lib/dub'
import { SEGMENTS } from '@/test/dubServer'
import DubSegmentsTable from './DubSegmentsTable.vue'

const report = (over: Partial<DubSegmentReport>): DubSegmentReport => ({
  id: 's1',
  start: 0,
  end: 2.5,
  text: '',
  natural_seconds: 1,
  speech_seconds: 1,
  played_seconds: 1,
  tempo: 1,
  video_stretch: 1,
  retimed_start: null,
  status: 'fits',
  message: 'Cabe no tempo.',
  cached: true,
  speaker: '',
  voice: '',
  ...over,
})

function mountTable(props: Record<string, unknown> = {}) {
  let rows: DubRow[] = rowsFrom(SEGMENTS)
  const wrapper = mount(DubSegmentsTable, {
    props: {
      modelValue: rows,
      'onUpdate:modelValue': (next: DubRow[]) => {
        rows = next
        void wrapper.setProps({ modelValue: next })
      },
      ...props,
    },
  })
  return { wrapper, rows: () => rows }
}

describe('DubSegmentsTable', () => {
  it('mostra tempo, original e tradução de cada fala, em uma tabela com legenda', () => {
    const { wrapper } = mountTable()
    expect(wrapper.find('caption').text()).toContain('Falas da dublagem')
    expect(wrapper.findAll('th').map((cell) => cell.text())).toEqual(['Tempo', 'Original', 'Tradução', 'Travar'])
    const first = wrapper.findAll('tbody tr')[0]!
    expect(first.text()).toContain('0,0 a 2,5 s')
    expect(first.text()).toContain('Olá a todos.')
    expect((first.find('textarea').element as HTMLTextAreaElement).value).toBe('Hello everyone.')
  })

  it('cada campo tem um rótulo com o número da fala, para leitor de tela', () => {
    const { wrapper } = mountTable()
    const labels = wrapper.findAll('label').map((label) => label.text())
    expect(labels).toContain('Tradução da fala s1')
    expect(labels).toContain('Tradução da fala s3')
    // os ids não se repetem entre as linhas
    const ids = wrapper.findAll('textarea').map((area) => area.attributes('id'))
    expect(new Set(ids).size).toBe(3)
  })

  it('editar a tradução ou a trava devolve só a linha mudada, sem mexer nas outras', async () => {
    const { wrapper, rows } = mountTable()
    await wrapper.findAll('textarea')[1]!.setValue('Another text.')
    await wrapper.findAll('input[type="checkbox"]')[0]!.setValue(true)
    expect(rows().map((row) => [row.text, row.locked])).toEqual([
      ['Hello everyone.', true],
      ['Another text.', true],
      ['See you next time.', false],
    ])
    // tempo e original não se editam
    expect(rows()[1]).toMatchObject({ start: 3, end: 5.5, original: 'Hoje vamos falar de vídeo.' })
  })

  it('o falante só aparece com dois ou mais; a fala sem falante oferece "Sem falante"', async () => {
    const { wrapper, rows } = mountTable({ speakers: ['Falante 1', 'Falante 2'] })
    expect(wrapper.findAll('th').map((cell) => cell.text())).toContain('Falante')
    const picks = wrapper.findAll('select')
    expect(picks).toHaveLength(3)
    expect(picks[0]!.findAll('option').map((option) => option.text())).toEqual(['Sem falante', 'Falante 1', 'Falante 2'])
    await picks[0]!.setValue('Falante 2')
    expect(rows()[0]!.speaker).toBe('Falante 2')
    // depois de escolhido, "Sem falante" some: o servidor não sabe limpar o falante
    expect(wrapper.findAll('select')[0]!.findAll('option').map((option) => option.text())).toEqual(['Falante 1', 'Falante 2'])
  })

  it('com um falante só não há coluna de falante', () => {
    const { wrapper } = mountTable({ speakers: ['Falante 1'] })
    expect(wrapper.find('select').exists()).toBe(false)
  })

  it('depois de gerar, mostra a situação de cada fala e a marca "nova"', () => {
    const { wrapper } = mountTable({
      reports: {
        s1: report({ status: 'fits', cached: false }),
        s2: report({ id: 's2', status: 'overflow', message: 'A fala não coube e foi cortada.', cached: true }),
        s3: report({ id: 's3', status: 'stretched', video_stretch: 1.5, cached: true }),
      },
    })
    expect(wrapper.findAll('th').map((cell) => cell.text())).toContain('Situação')
    const cells = wrapper.findAll('td.fit')
    expect(cells[0]!.text()).toBe('cabe nova')
    expect(cells[1]!.text()).toBe('não coube')
    expect(cells[1]!.find('.badge').attributes('title')).toBe('A fala não coube e foi cortada.')
    expect(cells[1]!.find('.badge--error').exists()).toBe(true)
    expect(cells[2]!.text()).toBe('vídeo esticado 1,50x')
  })

  it('desligada, nenhum campo aceita edição', () => {
    const { wrapper } = mountTable({ disabled: true })
    const fields = [...wrapper.findAll('textarea'), ...wrapper.findAll('input')]
    expect(fields.length).toBe(6)
    expect(fields.every((field) => field.attributes('disabled') !== undefined)).toBe(true)
  })
})
