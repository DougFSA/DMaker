<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { SIZE_DEFAULTS, SIZE_RANGES } from '@/lib/editorLayout'
import { useScreenLayoutStore } from '@/stores/screenLayout'
import { useWorkspaceStore } from '@/stores/workspace'
import LayoutDivider from './LayoutDivider.vue'
import SidebarNav from './SidebarNav.vue'
import TopBar from './TopBar.vue'

const workspace = useWorkspaceStore()
const screenLayout = useScreenLayoutStore()
const route = useRoute()

/** A largura da barra lateral vem do layout de tela (o divisor entre ela e o conteúdo); recolhida, vale a medida fixa. */
const sidebarWidth = computed(() => screenLayout.layout.sizes['col-sidebar'] ?? SIZE_DEFAULTS['col-sidebar'])
const resizing = ref(false)
const shellStyle = computed(() => (workspace.sidebarCollapsed ? undefined : { '--sidebar-width': `${sidebarWidth.value}px` }))
</script>

<template>
  <div :class="['shell', { 'shell--collapsed': workspace.sidebarCollapsed, 'shell--resizing': resizing }]" :style="shellStyle">
    <a href="#conteudo" class="shell__skip">Ir para o conteúdo</a>
    <aside class="shell__sidebar">
      <SidebarNav :collapsed="workspace.sidebarCollapsed" />
      <LayoutDivider
        v-if="!workspace.sidebarCollapsed"
        class="shell__resizer"
        orientation="vertical"
        label="Largura da barra lateral"
        :value="sidebarWidth"
        :min="SIZE_RANGES['col-sidebar'][0]"
        :max="SIZE_RANGES['col-sidebar'][1]"
        :per-pixel="1"
        :step="16"
        @resize="screenLayout.setSize('col-sidebar', $event)"
        @drag="resizing = $event"
      />
    </aside>
    <div class="shell__main">
      <TopBar />
      <main id="conteudo" :class="['shell__content', { 'shell__content--wide': route.meta.wide }]" tabindex="-1">
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

/* arrastando o divisor, a largura acompanha o mouse na hora, sem a animação do recolher */
.shell--resizing {
  transition: none;
}

.shell__sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
  background: var(--color-bg-soft);
  border-right: 1px solid var(--color-border);
}

.shell__resizer {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 5;
  width: 6px;
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

.shell__content--wide {
  max-width: none;
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
