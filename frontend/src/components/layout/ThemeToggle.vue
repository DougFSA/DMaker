<script setup lang="ts">
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { useThemeStore } from '@/stores/theme'

const theme = useThemeStore()
</script>

<template>
  <AppButton
    variant="ghost"
    icon-only
    :aria-label="theme.theme === 'dark' ? 'Mudar para o tema claro' : 'Mudar para o tema escuro'"
    :title="theme.theme === 'dark' ? 'Tema claro' : 'Tema escuro'"
    @click="theme.toggle()"
  >
    <AppIcon :name="theme.theme === 'dark' ? 'sun' : 'moon'" />
  </AppButton>
</template>
