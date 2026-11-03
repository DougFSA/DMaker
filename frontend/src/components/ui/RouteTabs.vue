<script setup lang="ts">
/* Abas que são páginas: cada uma leva a uma rota e a ativa é a da URL (a Voz usa para Vozes, Narração,
   Pronúncia, Isolar, Corrigir e Trocar). Abas de painéis na mesma página usam AppTabs. */
import { RouterLink, type RouteLocationRaw } from 'vue-router'

export interface RouteTabItem {
  to: RouteLocationRaw
  label: string
}

defineProps<{
  items: RouteTabItem[]
  /** Nome da navegação para leitor de tela ("Seções da Voz"). */
  label: string
}>()
</script>

<template>
  <nav :aria-label="label">
    <ul class="tabs__list">
      <li v-for="item in items" :key="item.label">
        <RouterLink :to="item.to" class="tabs__tab" exact-active-class="is-active">{{ item.label }}</RouterLink>
      </li>
    </ul>
  </nav>
</template>

<style scoped src="./tabs.css"></style>
