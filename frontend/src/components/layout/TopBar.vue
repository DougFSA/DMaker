<script setup lang="ts">
import { RouterLink } from 'vue-router'
import AppButton from '@/components/ui/AppButton.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import { useWorkspaceStore } from '@/stores/workspace'
import JobsMenu from './JobsMenu.vue'
import ThemeToggle from './ThemeToggle.vue'

const workspace = useWorkspaceStore()
</script>

<template>
  <header class="topbar">
    <AppButton
      variant="ghost"
      icon-only
      :aria-label="workspace.sidebarCollapsed ? 'Expandir a barra lateral' : 'Recolher a barra lateral'"
      @click="workspace.toggleSidebar()"
    >
      <AppIcon :name="workspace.sidebarCollapsed ? 'chevron-right' : 'chevron-left'" />
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
      <JobsMenu />
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
