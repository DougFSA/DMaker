<script setup lang="ts">
/* O seletor "Tela" do editor: os seis layouts embutidos, os que a pessoa salvou, os painéis que aparecem e as ações
   de salvar como, excluir e restaurar o padrão. Escolher o layout "Voz" leva ao estúdio de voz, que é a aba que ele
   abre. */
import { PopoverContent, PopoverPortal, PopoverRoot, PopoverTrigger } from 'reka-ui'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppButton from '@/components/ui/AppButton.vue'
import AppCheckbox from '@/components/ui/AppCheckbox.vue'
import AppDialog from '@/components/ui/AppDialog.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import AppInput from '@/components/ui/AppInput.vue'
import { BUILTIN_NAMES, MOVABLE_PANELS, type MovablePanel } from '@/lib/editorLayout'
import { useScreenLayoutStore } from '@/stores/screenLayout'
import { panelsIn } from './panels'

const layout = useScreenLayoutStore()
const router = useRouter()

const open = ref(false)
const saveOpen = ref(false)
const newName = ref('')

const panelTitles = new Map(panelsIn('workbench').map((panel) => [panel.id, panel.title]))
const panelChoices = MOVABLE_PANELS.map((id) => ({ id, title: panelTitles.get(id) ?? id }))

const triggerText = computed(() => `${layout.name}${layout.modified ? ' (alterado)' : ''}`)

onMounted(() => void layout.loadSaved())

function choose(name: string): void {
  const chosen = layout.choose(name)
  open.value = false
  // o layout "Voz" abre o estúdio de voz, a aba que ele pede
  if (chosen?.tab === 'voice') void router.push({ name: 'voice' })
}

function startSaving(): void {
  newName.value = layout.isBuiltin ? '' : layout.name
  open.value = false
  saveOpen.value = true
}

async function save(): Promise<void> {
  if (await layout.saveAs(newName.value)) saveOpen.value = false
}

function restore(): void {
  layout.restoreDefault()
  open.value = false
}

async function removeCurrent(): Promise<void> {
  open.value = false
  await layout.removeCurrent()
}
</script>

<template>
  <PopoverRoot v-model:open="open">
    <PopoverTrigger as-child>
      <AppButton size="sm" aria-label="Layout da tela" title="Escolher como os painéis ficam na tela">
        <AppIcon name="grid" :size="16" />
        Tela: {{ triggerText }}
        <AppIcon name="chevron-down" :size="16" />
      </AppButton>
    </PopoverTrigger>

    <PopoverPortal>
      <PopoverContent class="layout-menu" align="end" :side-offset="8" aria-label="Layout da tela">
        <section class="layout-menu__section" aria-labelledby="layout-builtin">
          <h2 id="layout-builtin" class="layout-menu__heading">Embutidos</h2>
          <ul class="layout-menu__list">
            <li v-for="name in BUILTIN_NAMES" :key="name">
              <button
                type="button"
                class="layout-menu__item"
                :aria-current="layout.name === name ? 'true' : undefined"
                :data-layout="name"
                @click="choose(name)"
              >
                <span>{{ name }}</span>
                <AppIcon v-if="layout.name === name" name="check" :size="16" />
              </button>
            </li>
          </ul>
        </section>

        <section v-if="layout.savedNames.length > 0" class="layout-menu__section" aria-labelledby="layout-saved">
          <h2 id="layout-saved" class="layout-menu__heading">Salvos</h2>
          <ul class="layout-menu__list">
            <li v-for="name in layout.savedNames" :key="name">
              <button
                type="button"
                class="layout-menu__item"
                :aria-current="layout.name === name ? 'true' : undefined"
                :data-layout="name"
                @click="choose(name)"
              >
                <span>{{ name }}</span>
                <AppIcon v-if="layout.name === name" name="check" :size="16" />
              </button>
            </li>
          </ul>
        </section>

        <section class="layout-menu__section" aria-labelledby="layout-panels">
          <h2 id="layout-panels" class="layout-menu__heading">Painéis na tela</h2>
          <div class="layout-menu__panels">
            <AppCheckbox
              v-for="choice in panelChoices"
              :key="choice.id"
              :label="choice.title"
              :model-value="!layout.isHidden(choice.id)"
              @update:model-value="layout.setHidden(choice.id as MovablePanel, !$event)"
            />
          </div>
        </section>

        <div class="layout-menu__actions">
          <AppButton size="sm" @click="startSaving">Salvar layout como...</AppButton>
          <AppButton
            size="sm"
            :disabled="layout.isBuiltin"
            :title="layout.isBuiltin ? 'Os layouts embutidos não podem ser excluídos' : 'Excluir o layout salvo que está em uso'"
            @click="removeCurrent"
          >
            Excluir layout atual
          </AppButton>
          <AppButton size="sm" variant="ghost" @click="restore">Restaurar padrão</AppButton>
        </div>
      </PopoverContent>
    </PopoverPortal>
  </PopoverRoot>

  <AppDialog v-model:open="saveOpen" title="Salvar layout como" description="O layout guarda onde cada painel fica, o tamanho dos divisores e o que está oculto." size="sm">
    <form id="save-layout-form" class="save-form" @submit.prevent="save">
      <AppInput v-model="newName" label="Nome do layout" placeholder="Por exemplo, Revisão com mídia" required />
    </form>
    <template #footer>
      <AppButton @click="saveOpen = false">Cancelar</AppButton>
      <AppButton variant="primary" type="submit" form="save-layout-form" :loading="layout.busy" :disabled="!newName.trim()">Salvar</AppButton>
    </template>
  </AppDialog>
</template>

<style>
.layout-menu {
  z-index: 70;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  width: min(20rem, calc(100vw - 2rem));
  max-height: min(34rem, calc(100vh - 6rem));
  overflow-y: auto;
  padding: var(--space-3);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
}

.layout-menu:focus {
  outline: none;
}

.layout-menu__section {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.layout-menu__heading {
  padding: 0 var(--space-2);
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-text-muted);
}

.layout-menu__list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}

.layout-menu__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  font-size: var(--text-sm);
  text-align: left;
  color: var(--color-text);
}

.layout-menu__item[aria-current='true'] {
  background: var(--color-accent-bg);
  color: var(--color-accent-text);
}

.layout-menu__item:hover,
.layout-menu__item:focus-visible {
  background: var(--color-surface-hover);
}

.layout-menu__panels {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-1) var(--space-3);
  padding: 0 var(--space-2);
}

.layout-menu__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border);
}

.save-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
</style>
