import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { describe, expect, it } from 'vitest'
import type { QueueFile } from '@/api'
import QueueFiles from './QueueFiles.vue'

const AUDIO: QueueFile = { name: 'curso.wav', url: '/api/voices/queue/q1/files/curso.wav', audio: true }
const SUBTITLE: QueueFile = { name: 'curso.srt', url: '/api/voices/queue/q1/files/curso.srt', audio: false }

function mountFiles(files: QueueFile[]) {
  return mount(QueueFiles, { props: { files }, global: { plugins: [createPinia()] } })
}

describe('QueueFiles', () => {
  it('sem arquivo pronto, não desenha nada', () => {
    expect(mountFiles([]).find('details').exists()).toBe(false)
  })

  it('conta os arquivos no título do bloco e lista o nome de cada um', () => {
    const wrapper = mountFiles([AUDIO, SUBTITLE])
    expect(wrapper.find('summary').text()).toBe('Arquivos prontos (2)')
    expect(wrapper.findAll('li').map((row) => row.find('.file__name').text())).toEqual(['curso.wav', 'curso.srt'])
  })

  it('o áudio tem Ouvir e Baixar; a legenda só Baixar', () => {
    const [audio, subtitle] = mountFiles([AUDIO, SUBTITLE]).findAll('li')
    expect(audio!.findAll('button').map((button) => button.text())).toEqual(['Ouvir', 'Baixar'])
    expect(subtitle!.findAll('button').map((button) => button.text())).toEqual(['Baixar'])
  })

  it('Ouvir abre o player do arquivo e Fechar o tira', async () => {
    const wrapper = mountFiles([AUDIO, SUBTITLE])
    expect(wrapper.find('audio').exists()).toBe(false)

    await wrapper.find('button[aria-label="Ouvir curso.wav"]').trigger('click')
    const player = wrapper.find('audio')
    expect(player.attributes('src')).toBe('/api/voices/queue/q1/files/curso.wav')

    await wrapper.find('button[aria-label="Fechar curso.wav"]').trigger('click')
    expect(wrapper.find('audio').exists()).toBe(false)
  })

  it('só um player por item: ouvir outro áudio fecha o primeiro', async () => {
    const second: QueueFile = { name: 'curso-2.wav', url: '/api/voices/queue/q1/files/curso-2.wav', audio: true }
    const wrapper = mountFiles([AUDIO, second])
    await wrapper.find('button[aria-label="Ouvir curso.wav"]').trigger('click')
    await wrapper.find('button[aria-label="Ouvir curso-2.wav"]').trigger('click')
    expect(wrapper.findAll('audio')).toHaveLength(1)
    expect(wrapper.find('audio').attributes('src')).toBe('/api/voices/queue/q1/files/curso-2.wav')
    expect(wrapper.find('button[aria-label="Ouvir curso.wav"]').exists()).toBe(true)
  })
})
