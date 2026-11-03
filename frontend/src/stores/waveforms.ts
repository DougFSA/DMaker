/* Os picos de forma de onda já pedidos ao servidor, por arquivo. Mora num store (e não no módulo) para cada tela
   começar com a memória limpa e para os testes trocarem o servidor por um falso. */
import { defineStore } from 'pinia'
import { api } from '@/api'
import { WaveformCache } from '@/lib/waveform'

export const useWaveformStore = defineStore('waveforms', () => {
  const cache = new WaveformCache((path, stream) => api.editor.waveform(path, stream))

  return {
    /** Os picos do arquivo (um pedido só por arquivo), ou nulo se o servidor não conseguiu gerá-los. */
    peaks: (path: string | null, stream = 0) => cache.peaks(path, stream),
    clear: () => cache.clear(),
  }
})
