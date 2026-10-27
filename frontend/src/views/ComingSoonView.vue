<script setup lang="ts">
import { computed } from 'vue'
import PageHeader from '@/components/layout/PageHeader.vue'
import AppBadge from '@/components/ui/AppBadge.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { CLASSIC_UI_PATH, NAV_ITEMS } from '@/navigation'

const props = defineProps<{ itemKey: string }>()
const item = computed(() => NAV_ITEMS.find((candidate) => candidate.key === props.itemKey))
</script>

<template>
  <div v-if="item">
    <PageHeader :title="item.label" subtitle="Esta área chega nas próximas fases da interface nova.">
      <AppBadge tone="accent">em breve</AppBadge>
    </PageHeader>
    <AppCard>
      <EmptyState
        :icon="item.icon"
        :title="`${item.label} ainda está na interface clássica`"
        :description="item.promise"
      >
        <AppButton :href="CLASSIC_UI_PATH" variant="primary">Abrir a interface clássica</AppButton>
        <AppButton to="/projetos">Voltar para Projetos</AppButton>
      </EmptyState>
    </AppCard>
  </div>
</template>
