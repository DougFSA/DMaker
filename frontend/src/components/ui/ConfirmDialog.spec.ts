import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import ConfirmDialog from './ConfirmDialog.vue'

let wrapper: VueWrapper | null = null

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

function mountDialog(props: Record<string, unknown> = {}) {
  wrapper = mount(ConfirmDialog, {
    props: { open: true, title: 'Apagar o modelo?', ...props },
    attachTo: document.body,
  })
  return wrapper
}

const button = (label: string) =>
  Array.from(document.body.querySelectorAll('button')).find((node) => node.textContent?.trim() === label) as
    | HTMLButtonElement
    | undefined

describe('ConfirmDialog', () => {
  it('é um alerta com título, texto e aviso em destaque', async () => {
    mountDialog({
      description: 'Esta ação não pode ser desfeita.',
      warning: 'Vai apagar o Whisper e liberar 3 GB.',
      tone: 'danger',
    })
    await flushPromises()
    const dialog = document.body.querySelector('[role="alertdialog"]')
    expect(dialog).not.toBeNull()
    expect(dialog?.textContent).toContain('Apagar o modelo?')
    expect(dialog?.textContent).toContain('Esta ação não pode ser desfeita.')
    expect(document.body.querySelector('.confirm__warning--danger')?.textContent).toContain('Vai apagar o Whisper')
  })

  it('confirmar emite confirm e não emite cancel', async () => {
    const dialog = mountDialog({ confirmLabel: 'Apagar' })
    await flushPromises()
    button('Apagar')?.click()
    await flushPromises()
    expect(dialog.emitted('confirm')).toHaveLength(1)
    expect(dialog.emitted('cancel')).toBeUndefined()
  })

  it('cancelar emite cancel e não emite confirm', async () => {
    const dialog = mountDialog()
    await flushPromises()
    button('Cancelar')?.click()
    await flushPromises()
    expect(dialog.emitted('cancel')).toHaveLength(1)
    expect(dialog.emitted('confirm')).toBeUndefined()
  })

  it('Esc também cancela', async () => {
    const dialog = mountDialog()
    await flushPromises()
    document.body.querySelector('[role="alertdialog"]')?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await flushPromises()
    expect(dialog.emitted('cancel')).toHaveLength(1)
  })

  it('o foco começa em Cancelar, o lado seguro', async () => {
    mountDialog({ tone: 'danger', confirmLabel: 'Apagar' })
    await flushPromises()
    expect(document.activeElement).toBe(button('Cancelar'))
  })

  it('o botão de confirmar segue o tom e os rótulos pedidos', async () => {
    mountDialog({ tone: 'danger', confirmLabel: 'Apagar', cancelLabel: 'Manter' })
    await flushPromises()
    expect(button('Apagar')?.className).toContain('btn--danger')
    expect(button('Manter')).toBeDefined()
  })

  it('reaberto, volta a emitir o desfecho', async () => {
    const dialog = mountDialog()
    await flushPromises()
    button('Cancelar')?.click()
    await flushPromises()
    await dialog.setProps({ open: false })
    await dialog.setProps({ open: true })
    await flushPromises()
    button('Cancelar')?.click()
    await flushPromises()
    expect(dialog.emitted('cancel')).toHaveLength(2)
  })
})
