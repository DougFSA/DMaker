<script setup lang="ts">
import PageHeader from '@/components/layout/PageHeader.vue'
import UnderConstruction from '@/components/layout/UnderConstruction.vue'
</script>

<template>
  <PageHeader title="Fila" subtitle="As narrações longas que esperam a vez." />
  <UnderConstruction
    title="Fila"
    description="Acompanhar as narrações em andamento, pausar, reordenar e baixar o que ficou pronto."
    classic="aba Voz, seção Fila de narrações"
    icon="queue"
  />
</template>
