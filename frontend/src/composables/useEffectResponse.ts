/* A resposta de frequência de um efeito de equalização, pedida ao servidor (POST /api/audio-effects/response) toda vez que
   o efeito muda, depois de uma espera curta: arrastar um ponto ou um controle redesenha o gráfico ao vivo sem uma chamada
   por pixel. Uma resposta atrasada de um pedido antigo nunca sobrepõe a do mais novo. A conta é a mesma do render. */
import { onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { errorMessage } from '@/api'
import { fetchEffectResponse } from '@/api/audioEffects'
import type { AudioEffectSettings, EffectResponse } from '@/api'

/** Quanto esperar o efeito parar de mudar antes de pedir a curva: curto, para o gráfico acompanhar o arraste. */
export const RESPONSE_DELAY_MS = 120

/** O efeito sem o que não muda a curva (bypass e intervalo): dois efeitos que só diferem nisso têm o mesmo gráfico. */
function curveInput(effect: AudioEffectSettings): AudioEffectSettings {
  const rest = { ...effect }
  delete rest.enabled
  delete rest.start
  delete rest.end
  return rest
}

export function useEffectResponse(effect: Ref<AudioEffectSettings | null>, delay = RESPONSE_DELAY_MS) {
  const curve = ref<EffectResponse | null>(null)
  const error = ref('')
  let timer: ReturnType<typeof setTimeout> | null = null
  let ticket = 0

  async function run(): Promise<void> {
    const current = effect.value
    if (!current) return
    const mine = ++ticket
    try {
      const response = await fetchEffectResponse(curveInput(current))
      if (mine !== ticket) return
      curve.value = response
      error.value = ''
    } catch (failure) {
      if (mine !== ticket) return
      error.value = errorMessage(failure)
    }
  }

  function schedule(first = false): void {
    if (timer) clearTimeout(timer)
    timer = null
    if (!effect.value) {
      ticket += 1
      curve.value = null
      return
    }
    timer = setTimeout(() => void run(), first ? 0 : delay)
  }

  watch(effect, () => schedule(), { deep: true })
  schedule(true)

  onBeforeUnmount(() => {
    ticket += 1 // o pedido que ainda voa não escreve num componente que já saiu
    if (timer) clearTimeout(timer)
  })

  return { curve, error }
}
