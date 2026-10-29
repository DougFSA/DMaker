<script setup lang="ts">
/* O que cada área mostra até a frente dela chegar: diz o que vem aí e leva ao equivalente na interface clássica. */
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import type { IconName } from '@/components/ui/AppIcon.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { CLASSIC_UI_PATH } from '@/navigation'

defineProps<{
  /** O nome da tela ("Narração", "Dublagem"). */
  title: string
  /** O que a tela vai trazer. */
  description: string
  /** Onde achar a mesma função na interface clássica ("aba Voz, seção Narração"). */
  classic: string
  icon: IconName
}>()
</script>

<template>
  <AppCard>
    <EmptyState :icon="icon" :title="`${title}: em construção`" :description="description">
      <AppBadge tone="accent">em construção</AppBadge>
      <p class="classic-hint">Por enquanto, use a {{ classic }} da interface clássica.</p>
      <AppButton :href="CLASSIC_UI_PATH" variant="primary">Abrir a interface clássica</AppButton>
      <AppButton to="/projetos">Voltar para Projetos</AppButton>
    </EmptyState>
  </AppCard>
</template>

<style scoped>
.classic-hint {
  flex-basis: 100%;
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}
</style>
