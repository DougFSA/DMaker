<script setup lang="ts">
import PageHeader from '@/components/layout/PageHeader.vue'
import UnderConstruction from '@/components/layout/UnderConstruction.vue'

/** O projeto aberto no editor (`/editor/:name`); o menu lateral leva a `/editor`, sem nome. */
defineProps<{ name?: string }>()
</script>

<template>
  <PageHeader title="Editor" :subtitle="name ? `Projeto ${name}` : 'Escolha um projeto para editar.'" />
  <UnderConstruction
    title="Editor"
    description="Player, linha do tempo com trilhas, arrastar e aparar trechos, filtros e layouts de tela."
    classic="aba Linha do tempo"
    icon="film"
  />
</template>
