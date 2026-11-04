/* A Draw Tool do painel Áudio (desenho de amostra no zoom máximo). Entra por último: ela grava o efeito `draw`, que
   roda no estágio de amostras do EffectProcessor (DMK-55). Até lá o gancho existe e não faz nada. */
import { ref, type Ref } from 'vue'
import type { AudioWave } from '@/api'

export interface DrawToolOptions {
  area: Ref<HTMLElement | null>
  width: Ref<number>
  height: Ref<number>
  data: () => AudioWave | null
}

export function useDrawTool(options: DrawToolOptions) {
  void options
  /** Os pontos (x,y em pixels da área) do traço em andamento, ou nulo; a onda os desenha por cima. */
  const preview = ref<string | null>(null)

  function start(event: MouseEvent): void {
    void event
  }

  return { preview, start }
}
