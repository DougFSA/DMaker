<script setup lang="ts">
/* A casca da área Voz: título e abas (que são rotas) por cima da seção aberta. Cada seção é uma view em
   views/voice/ e entra no router como filha de /voz. */
import PageHeader from '@/components/layout/PageHeader.vue'
import RouteTabs, { type RouteTabItem } from '@/components/ui/RouteTabs.vue'

const tabs: RouteTabItem[] = [
  { to: '/voz', label: 'Vozes' },
  { to: '/voz/narracao', label: 'Narração' },
  { to: '/voz/pronuncia', label: 'Pronúncia' },
  { to: '/voz/isolar', label: 'Isolar voz' },
  { to: '/voz/corrigir', label: 'Corrigir fala' },
  { to: '/voz/trocar', label: 'Trocar voz' },
]
</script>

<template>
  <div class="voice">
    <PageHeader title="Voz" subtitle="Vozes, narração, pronúncia e ferramentas de áudio." />
    <RouteTabs :items="tabs" label="Seções da Voz" />
    <div class="voice__section"><RouterView /></div>
  </div>
</template>

<style scoped>
.voice__section {
  margin-top: var(--space-5);
}
</style>
