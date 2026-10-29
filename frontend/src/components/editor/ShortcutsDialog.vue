<script setup lang="ts">
/* A janela de atalhos (a tecla ?): lista os atalhos por categoria, e clicar numa tecla e apertar a nova a troca.
   Trocar para uma tecla que outro atalho já usa só avisa, não bloqueia: duas ações na mesma tecla é escolha da
   pessoa. As trocas ficam no navegador. */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppDialog from '@/components/ui/AppDialog.vue'
import {
  comboFromEvent,
  comboLabel,
  isModifierKey,
  keyLabel,
  SHORTCUT_CATEGORIES,
  type ShortcutDef,
  type ShortcutId,
} from '@/lib/keymap'
import { useKeymapStore } from '@/stores/keymap'

const keymap = useKeymapStore()

/** O atalho que está esperando a próxima tecla. */
const capturing = ref<ShortcutId | null>(null)
const notice = ref('')

const groups = computed(() =>
  SHORTCUT_CATEGORIES.map((category) => ({
    ...category,
    entries: keymap.entries.filter((entry) => entry.category === category.id),
  })).filter((group) => group.entries.length > 0),
)

function startCapture(entry: ShortcutDef): void {
  notice.value = ''
  capturing.value = entry.id
}

/** Na fase de captura da janela, antes de qualquer outro ouvinte: a tecla apertada é a nova, e não aciona nada. */
function onCaptureKey(event: KeyboardEvent): void {
  const id = capturing.value
  if (!id) return
  // segurar só o Ctrl ou o Shift ainda é montar a combinação
  if (isModifierKey(event.key)) return
  event.preventDefault()
  event.stopPropagation()
  capturing.value = null
  if (event.key === 'Escape') return
  const combo = comboFromEvent(event)
  const clash = keymap.conflictFor(combo, id)
  keymap.setBinding(id, combo)
  notice.value = clash ? `“${comboLabel(combo)}” já era o atalho de “${clash.label}”. Agora os dois usam essa tecla.` : ''
}

watch(capturing, (id) => {
  if (id) window.addEventListener('keydown', onCaptureKey, true)
  else window.removeEventListener('keydown', onCaptureKey, true)
})

// fechar a janela no meio da captura cancela a captura
watch(
  () => keymap.dialogOpen,
  (open) => {
    if (!open) {
      capturing.value = null
      notice.value = ''
    }
  },
)

onBeforeUnmount(() => window.removeEventListener('keydown', onCaptureKey, true))

function reset(): void {
  capturing.value = null
  notice.value = ''
  keymap.reset()
}
</script>

<template>
  <AppDialog
    v-model:open="keymap.dialogOpen"
    title="Atalhos de teclado"
    description="Clique numa tecla para trocá-la: a próxima combinação que você apertar vira o novo atalho."
    size="lg"
  >
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>

    <section v-for="group in groups" :key="group.id" class="group">
      <h3 class="group__title">{{ group.label }}</h3>
      <ul class="group__list">
        <li v-for="entry in group.entries" :key="entry.id" class="row">
          <span class="row__label">{{ entry.label }}</span>
          <button
            type="button"
            :class="['key', { 'key--capturing': capturing === entry.id, 'key--custom': !keymap.isDefault(entry.id) }]"
            :data-shortcut="entry.id"
            :aria-label="`${entry.label}: ${keyLabel(entry.keys)}. Clique para trocar a tecla.`"
            @click="startCapture(entry)"
          >
            {{ capturing === entry.id ? 'Pressione uma tecla...' : keyLabel(entry.keys) }}
          </button>
        </li>
      </ul>
    </section>

    <template #footer>
      <AppButton :disabled="keymap.customCount === 0" @click="reset">Restaurar padrões</AppButton>
      <AppButton variant="primary" @click="keymap.dialogOpen = false">Fechar</AppButton>
    </template>
  </AppDialog>
</template>

<style scoped>
.notice {
  margin-bottom: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--color-warning-bg);
  color: var(--color-warning);
  font-size: var(--text-sm);
}

.group + .group {
  margin-top: var(--space-4);
}

.group__title {
  margin-bottom: var(--space-2);
  font-size: var(--text-sm);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-text-soft);
}

.group__list {
  display: grid;
  gap: var(--space-1);
}

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-1) 0;
  border-bottom: 1px solid var(--color-border);
  font-size: var(--text-sm);
}

.key {
  flex: none;
  min-width: 6rem;
  padding: var(--space-1) var(--space-3);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-sm);
  background: var(--color-surface-raised);
  color: var(--color-text);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  cursor: pointer;
}

.key:hover {
  border-color: var(--color-accent);
}

.key--custom {
  color: var(--color-accent-text);
}

.key--capturing {
  border-color: var(--color-accent);
  background: var(--color-accent-bg);
  color: var(--color-accent-text);
}
</style>
