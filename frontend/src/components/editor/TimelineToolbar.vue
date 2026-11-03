<script setup lang="ts">
/* A barra de ferramentas da linha do tempo: cortar, remover, lift, duplicar, aparar, encaixe, zoom e os botões de
   painéis (F filtros, M mídia) e de atalhos. Cada botão chama o mesmo comando do atalho de teclado dele, e o balão
   mostra a tecla (que muda se a pessoa trocou o atalho). */
import { computed } from 'vue'
import { useEditorActions } from '@/composables/useEditorActions'
import AppButton from '@/components/ui/AppButton.vue'
import type { ShortcutId } from '@/lib/keymap'
import { useEditorStore } from '@/stores/editor'
import { useKeymapStore } from '@/stores/keymap'
import { useScreenLayoutStore } from '@/stores/screenLayout'
import { useTimelineStore } from '@/stores/timeline'

const editor = useEditorStore()
const timeline = useTimelineStore()
const keymap = useKeymapStore()
const layout = useScreenLayoutStore()
const actions = useEditorActions()

const ready = computed(() => !!editor.view)

/** O balão de um botão: o que ele faz e a tecla do atalho. */
function hint(text: string, id: ShortcutId): string {
  const keys = keymap.labelFor(id)
  return keys ? `${text} (${keys})` : text
}
</script>

<template>
  <div class="bar" role="toolbar" aria-label="Ferramentas da linha do tempo">
    <div class="bar__group" role="group" aria-label="Edição">
      <AppButton size="sm" :disabled="!ready" :title="hint('Cortar o trecho no cursor', 'split')" @click="actions.split()">
        Cortar
      </AppButton>
      <AppButton size="sm" :disabled="!ready" :title="hint('Remover e fechar a lacuna', 'remove_ripple')" @click="actions.removeSelected()">
        Remover
      </AppButton>
      <AppButton size="sm" :disabled="!ready" :title="hint('Lift: remover sem deixar lacuna na V1', 'lift')" @click="actions.lift()">
        Lift
      </AppButton>
      <AppButton size="sm" :disabled="!ready" :title="hint('Duplicar a seleção', 'duplicate')" @click="actions.duplicateSelected()">
        Duplicar
      </AppButton>
      <AppButton size="sm" :disabled="!ready" :title="hint('Aparar a entrada até o cursor', 'trim_in')" @click="actions.trimTo('in')">
        Aparar entrada
      </AppButton>
      <AppButton size="sm" :disabled="!ready" :title="hint('Aparar a saída até o cursor', 'trim_out')" @click="actions.trimTo('out')">
        Aparar saída
      </AppButton>
    </div>

    <div class="bar__group" role="group" aria-label="Encaixe">
      <AppButton
        size="sm"
        :variant="timeline.snapEnabled ? 'primary' : 'secondary'"
        :aria-pressed="timeline.snapEnabled"
        :title="hint('Encaixe nas bordas, no cursor e nas pontas', 'toggle_snap')"
        @click="timeline.toggleSnap()"
      >
        Snap
      </AppButton>
      <AppButton
        size="sm"
        :aria-pressed="timeline.rippleAlways"
        :title="hint('A V1 sempre fecha as lacunas (ripple)', 'toggle_ripple')"
        @click="timeline.toggleRipple()"
      >
        {{ timeline.rippleAlways ? 'Ripple: V1 (sempre)' : 'Ripple: V1' }}
      </AppButton>
    </div>

    <div class="bar__group" role="group" aria-label="Zoom">
      <AppButton size="sm" icon-only aria-label="Afastar" :title="hint('Afastar', 'zoom_out')" @click="timeline.zoomOut()">−</AppButton>
      <AppButton size="sm" icon-only aria-label="Aproximar" :title="hint('Aproximar', 'zoom_in')" @click="timeline.zoomIn()">+</AppButton>
      <AppButton size="sm" :disabled="!ready" :title="hint('Ajustar o vídeo inteiro à largura da tela', 'zoom_fit')" @click="timeline.zoomFit()">
        Ajustar
      </AppButton>
    </div>

    <div class="bar__group" role="group" aria-label="Painéis">
      <AppButton
        size="sm"
        icon-only
        aria-label="Filtros"
        :variant="layout.isHidden('filters') ? 'secondary' : 'primary'"
        :aria-pressed="!layout.isHidden('filters')"
        title="Mostrar ou ocultar o painel Filtros"
        @click="layout.toggle('filters')"
      >
        F
      </AppButton>
      <AppButton
        size="sm"
        icon-only
        aria-label="Mídia"
        :variant="layout.isHidden('media') ? 'secondary' : 'primary'"
        :aria-pressed="!layout.isHidden('media')"
        title="Mostrar ou ocultar o painel Mídia"
        @click="layout.toggle('media')"
      >
        M
      </AppButton>
      <AppButton size="sm" icon-only aria-label="Atalhos de teclado" :title="hint('Atalhos de teclado', 'show_shortcuts')" @click="keymap.openDialog()">
        ?
      </AppButton>
    </div>
  </div>
</template>

<style scoped>
.bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2) var(--space-4);
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--color-border);
}

.bar__group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1);
}
</style>
