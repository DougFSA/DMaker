import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import SendToQueueDialog from './SendToQueueDialog.vue'

let wrapper: VueWrapper | null = null

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

async function mountDialog(props: { open?: boolean; busy?: boolean; characters?: number } = {}) {
  wrapper = mount(SendToQueueDialog, {
    props: { open: true, busy: false, characters: 1234, ...props },
    attachTo: document.body,
  })
  // o diálogo se desenha no portal um instante depois de montar
  await flushPromises()
  return wrapper
}

/** O diálogo mora num portal fora do componente. */
const dialog = () => document.body.querySelector('[role="dialog"]') as HTMLElement
const button = (label: string) =>
  [...dialog().querySelectorAll('button')].find((node) => node.textContent?.trim() === label) as HTMLButtonElement

describe('SendToQueueDialog', () => {
  it('explica o que a fila faz e quantos caracteres o roteiro tem', async () => {
    await mountDialog()
    expect(dialog().textContent).toContain('A fila narra em segundo plano, um roteiro por vez')
    expect(dialog().textContent).toContain('O roteiro tem 1.234 caracteres.')
  })

  it('fechado, não mostra nada', async () => {
    await mountDialog({ open: false })
    expect(document.body.querySelector('[role="dialog"]')).toBeNull()
  })

  it('envia com o formato WAV e sem rascunho, a menos que a pessoa mude', async () => {
    const mounted = await mountDialog()
    ;(dialog().querySelector('form') as HTMLFormElement).dispatchEvent(new Event('submit', { cancelable: true }))
    expect(mounted.emitted('send')).toEqual([[{ title: '', format: 'wav', draft: false }]])
  })

  it('envia o título, o formato e o rascunho escolhidos', async () => {
    const mounted = await mountDialog()
    const title = dialog().querySelector('input[type="text"]') as HTMLInputElement
    title.value = 'Capítulo 1'
    title.dispatchEvent(new Event('input'))
    button('MP3').click()
    ;(dialog().querySelector('input[type="checkbox"]') as HTMLInputElement).click()
    await mounted.vm.$nextTick()
    ;(dialog().querySelector('form') as HTMLFormElement).dispatchEvent(new Event('submit', { cancelable: true }))
    expect(mounted.emitted('send')).toEqual([[{ title: 'Capítulo 1', format: 'mp3', draft: true }]])
  })

  it('Cancelar fecha o diálogo sem enviar', async () => {
    const mounted = await mountDialog()
    button('Cancelar').click()
    await mounted.vm.$nextTick()
    expect(mounted.emitted('update:open')).toEqual([[false]])
    expect(mounted.emitted('send')).toBeUndefined()
  })

  it('enquanto envia, o botão fica em andamento', async () => {
    await mountDialog({ busy: true })
    expect(button('Mandar para a fila').getAttribute('disabled')).not.toBeNull()
  })

  it('o título de um roteiro não passa para o seguinte', async () => {
    const mounted = await mountDialog()
    const title = dialog().querySelector('input[type="text"]') as HTMLInputElement
    title.value = 'Capítulo 1'
    title.dispatchEvent(new Event('input'))
    await mounted.setProps({ open: false })
    await mounted.setProps({ open: true })
    await mounted.vm.$nextTick()
    expect((dialog().querySelector('input[type="text"]') as HTMLInputElement).value).toBe('')
  })
})
