<script setup lang="ts">
import { useWorkspaceStore } from '@/stores/workspace'
import SidebarNav from './SidebarNav.vue'
import TopBar from './TopBar.vue'

const workspace = useWorkspaceStore()
</script>

<template>
  <div :class="['shell', { 'shell--collapsed': workspace.sidebarCollapsed }]">
    <a href="#conteudo" class="shell__skip">Ir para o conteúdo</a>
    <aside class="shell__sidebar">
      <SidebarNav :collapsed="workspace.sidebarCollapsed" />
    </aside>
    <div class="shell__main">
      <TopBar />
      <main id="conteudo" class="shell__content" tabindex="-1">
        <slot />
      </main>
    </div>
  </div>
</template>

<style scoped>
.shell {
  display: grid;
  grid-template-columns: var(--sidebar-width) minmax(0, 1fr);
  min-height: 100vh;
  transition: grid-template-columns 200ms ease;
}

.shell--collapsed {
  grid-template-columns: var(--sidebar-width-collapsed) minmax(0, 1fr);
}

.shell__sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
  background: var(--color-bg-soft);
  border-right: 1px solid var(--color-border);
}

.shell__main {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.shell__content {
  flex: 1;
  width: 100%;
  max-width: 80rem;
  margin: 0 auto;
  padding: var(--space-6) var(--space-5) var(--space-7);
}

.shell__content:focus {
  outline: none;
}

.shell__skip {
  position: absolute;
  top: -3rem;
  left: var(--space-3);
  z-index: 100;
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-pill);
  background: var(--color-accent);
  color: var(--color-on-accent);
  font-weight: 600;
}

.shell__skip:focus {
  top: var(--space-3);
}
</style>
