import { mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import { microphoneKey } from '@/composables/useMicrophoneRecorder'
import { createMicrophone, MAX_RECORDING_MS, type Recording } from '@/lib/microphone'
import { FakeRecorder, fakeEnvironment, type FakeEnvironment } from '@/test/recorder'
import VoiceRecorder from './VoiceRecorder.vue'

let wrapper: VueWrapper | null = null

beforeEach(() => {
  FakeRecorder.reset()
  vi.useFakeTimers()
  URL.createObjectURL = vi.fn(() => 'blob:gravacao')
  URL.revokeObjectURL = vi.fn()
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.useRealTimers()
})

function mountRecorder(environment: FakeEnvironment = fakeEnvironment(), modelValue: Recording | null = null) {
  wrapper = mount(VoiceRecorder, {
    // o v-model é do pai: aqui o próprio teste devolve o valor novo ao componente
    props: { modelValue, 'onUpdate:modelValue': (value: Recording | null) => wrapper?.setProps({ modelValue: value }) },
    global: { provide: { [microphoneKey as symbol]: createMicrophone(() => environment) } },
  })
  return wrapper
}

const button = () => wrapper!.find('button')
const clock = () => wrapper!.find('.recorder__clock').text().replace('Tempo gravado:', '').trim()

/** Deixa o tempo e as promessas andarem e o Vue repintar. */
async function pass(ms: number): Promise<void> {
  await vi.advanceTimersByTimeAsync(ms)
  await nextTick()
}

describe('VoiceRecorder', () => {
  it('começa pronto para gravar, com o relógio zerado e o conselho de 5 a 8 segundos', () => {
    mountRecorder()
    expect(button().text()).toBe('Gravar')
    expect(clock()).toBe('0:00')
    expect(wrapper!.find('[role="status"]').text()).toBe('Recomendado: 5 a 8 segundos de fala limpa.')
    expect(wrapper!.text()).toContain('Para sozinho aos 30 s.')
  })

  it('grava e para: o relógio anda, o conselho acompanha e a gravação pronta pode ser ouvida', async () => {
    mountRecorder()
    await button().trigger('click')
    await pass(0)
    expect(button().text()).toBe('Parar gravação')

    await pass(2000)
    expect(clock()).toBe('0:02')
    expect(wrapper!.find('[role="status"]').attributes('data-level')).toBe('bad')

    await pass(4000)
    expect(clock()).toBe('0:06')
    expect(wrapper!.find('[role="status"]').attributes('data-level')).toBe('good')
    expect(wrapper!.find('[role="status"]').text()).toContain('Ótimo')

    await button().trigger('click')
    await pass(0)
    expect(button().text()).toBe('Gravar de novo')
    expect(wrapper!.find('audio').attributes('src')).toBe('blob:gravacao')
    expect(wrapper!.text()).toContain('Sua gravação')

    const emitted = wrapper!.emitted('update:modelValue')
    const recording = emitted?.at(-1)?.[0] as Recording
    expect(recording.filename).toBe('gravacao.webm')
    expect(recording.durationMs).toBe(6000)
  })

  it('aos 30 segundos para sozinho e entrega a gravação', async () => {
    mountRecorder()
    await button().trigger('click')
    await pass(MAX_RECORDING_MS + 1000)
    expect(button().text()).toBe('Gravar de novo')
    expect(clock()).toBe('0:30')
    expect(wrapper!.find('[role="status"]').text()).toBe('Só os primeiros 15 segundos serão usados.')
    expect((wrapper!.emitted('update:modelValue')?.at(-1)?.[0] as Recording).durationMs).toBe(MAX_RECORDING_MS)
  })

  it('permissão negada mostra a mensagem clara e deixa tentar de novo', async () => {
    mountRecorder(fakeEnvironment({ reject: 'NotAllowedError' }))
    await button().trigger('click')
    await pass(0)
    expect(wrapper!.find('[role="alert"]').text()).toBe(
      'Sem acesso ao microfone. Libere a permissão no navegador ou envie um arquivo.',
    )
    expect(button().text()).toBe('Gravar')
    expect(button().attributes('disabled')).toBeUndefined()
    expect(wrapper!.emitted('update:modelValue')).toBeUndefined()
  })

  it('navegador sem microfone: o botão fica desligado e a mensagem manda enviar um arquivo', () => {
    mountRecorder(fakeEnvironment({ noMicrophone: true }))
    expect(button().attributes('disabled')).toBeDefined()
    expect(wrapper!.find('[role="alert"]').text()).toBe(
      'Este navegador não grava pelo microfone. Envie um arquivo de áudio.',
    )
  })

  it('quando o formulário limpa a gravação, o gravador volta ao começo', async () => {
    mountRecorder()
    await button().trigger('click')
    await pass(3000)
    await button().trigger('click')
    await pass(0)
    expect(button().text()).toBe('Gravar de novo')

    await wrapper!.setProps({ modelValue: null })
    await pass(0)
    expect(button().text()).toBe('Gravar')
    expect(clock()).toBe('0:00')
    expect(wrapper!.find('audio').exists()).toBe(false)
  })

  it('sair da tela com o microfone aberto o solta', async () => {
    const environment = fakeEnvironment()
    mountRecorder(environment)
    await button().trigger('click')
    await pass(1000)
    expect(environment.stream.released).toBe(false)
    wrapper!.unmount()
    wrapper = null
    expect(environment.stream.released).toBe(true)
  })
})
