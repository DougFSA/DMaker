import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { useConfirm } from '@/composables/useConfirm'
import { useConfirmStore } from '@/stores/confirm'
import ConfirmHost from './ConfirmHost.vue'

let wrapper: VueWrapper | null = null

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

const button = (label: string) =>
  Array.from(document.body.querySelectorAll('button')).find((node) => node.textContent?.trim() === label) as
    | HTMLButtonElement
    | undefined

function mountHost() {
  wrapper = mount(ConfirmHost, { global: { plugins: [] }, attachTo: document.body })
  return wrapper
}

describe('useConfirm com o ConfirmHost', () => {
  it('não mostra nada enquanto ninguém pergunta', async () => {
    mountHost()
    await flushPromises()
    expect(document.body.querySelector('[role="alertdialog"]')).toBeNull()
  })

  it('resolve true quando a pessoa confirma', async () => {
    mountHost()
    const confirm = useConfirm()
    const answer = confirm({ title: 'Remover a voz?', confirmLabel: 'Remover', tone: 'danger' })
    await flushPromises()
    expect(document.body.textContent).toContain('Remover a voz?')
    button('Remover')?.click()
    await expect(answer).resolves.toBe(true)
    await flushPromises()
    expect(document.body.querySelector('[role="alertdialog"]')).toBeNull()
  })

  it('resolve false quando a pessoa cancela', async () => {
    mountHost()
    const answer = useConfirm()({ title: 'Remover a voz?' })
    await flushPromises()
    button('Cancelar')?.click()
    await expect(answer).resolves.toBe(false)
  })

  it('perguntas seguidas esperam a vez, cada uma com a sua resposta', async () => {
    mountHost()
    const confirm = useConfirm()
    const first = confirm({ title: 'Primeira?', confirmLabel: 'Sim' })
    const second = confirm({ title: 'Segunda?', confirmLabel: 'Sim' })
    await flushPromises()
    expect(document.body.textContent).toContain('Primeira?')
    expect(document.body.textContent).not.toContain('Segunda?')

    button('Cancelar')?.click()
    await expect(first).resolves.toBe(false)
    await flushPromises()
    expect(document.body.textContent).toContain('Segunda?')

    button('Sim')?.click()
    await expect(second).resolves.toBe(true)
  })
})

describe('useConfirmStore', () => {
  it('answer sem pergunta pendente não faz nada', () => {
    const store = useConfirmStore()
    expect(() => store.answer(true)).not.toThrow()
    expect(store.current).toBeNull()
  })

  it('a pergunta da vez carrega as opções e um id próprio', () => {
    const store = useConfirmStore()
    void store.ask({ title: 'A' })
    void store.ask({ title: 'B' })
    const first = store.current
    expect(first?.options.title).toBe('A')
    store.answer(true)
    expect(store.current?.options.title).toBe('B')
    expect(store.current?.id).not.toBe(first?.id)
  })
})
