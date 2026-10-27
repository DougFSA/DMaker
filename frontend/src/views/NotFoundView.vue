<script setup lang="ts">
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
</script>

<template>
  <AppCard>
    <EmptyState icon="search" title="Página não encontrada" description="Esse endereço não existe na interface.">
      <AppButton to="/projetos" variant="primary">Ir para Projetos</AppButton>
    </EmptyState>
  </AppCard>
</template>
