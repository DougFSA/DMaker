<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon, { type IconName } from '@/components/ui/AppIcon.vue'
import { NAVIGATION_TOGGLE_ID } from '@/composables/useNavigationDrawer'
import { useWorkspaceStore } from '@/stores/workspace'
import JobsMenu from './JobsMenu.vue'
import ThemeToggle from './ThemeToggle.vue'

const workspace = useWorkspaceStore()

/** O mesmo botão faz duas coisas: em tela estreita abre e fecha a gaveta; nas outras recolhe e alarga a barra lateral. */
const toggleLabel = computed(() => {
  if (workspace.narrow) return workspace.drawerOpen ? 'Fechar o menu de navegação' : 'Abrir o menu de navegação'
  return workspace.sidebarCollapsed ? 'Expandir a barra lateral' : 'Recolher a barra lateral'
})
const toggleIcon = computed<IconName>(() => {
  if (workspace.narrow) return 'list'
  return workspace.sidebarCollapsed ? 'chevron-right' : 'chevron-left'
})
</script>

<template>
  <header :class="['topbar', { 'topbar--narrow': workspace.narrow }]">
    <AppButton
      :id="NAVIGATION_TOGGLE_ID"
      variant="ghost"
      icon-only
      :aria-label="toggleLabel"
      :aria-controls="workspace.narrow ? 'barra-lateral' : undefined"
      :aria-expanded="workspace.narrow ? workspace.drawerOpen : undefined"
      @click="workspace.toggleNavigation()"
    >
      <AppIcon :name="toggleIcon" />
    </AppButton>

    <div class="topbar__project" aria-label="Projeto atual">
      <span class="topbar__label">Projeto atual</span>
      <RouterLink
        v-if="workspace.currentProject"
        :to="{ name: 'project', params: { name: workspace.currentProject } }"
        class="topbar__name"
      >
        {{ workspace.currentProject }}
      </RouterLink>
      <span v-else class="topbar__none">nenhum aberto</span>
    </div>

    <div class="topbar__actions">
      <JobsMenu :compact="workspace.narrow" />
      <ThemeToggle />
    </div>
  </header>
</template>

<style scoped>
.topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  gap: var(--space-4);
  height: var(--topbar-height);
  padding: 0 var(--space-5);
  background: color-mix(in srgb, var(--color-bg) 86%, transparent);
  border-bottom: 1px solid var(--color-border);
  backdrop-filter: blur(10px);
}

/* tela estreita: menos folga nas bordas, e o rótulo vai para cima do nome em vez de dividir a linha com ele */
.topbar--narrow {
  gap: var(--space-2);
  padding: 0 var(--space-3);
}

.topbar--narrow .topbar__project {
  flex-direction: column;
  align-items: flex-start;
  gap: 0;
  line-height: 1.25;
}

.topbar--narrow .topbar__name {
  max-width: 100%;
}

.topbar__project {
  display: flex;
  flex: 1;
  align-items: baseline;
  gap: var(--space-2);
  min-width: 0;
}

.topbar__label {
  font-size: var(--text-xs);
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-text-muted);
  white-space: nowrap;
}

.topbar__name {
  overflow: hidden;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.topbar__none {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.topbar__actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
</style>
