<script setup lang="ts">
import PageHeader from '@/components/layout/PageHeader.vue'
import UnderConstruction from '@/components/layout/UnderConstruction.vue'
</script>

<template>
  <PageHeader title="Modelos" subtitle="Os modelos de IA instalados na máquina." />
  <UnderConstruction
    title="Modelos"
    description="Ver o que está baixado, baixar o que falta e apagar o que não usa mais."
    classic="aba Modelos"
    icon="layers"
  />
</template>
