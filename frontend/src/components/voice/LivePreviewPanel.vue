<script setup lang="ts">
/* A prévia ao vivo da narração: a frase "Tocando fala i de n", o aviso de que é a fala crua e o botão que a silencia
   sem parar a geração. Fica à vista depois que o trabalho acaba, porque o áudio ainda toca por mais um tempo. */
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'

defineProps<{
  /** A frase de andamento ("Tocando fala 2 de 5"). */
  status: string
  /** A prévia já foi silenciada ou parada: não há mais o que silenciar. */
  finished: boolean
  /** A narração foi parada a pedido: não vem arquivo final. */
  stopped?: boolean
}>()

defineEmits<{ mute: [] }>()
</script>

<template>
  <section class="live" aria-label="Prévia ao vivo">
    <p class="live__status" role="status" aria-live="polite">
      <AppIcon name="mic" :size="16" />
      <span>{{ status }}</span>
    </p>
    <p v-if="stopped" class="live__hint">
      A narração parou antes do fim, então não há arquivo final. Gerar o mesmo roteiro de novo não sintetiza outra vez
      as falas que já saíram.
    </p>
    <p v-else class="live__hint">
      Cada fala toca assim que fica pronta e é a fala crua, sem o acabamento final. O arquivo final, com acabamento
      broadcast, aparece abaixo quando o roteiro terminar.
    </p>
    <AppButton size="sm" :disabled="finished" title="Silencia a prévia ao vivo; não interrompe a geração" @click="$emit('mute')">
      Silenciar prévia
    </AppButton>
  </section>
</template>

<style scoped>
.live {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-soft);
}

.live__status {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-weight: 600;
  color: var(--color-accent-text);
  font-variant-numeric: tabular-nums;
}

.live__hint {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}
</style>
