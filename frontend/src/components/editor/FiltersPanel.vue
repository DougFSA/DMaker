<script setup lang="ts">
/* O painel Filtros: os grupos de campos do item selecionado na linha do tempo (ou os do projeto, sem seleção).
   É dirigido pelo catálogo (`lib/filterCatalog.json`): mostra só os grupos "aplicados", ou seja, os que já saem do
   padrão do schema; o "+" lista os outros e o "×" de um grupo o devolve ao padrão. A faixa A1 edita o clipe da V1. */
import { computed, onMounted, ref, watch } from 'vue'
import { PopoverContent, PopoverPortal, PopoverRoot, PopoverTrigger } from 'reka-ui'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppIcon from '@/components/ui/AppIcon.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import type { OptionItem } from '@/lib/editorLabels'
import { groupsFor, type FilterGroup, type FilterTarget } from '@/lib/filterCatalog'
import {
  contextKey,
  defaultsDefOf,
  isGroupApplied,
  isPinned,
  resetPaths,
  resetPathsIn,
  selectionFor,
  targetTitle,
} from '@/lib/filters'
import { displayLabel } from '@/lib/timeline'
import { useCatalogStore } from '@/stores/catalog'
import { useEditorStore } from '@/stores/editor'
import FilterGroupCard from './FilterGroupCard.vue'

interface GroupEntry {
  group: FilterGroup
  /** Onde o grupo mora na spec: a base fixa dos grupos do projeto ou o caminho do item selecionado. */
  base: string
  defName: string | null
  pinned: boolean
  /** Algum campo sai do padrão agora. */
  applied: boolean
}

const editor = useEditorStore()
const catalog = useCatalogStore()

onMounted(() => {
  // os formatos do campo "Formato" da Saída; sem eles o campo mostra só o que a spec já tem
  catalog.load().catch(() => undefined)
})

const presets = computed<OptionItem[]>(() =>
  catalog.presets.map((preset) => ({ value: preset.id, label: `${preset.platform} · ${preset.name} (${preset.id})` })),
)

/** O item de que os filtros falam: o último que a pessoa selecionou (Ctrl soma, e o painel segue o mais recente). */
const primary = computed(() => {
  const last = editor.selection[editor.selection.length - 1]
  return last ? editor.findItem(last) : null
})
const context = computed(() =>
  primary.value && editor.view ? selectionFor(primary.value.trackId, primary.value.item, editor.view) : null,
)
const target = computed<FilterTarget>(() => context.value?.target ?? 'project')
const selectionKey = computed(() => contextKey(context.value))

const subtitle = computed(() => {
  const title = targetTitle(target.value)
  const label = context.value && primary.value ? displayLabel(primary.value.item.label) : ''
  return label ? `${title} · ${label}` : title
})

const entries = computed<GroupEntry[]>(() =>
  groupsFor(target.value).map((group) => {
    const defName = defaultsDefOf(group, target.value)
    const base = group.base ?? context.value?.base ?? ''
    const read = (path: string) => editor.get(`${base}.${path}`)
    return {
      group,
      base,
      defName,
      pinned: isPinned(group, defName, editor.schema),
      applied: isGroupApplied(group, defName, editor.schema, read),
    }
  }),
)

/**
 * Os grupos que continuam à mostra: os abertos pelo "+" e os que já saíram do padrão alguma vez com esta seleção.
 * Sem isso, voltar um campo ao padrão faria o grupo sumir debaixo da mão de quem está digitando.
 */
const kept = ref(new Set<string>())
let keptFor = ''
watch(
  [entries, selectionKey],
  ([list, key]) => {
    if (key !== keptFor) {
      keptFor = key
      kept.value = new Set()
    }
    const fresh = list.filter((entry) => entry.applied && !kept.value.has(entry.group.id)).map((entry) => entry.group.id)
    if (fresh.length > 0) kept.value = new Set([...kept.value, ...fresh])
  },
  { immediate: true, flush: 'sync' },
)

const shown = computed(() => entries.value.filter((entry) => entry.applied || kept.value.has(entry.group.id)))
const available = computed(() => entries.value.filter((entry) => !shown.value.includes(entry)))

const menuOpen = ref(false)

function add(entry: GroupEntry): void {
  kept.value = new Set([...kept.value, entry.group.id])
  menuOpen.value = false
}

/** Devolve o grupo ao padrão: apaga os campos dele da spec, num passo só do desfazer. */
function remove(entry: GroupEntry): void {
  editor.flushPendingEdits()
  const paths = resetPaths(entry.group, entry.base, entry.defName, editor.schema)
  editor.mutate((draft) => resetPathsIn(draft, paths))
  const next = new Set(kept.value)
  next.delete(entry.group.id)
  kept.value = next
}

const ready = computed(() => !!editor.spec)
</script>

<template>
  <AppCard class="filters" title="Filtros" :subtitle="ready ? subtitle : undefined" flush>
    <template #actions>
      <PopoverRoot v-model:open="menuOpen">
        <PopoverTrigger as-child>
          <AppButton size="sm" :disabled="!ready" aria-label="Adicionar filtro" title="Adicionar um filtro a este item">
            <AppIcon name="plus" :size="16" />
            Filtro
          </AppButton>
        </PopoverTrigger>
        <PopoverPortal>
          <PopoverContent class="filters-menu" align="end" :side-offset="6" aria-label="Filtros que faltam">
            <ul v-if="available.length > 0" class="filters-menu__list">
              <li v-for="entry in available" :key="entry.group.id">
                <button type="button" class="filters-menu__item" :data-add-group="entry.group.id" @click="add(entry)">
                  {{ entry.group.label }}
                </button>
              </li>
            </ul>
            <p v-else class="filters-menu__empty">Nada mais para adicionar.</p>
          </PopoverContent>
        </PopoverPortal>
      </PopoverRoot>
    </template>

    <EmptyState v-if="!ready" icon="layers" title="Sem projeto aberto" description="Os filtros aparecem quando o projeto abrir." />

    <div v-else class="filters__body">
      <p v-if="!editor.schema && editor.referenceError" class="filters__note" role="status">
        Os padrões do schema não carregaram: os grupos mostram o que a spec tem.
      </p>
      <FilterGroupCard
        v-for="entry in shown"
        :key="`${selectionKey}:${entry.group.id}`"
        :group="entry.group"
        :base="entry.base"
        :presets="presets"
        :removable="!entry.pinned"
        @remove="remove(entry)"
      />
      <p v-if="shown.length === 0" class="filters__empty">Nenhum filtro aplicado. Use o botão Filtro para adicionar.</p>
    </div>
  </AppCard>
</template>

<style scoped>
.filters__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  /* a lista rola dentro do painel: filtro demais não estica a bancada nem empurra a linha do tempo para baixo */
  max-height: var(--editor-side-panel-height, 34rem);
  overflow-y: auto;
  padding: 0 var(--space-4) var(--space-4);
}

.filters__empty,
.filters__note {
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}

.filters__note {
  color: var(--color-warning);
}
</style>

<style>
.filters-menu {
  z-index: 70;
  min-width: 12rem;
  max-height: min(24rem, calc(100vh - 6rem));
  overflow-y: auto;
  padding: var(--space-2);
  background: var(--color-surface-raised);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
}

.filters-menu:focus {
  outline: none;
}

.filters-menu__list {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}

.filters-menu__item {
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  font-size: var(--text-sm);
  text-align: left;
  color: var(--color-text);
}

.filters-menu__item:hover,
.filters-menu__item:focus-visible {
  background: var(--color-surface-hover);
}

.filters-menu__empty {
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-soft);
}
</style>
