<script setup lang="ts">
/* O gráfico de resposta de frequência de um efeito de equalização sem controle próprio de curva (passa-alta, passa-baixa,
   Notch, prateleiras, Graves e agudos, filtros clássicos): a curva sai do servidor, calculada das mesmas seções de filtro
   que o render aplica, e se redesenha sozinha a cada ajuste de um parâmetro. */
import { toRef } from 'vue'
import type { AudioEffectSettings } from '@/api'
import { useEffectResponse } from '@/composables/useEffectResponse'
import EqResponseChart from './EqResponseChart.vue'

const props = defineProps<{
  effect: AudioEffectSettings
  name: string
}>()

const { curve, error } = useEffectResponse(toRef(props, 'effect'))
</script>

<template>
  <div class="response" data-effect-response>
    <EqResponseChart :curve="curve" :label="`Resposta de frequência de ${name}`" />
    <p v-if="error" class="response__error" role="status" data-eq-error>Não foi possível desenhar a resposta: {{ error }}</p>
  </div>
</template>

<style scoped>
.response {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.response__error {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-warning);
}
</style>
