<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { NARROW_QUERY, useMediaQuery } from '@/composables/useMediaQuery'
import { useNavigationDrawer } from '@/composables/useNavigationDrawer'
import { SIZE_DEFAULTS, SIZE_RANGES } from '@/lib/editorLayout'
import { useScreenLayoutStore } from '@/stores/screenLayout'
import { useWorkspaceStore } from '@/stores/workspace'
import LayoutDivider from './LayoutDivider.vue'
import SidebarNav from './SidebarNav.vue'
import TopBar from './TopBar.vue'

const workspace = useWorkspaceStore()
const screenLayout = useScreenLayoutStore()
const route = useRoute()

/** Em tela estreita a barra lateral sai da grade e vira gaveta; o valor é lido já na montagem, antes da primeira pintura. */
const narrow = useMediaQuery(NARROW_QUERY)
watch(narrow, (value) => workspace.setNarrow(value), { immediate: true })

const sidebar = ref<HTMLElement | null>(null)
const { onDrawerClick } = useNavigationDrawer(sidebar)
/** A gaveta aberta cobre a tela: o resto fica inerte (sem foco, sem leitor de tela) até ela fechar. */
const drawerOpen = computed(() => workspace.narrow && workspace.drawerOpen)

/**
 * `inert` em texto, não booleano: no navegador o Vue liga e desliga a propriedade com `'true'` e `undefined`; onde a
 * propriedade não existe (o jsdom dos testes) ele grava o atributo ou o tira. Com `true`/`false` esse segundo caso
 * deixaria `inert="false"` na tag, e o atributo, mesmo com esse valor, continua valendo como ligado.
 */
function inert(on: boolean): 'true' | undefined {
  return on ? 'true' : undefined
}

/** A largura da barra lateral vem do layout de tela (o divisor entre ela e o conteúdo); recolhida, vale a medida fixa. */
const sidebarWidth = computed(() => screenLayout.layout.sizes['col-sidebar'] ?? SIZE_DEFAULTS['col-sidebar'])
const resizing = ref(false)
/** Na gaveta vale a largura padrão do token: o layout de tela guardado é o da barra fixa de uma janela larga. */
const shellStyle = computed(() =>
  workspace.sidebarCompact || workspace.narrow ? undefined : { '--sidebar-width': `${sidebarWidth.value}px` },
)
</script>

<template>
  <div
    :class="[
      'shell',
      { 'shell--collapsed': workspace.sidebarCompact, 'shell--narrow': workspace.narrow, 'shell--resizing': resizing },
    ]"
    :style="shellStyle"
  >
    <a href="#conteudo" class="shell__skip" :inert="inert(drawerOpen)">Ir para o conteúdo</a>
    <Transition name="shell-backdrop">
      <div v-if="drawerOpen" class="shell__backdrop" aria-hidden="true" @click="workspace.closeDrawer()" />
    </Transition>
    <aside
      id="barra-lateral"
      ref="sidebar"
      :class="['shell__sidebar', { 'is-open': drawerOpen }]"
      :role="workspace.narrow ? 'dialog' : undefined"
      :aria-modal="workspace.narrow ? 'true' : undefined"
      :aria-label="workspace.narrow ? 'Menu de navegação' : undefined"
      :tabindex="workspace.narrow ? -1 : undefined"
      :inert="inert(workspace.narrow && !drawerOpen)"
      @click="onDrawerClick"
    >
      <SidebarNav :collapsed="workspace.sidebarCompact" />
      <LayoutDivider
        v-if="!workspace.sidebarCompact && !workspace.narrow"
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
    <div class="shell__main" :inert="inert(drawerOpen)">
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

/* Tela estreita: a barra lateral sai da grade e vira gaveta por cima do conteúdo, fechada até alguém abri-la. */
.shell--narrow {
  grid-template-columns: minmax(0, 1fr);
}

.shell--narrow .shell__sidebar {
  position: fixed;
  inset: 0 auto 0 0;
  z-index: 50;
  width: min(var(--sidebar-width), 85vw);
  height: auto;
  overscroll-behavior: contain;
  /* fechada, fica fora da tela e inerte (atributo `inert`): sem `visibility: hidden`, que impediria o foco de entrar já na abertura */
  transform: translateX(-100%);
  transition: transform 200ms ease;
}

.shell--narrow .shell__sidebar.is-open {
  transform: none;
  box-shadow: var(--shadow-lg);
}

.shell--narrow .shell__sidebar:focus {
  outline: none;
}

.shell__backdrop {
  position: fixed;
  inset: 0;
  z-index: 45;
  background: var(--color-overlay);
}

.shell-backdrop-enter-active,
.shell-backdrop-leave-active {
  transition: opacity 200ms ease;
}

.shell-backdrop-enter-from,
.shell-backdrop-leave-to {
  opacity: 0;
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
